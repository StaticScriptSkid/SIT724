#!/usr/bin/env python3
"""
generate.py — run the locked SIT724 feedback prompt against every case in
cases/cases.json, for every model in config.yaml, and log the results.

Usage:
    # Prove the pipeline works with no API calls and no cost (safe to demo):
    python pipeline/generate.py --dry-run

    # Print an estimated cost without calling any API:
    python pipeline/generate.py --estimate

    # Real run (needs API keys set as env vars per config.yaml):
    python pipeline/generate.py

Design notes (see prompts/PROMPT_LOCK.md and docs/decision_log.md):
    - Prompt is locked (verbatim from the SIT723 thesis) so results stay comparable.
    - Every run gets its own write-once output directory: outputs/<run_id>/
    - Every rendered prompt is hashed (SHA-256) so prompt drift is detectable later
      even without diffing prompts/template.txt directly.
    - Only 'final' cases are included by default; 'draft' cases (Q11+, awaiting
      supervisor review) are excluded unless --include-drafts is passed.
    - On any API failure, the call retries up to `retries` times with a fixed
      backoff (fallback plan for rate limits / transient downtime). If retries
      are exhausted, the failure is logged in the response record rather than
      crashing the run, so one bad call doesn't lose the rest of the batch.
"""

import argparse
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

import os


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_cases(path: str, include_drafts: bool) -> list:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cases = data["cases"]
    if not include_drafts:
        cases = [c for c in cases if c.get("status") == "final"]
    return cases, data.get("benchmark_version", "unknown")


def render_prompt(template: str, case: dict) -> str:
    return template.format(
        question=case["question"],
        correct_answer=case["correct_answer"],
        wrong_answer=case["wrong_answer"],
        misconception=case["misconception"],
    )


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_run_id(mode: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = uuid.uuid4().hex[:8]
    return f"{ts}-{short}" if mode != "dry-run" else f"dryrun_{ts}-{short}"


# ---------------------------------------------------------------------------
# Provider calls (only used when NOT in --dry-run mode)
# ---------------------------------------------------------------------------

def call_openai_compatible(model_cfg: dict, rendered_prompt: str, params: dict) -> str:
    api_key = os.environ.get(model_cfg["api_key_env"])
    api_base = os.environ.get(model_cfg.get("api_base_env", ""), "https://api.openai.com/v1")
    if not api_key:
        raise RuntimeError(f"Missing API key env var: {model_cfg['api_key_env']}")
    resp = requests.post(
        f"{api_base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model_cfg["model_id"],
            "messages": [{"role": "user", "content": rendered_prompt}],
            "temperature": params["temperature"],
            "max_tokens": params["max_tokens"],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def call_anthropic(model_cfg: dict, rendered_prompt: str, params: dict) -> str:
    api_key = os.environ.get(model_cfg["api_key_env"])
    if not api_key:
        raise RuntimeError(f"Missing API key env var: {model_cfg['api_key_env']}")
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model_cfg["model_id"],
            "max_tokens": params["max_tokens"],
            "temperature": params["temperature"],
            "messages": [{"role": "user", "content": rendered_prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def call_gemini(model_cfg: dict, rendered_prompt: str, params: dict) -> str:
    api_key = os.environ.get(model_cfg["api_key_env"])
    if not api_key:
        raise RuntimeError(f"Missing API key env var: {model_cfg['api_key_env']}")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_cfg['model_id']}:generateContent?key={api_key}"
    )
    resp = requests.post(
        url,
        json={
            "contents": [{"parts": [{"text": rendered_prompt}]}],
            "generationConfig": {
                "temperature": params["temperature"],
                "maxOutputTokens": params["max_tokens"],
            },
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


PROVIDER_FUNCS = {
    "openai-compatible": call_openai_compatible,
    "anthropic": call_anthropic,
    "gemini": call_gemini,
}


def call_model_with_retries(model_cfg: dict, rendered_prompt: str, params: dict) -> dict:
    """Fallback plan: retry on failure with fixed backoff; log (not crash) on exhaustion."""
    provider = model_cfg["provider"]
    func = PROVIDER_FUNCS.get(provider)
    if func is None:
        return {"response_text": None, "error": f"Unknown provider: {provider}"}
    if requests is None:
        return {"response_text": None, "error": "The 'requests' package is not installed."}

    last_error = None
    for attempt in range(1, params["retries"] + 1):
        try:
            text = func(model_cfg, rendered_prompt, params)
            return {"response_text": text, "error": None, "attempts": attempt}
        except Exception as e:  # noqa: BLE001 — deliberately broad: log and retry
            last_error = str(e)
            if attempt < params["retries"]:
                time.sleep(params["retry_backoff_seconds"])
    return {"response_text": None, "error": last_error, "attempts": params["retries"]}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run the SIT724 feedback-evaluation pipeline.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Render prompts and log records, but make no API calls.")
    parser.add_argument("--estimate", action="store_true", help="Print an estimated cost (needs pricing filled in config.yaml) and exit.")
    parser.add_argument("--include-drafts", action="store_true", help="Also run draft (unreviewed) cases.")
    parser.add_argument("--output-dir", default=None, help="Override outputs directory root.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    params = cfg["generation_params"]
    models = cfg["models"]

    cases, benchmark_version = load_cases(cfg["paths"]["cases_file"], args.include_drafts)
    with open(cfg["paths"]["prompt_template"], "r", encoding="utf-8") as f:
        template = f.read()

    if args.estimate:
        pricing = cfg.get("pricing_usd_per_1k_tokens", {})
        missing = [m["name"] for m in models if pricing.get(m["name"], {}).get("output") is None]
        if missing:
            print("Cannot estimate cost yet — pricing not filled in config.yaml for:", ", ".join(missing))
            print(f"Would run {len(cases)} cases x {len(models)} models = {len(cases) * len(models)} calls.")
            return
        # crude estimate assuming max_tokens output, ~200 input tokens per call
        total = 0.0
        for m in models:
            price = pricing[m["name"]]
            calls = len(cases)
            total += calls * (200 / 1000 * price["input"] + params["max_tokens"] / 1000 * price["output"])
        print(f"Estimated cost for {len(cases)} cases x {len(models)} models: ${total:.2f} USD")
        return

    mode = "dry-run" if args.dry_run else "live"
    run_id = new_run_id(mode)
    output_root = Path(args.output_dir or cfg["paths"]["outputs_dir"])
    run_dir = output_root / (run_id if mode == "live" else run_id)
    run_dir.mkdir(parents=True, exist_ok=False)  # write-once: fail loudly on collision

    started_utc = datetime.now(timezone.utc).isoformat()

    manifest = {
        "run_id": run_id,
        "mode": mode,
        "started_utc": started_utc,
        "prompt_version": cfg["prompt_version"],
        "benchmark_version": benchmark_version,
        "generation_params": params,
        "models": [m["name"] for m in models],
        "n_cases": len(cases),
    }

    records = []
    for case in cases:
        rendered = render_prompt(template, case)
        prompt_hash = sha256_of(rendered)
        for model_cfg in models:
            record = {
                "run_id": run_id,
                "mode": mode,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "case_id": case["id"],
                "model_name": model_cfg["name"],
                "provider": model_cfg["provider"],
                "model_requested": model_cfg["model_id"],
                "prompt_version": cfg["prompt_version"],
                "benchmark_version": benchmark_version,
                "params": {"temperature": params["temperature"], "max_tokens": params["max_tokens"]},
                "prompt_sha256": prompt_hash,
            }
            if args.dry_run:
                record["response_text"] = "[DRY RUN — no API call made]"
                record["rendered_prompt"] = rendered[:200] + (" [...]" if len(rendered) > 200 else "")
            else:
                result = call_model_with_retries(model_cfg, rendered, params)
                record["response_text"] = result["response_text"]
                record["error"] = result.get("error")
                record["attempts"] = result.get("attempts")
            records.append(record)

    with open(run_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    with open(run_dir / "responses.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    failures = [r for r in records if r.get("error")]
    print(f"Run {run_id} complete: {len(records)} records written to {run_dir}")
    if not args.dry_run:
        print(f"  {len(records) - len(failures)} succeeded, {len(failures)} failed after retries")
    else:
        print("  (dry run — no API calls were made, no cost incurred)")


if __name__ == "__main__":
    main()
