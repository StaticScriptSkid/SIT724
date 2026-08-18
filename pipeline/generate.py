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
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import yaml

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


def load_dotenv(path: Optional[str | Path] = None) -> Optional[Path]:
    """Load KEY=value pairs from a local .env into os.environ.

    Does not override variables already set in the shell. Missing file is a no-op.
    .env is gitignored — only .env.example is tracked.
    """
    env_path = Path(path) if path else Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return None
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
    return env_path


load_dotenv()


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
    api_base = os.environ.get(model_cfg.get("api_base_env", ""), "https://api.openai.com/v1").rstrip("/")
    if not api_key:
        raise RuntimeError(f"Missing API key env var: {model_cfg['api_key_env']}")

    temperature = model_cfg.get("temperature", params["temperature"])
    max_tokens = model_cfg.get("max_tokens", params["max_tokens"])
    body = {
        "model": model_cfg["model_id"],
        "messages": [{"role": "user", "content": rendered_prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # Provider-specific extras (e.g. Kimi thinking flags) from config.yaml.
    extras = model_cfg.get("request_extras") or {}
    if extras:
        body.update(extras)

    resp = requests.post(
        f"{api_base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=60,
    )
    if not resp.ok:
        detail = (resp.text or "").strip().replace("\n", " ")
        if len(detail) > 300:
            detail = detail[:300] + "..."
        raise RuntimeError(f"{resp.status_code} Client Error for {api_base}/chat/completions: {detail}")
    message = resp.json()["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if content:
        return content
    # Some Kimi models put draft text in reasoning_content when content is empty.
    reasoning = (message.get("reasoning_content") or "").strip()
    if reasoning:
        raise RuntimeError(
            "Model returned empty content (only reasoning_content). "
            "Check model_id / temperature / thinking settings for this provider."
        )
    raise RuntimeError("Model returned empty content.")


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


def _gemini_visible_text(payload: dict) -> str:
    """Return the student-facing answer, not thought/scratchpad fragments.

    Gemini 3.x often puts internal reasoning in parts[0] (or thought parts).
    Reading only parts[0] made live runs look 'ok' while storing a cutoff stub.
    """
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {payload}")
    cand = candidates[0]
    parts = (cand.get("content") or {}).get("parts") or []
    visible = []
    for part in parts:
        if part.get("thought"):
            continue
        text = part.get("text")
        if text:
            visible.append(text)
    text = "".join(visible).strip()
    finish = cand.get("finishReason")
    if not text:
        raise RuntimeError(
            f"Gemini returned empty visible text (finishReason={finish!r})."
        )
    if finish == "MAX_TOKENS" and len(text) < 120:
        raise RuntimeError(
            f"Gemini output still truncated (finishReason=MAX_TOKENS, {len(text)} chars)."
        )
    return text


def call_gemini(model_cfg: dict, rendered_prompt: str, params: dict) -> str:
    api_key = os.environ.get(model_cfg["api_key_env"])
    if not api_key:
        raise RuntimeError(f"Missing API key env var: {model_cfg['api_key_env']}")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_cfg['model_id']}:generateContent"
    )
    # Gemini 3.x uses some of maxOutputTokens for internal reasoning before the
    # visible reply. Shared config max_tokens=400 is enough for DeepSeek but
    # cuts Gemini off mid-sentence. Give Gemini more room; other models unchanged.
    gemini_max_tokens = max(int(params["max_tokens"]), 2048)
    resp = requests.post(
        url,
        headers={"x-goog-api-key": api_key, "content-type": "application/json"},
        json={
            "contents": [{"parts": [{"text": rendered_prompt}]}],
            "generationConfig": {
                "temperature": params["temperature"],
                "maxOutputTokens": gemini_max_tokens,
            },
        },
        timeout=60,
    )
    resp.raise_for_status()
    return _gemini_visible_text(resp.json())


PROVIDER_FUNCS = {
    "openai-compatible": call_openai_compatible,
    "anthropic": call_anthropic,
    "gemini": call_gemini,
}


def _redact_secrets(message: str) -> str:
    """Strip API keys from logged error strings (e.g. Gemini ?key= query param)."""
    return re.sub(r"([?&]key=)[^&\s]+", r"\1REDACTED", message, flags=re.IGNORECASE)


def _is_permanent_error(message: str) -> bool:
    """Errors that will not succeed on retry (missing keys, unknown provider, etc.)."""
    permanent_markers = (
        "Missing API key",
        "Unknown provider",
        "The 'requests' package is not installed",
        "404 Client Error",
    )
    return any(marker in message for marker in permanent_markers)


def call_model_with_retries(model_cfg: dict, rendered_prompt: str, params: dict) -> dict:
    """Fallback plan: retry on failure with fixed backoff; log (not crash) on exhaustion."""
    provider = model_cfg["provider"]
    func = PROVIDER_FUNCS.get(provider)
    if func is None:
        return {"response_text": None, "error": f"Unknown provider: {provider}"}
    if requests is None:
        return {"response_text": None, "error": "The 'requests' package is not installed."}

    # Fail fast before any network/retry loop when the key env var is unset.
    api_key_env = model_cfg.get("api_key_env")
    if api_key_env and not os.environ.get(api_key_env):
        return {
            "response_text": None,
            "error": f"Missing API key env var: {api_key_env}",
            "attempts": 0,
        }

    last_error = None
    for attempt in range(1, params["retries"] + 1):
        try:
            text = func(model_cfg, rendered_prompt, params)
            return {"response_text": text, "error": None, "attempts": attempt}
        except Exception as e:  # noqa: BLE001 — deliberately broad: log and retry
            last_error = _redact_secrets(str(e))
            if _is_permanent_error(last_error):
                return {"response_text": None, "error": last_error, "attempts": attempt}
            if attempt < params["retries"]:
                time.sleep(params["retry_backoff_seconds"])
    return {"response_text": None, "error": last_error, "attempts": params["retries"]}


# ---------------------------------------------------------------------------
# Shared run entry point (CLI + GUI)
# ---------------------------------------------------------------------------

ProgressCallback = Optional[Callable[[str], None]]
CancelCheck = Optional[Callable[[], bool]]


class MissingAPIKeysError(RuntimeError):
    """Raised when a live run is attempted without required API key env vars."""

    def __init__(self, missing: list):
        self.missing = missing
        names = ", ".join(missing)
        super().__init__(
            f"No API keys set. Need at least one of: {names}. "
            "Export the env var(s) then restart Streamlit / the CLI "
            "(see Config tab / config.yaml)."
        )


def missing_api_key_envs(models: list) -> list:
    """Return unique api_key_env names that are unset in the current process."""
    missing = []
    seen = set()
    for m in models:
        env = m.get("api_key_env")
        if not env or env in seen:
            continue
        seen.add(env)
        if not os.environ.get(env):
            missing.append(env)
    return missing


def api_key_status(models: list) -> list:
    """Per-model key presence for GUI display: [{name, api_key_env, present}, ...]."""
    rows = []
    for m in models:
        env = m.get("api_key_env", "")
        rows.append({
            "name": m.get("name"),
            "api_key_env": env,
            "present": bool(env and os.environ.get(env)),
        })
    return rows


def models_ready_for_live(models: list) -> tuple[list, list]:
    """Split config models into (has_key, missing_key)."""
    ready, skipped = [], []
    for m in models:
        env = m.get("api_key_env")
        if env and os.environ.get(env):
            ready.append(m)
        else:
            skipped.append(m)
    return ready, skipped


def run_pipeline(
    config_path: str = "config.yaml",
    dry_run: bool = False,
    include_drafts: bool = False,
    output_dir: Optional[str] = None,
    on_progress: ProgressCallback = None,
    should_cancel: CancelCheck = None,
) -> dict:
    """
    Run the feedback-evaluation pipeline (same logic as the CLI).

    on_progress: optional callable(message: str) invoked with status lines as
    work proceeds, so a GUI can stream progress without reimplementing the loop.
    should_cancel: optional callable() -> bool; when True, stop between calls and
    write whatever records were collected so far (manifest.cancelled = true).

    Returns a summary dict:
        run_id, mode, run_dir, n_records, n_succeeded, n_failed, dry_run, cancelled
    """
    def emit(msg: str) -> None:
        if on_progress is not None:
            on_progress(msg)

    def cancelled() -> bool:
        return bool(should_cancel and should_cancel())

    cfg = load_config(config_path)
    params = cfg["generation_params"]
    models = cfg["models"]
    skipped_names: list[str] = []

    # Live runs: call only models whose API key env var is set.
    if not dry_run:
        ready, skipped = models_ready_for_live(models)
        if not ready:
            raise MissingAPIKeysError(missing_api_key_envs(models))
        skipped_names = [m["name"] for m in skipped]
        models = ready

    cases, benchmark_version = load_cases(cfg["paths"]["cases_file"], include_drafts)
    with open(cfg["paths"]["prompt_template"], "r", encoding="utf-8") as f:
        template = f.read()

    mode = "dry-run" if dry_run else "live"
    run_id = new_run_id(mode)
    output_root = Path(output_dir or cfg["paths"]["outputs_dir"])
    run_dir = output_root / run_id
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
    if skipped_names:
        manifest["models_skipped_missing_key"] = skipped_names

    total = len(cases) * len(models)
    if skipped_names:
        emit(f"Skipping models with no API key: {', '.join(skipped_names)}")
    emit(f"Starting {mode} run {run_id}: {len(cases)} cases x {len(models)} models = {total} calls")

    records = []
    done = 0
    was_cancelled = False
    try:
        for case in cases:
            if cancelled():
                was_cancelled = True
                break
            rendered = render_prompt(template, case)
            prompt_hash = sha256_of(rendered)
            for model_cfg in models:
                if cancelled():
                    was_cancelled = True
                    break
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
                if dry_run:
                    record["response_text"] = "[DRY RUN — no API call made]"
                    record["rendered_prompt"] = rendered[:200] + (" [...]" if len(rendered) > 200 else "")
                else:
                    result = call_model_with_retries(model_cfg, rendered, params)
                    record["response_text"] = result["response_text"]
                    record["error"] = result.get("error")
                    record["attempts"] = result.get("attempts")
                records.append(record)
                done += 1
                status = "ok" if not record.get("error") else f"ERROR: {record.get('error')}"
                emit(f"[{done}/{total}] {case['id']} × {model_cfg['name']}: {status}")
            if was_cancelled:
                break
    except Exception:
        # Still persist whatever we have if something unexpected blows up mid-run.
        raise
    finally:
        if was_cancelled:
            manifest["cancelled"] = True
            emit(f"Cancelled after {done}/{total} calls — writing partial results to {run_dir}")

        with open(run_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        with open(run_dir / "responses.jsonl", "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    failures = [r for r in records if r.get("error")]
    n_succeeded = len(records) - len(failures)
    if was_cancelled:
        emit(f"Run {run_id} cancelled: {len(records)} records written to {run_dir}")
    else:
        emit(f"Run {run_id} complete: {len(records)} records written to {run_dir}")
    if not dry_run:
        emit(f"  {n_succeeded} succeeded, {len(failures)} failed after retries")
    else:
        emit("  (dry run — no API calls were made, no cost incurred)")

    return {
        "run_id": run_id,
        "mode": mode,
        "run_dir": str(run_dir),
        "n_records": len(records),
        "n_succeeded": n_succeeded,
        "n_failed": len(failures),
        "dry_run": dry_run,
        "cancelled": was_cancelled,
        "models": [m["name"] for m in models],
        "models_skipped_missing_key": skipped_names,
    }


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

    if args.estimate:
        cfg = load_config(args.config)
        params = cfg["generation_params"]
        models = cfg["models"]
        cases, _benchmark_version = load_cases(cfg["paths"]["cases_file"], args.include_drafts)
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

    try:
        summary = run_pipeline(
            config_path=args.config,
            dry_run=args.dry_run,
            include_drafts=args.include_drafts,
            output_dir=args.output_dir,
            on_progress=None,  # CLI keeps the original final-only printouts below
        )
    except MissingAPIKeysError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1) from e

    if summary.get("cancelled"):
        print(f"Run {summary['run_id']} cancelled: {summary['n_records']} records written to {summary['run_dir']}")
    else:
        print(f"Run {summary['run_id']} complete: {summary['n_records']} records written to {summary['run_dir']}")
    if not args.dry_run:
        print(f"  {summary['n_succeeded']} succeeded, {summary['n_failed']} failed after retries")
        skipped = summary.get("models_skipped_missing_key") or []
        if skipped:
            print(f"  skipped (no API key): {', '.join(skipped)}")
    else:
        print("  (dry run — no API calls were made, no cost incurred)")


if __name__ == "__main__":
    main()
