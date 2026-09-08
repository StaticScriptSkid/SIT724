#!/usr/bin/env python3
"""
llm_judge.py — LLM-as-judge pilot.

Scores the same blinded responses a human peer rater scored through the form in
peer_review/, using the `judge:` model in config.yaml (GLM-5.2 by default), so
AI-judge vs human-judge agreement can be compared item-for-item.

How blinding and alignment work:
    - Items come from pipeline.peer_review.build_pack(): the same pack_id, blind_id,
      case_id and variant_index the human form used, so every row lines up with the
      human's returned file. The judge prompt never sees which model wrote a response.
    - Output is the same JSON shape the human form produces, so
      `python pipeline/peer_review.py --import <file>` accepts it unchanged.

Usage:
    python pipeline/llm_judge.py                      # judge all 150, resume if interrupted
    python pipeline/llm_judge.py --limit 3            # smoke test on the first 3 items
    python pipeline/llm_judge.py --match peer_review/returns/sit724-peer-SS-complete.json
    python pipeline/llm_judge.py --fresh              # ignore an existing output file

Design notes:
    - temperature 0 (see config.yaml judge:); thinking disabled so the reply is bare JSON.
    - Each verdict is validated (7 integer scores 1-5, judgement in accept/reject/refine,
      non-empty reasoning, refine_detail when refine). One retry on a malformed reply,
      with a short correction appended; still-malformed items are recorded with an
      `error` and count as incomplete (the importer skips them).
    - The output file is rewritten after every item, so a crash or rate-limit stop
      loses nothing and a re-run resumes from where it stopped.
    - The judge prompt text is SHA-256 hashed into judge_meta, mirroring how the
      generation pipeline hashes the locked feedback prompt.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.generate import (  # noqa: E402
    _is_permanent_error,
    call_model_with_retries,
    load_config,
    load_dotenv,
    sha256_of,
)
from pipeline.peer_review import DEFAULT_RUN_ID, RUBRIC_DIM_KEYS, build_pack  # noqa: E402

load_dotenv(ROOT / ".env")

CONFIG_PATH = ROOT / "config.yaml"
RETURNS_DIR = ROOT / "peer_review" / "returns"
DEFAULT_OUTPUT = RETURNS_DIR / "sit724_judge_glm52_complete.json"
JUDGEMENTS = ("accept", "reject", "refine")

# Verbatim judge prompt (agreed 9 Sep 2026). Placeholders are substituted with
# str.replace, not str.format, because the JSON example contains literal braces.
JUDGE_PROMPT = """You are scoring one piece of AI-generated feedback on a beginner Python mistake.

Question given to the model:
{question}

The model's response:
{response_text}

Correct answer: {correct_answer}
Known misconception being tested: {misconception}

Score the response on these 7 dimensions, 1-5 each:
accuracy, selectivity, clarity, informativeness, specificity, level_of_detail, ethics_safety

Then give a judgement: "accept", "reject", or "refine".
Then give a one-sentence reason for that judgement, specific to this response.
If judgement is "refine", also give a refine_detail sentence saying what should change.

Return only this JSON:
{"rubric_scores": {...}, "judgement": "...", "reasoning": "...", "refine_detail": "..."}"""

RETRY_SUFFIX = (
    "\n\nYour previous reply could not be parsed. Return ONLY the JSON object described above, "
    "with integer scores 1-5 for all seven dimensions and no other text."
)


def render_judge_prompt(item: dict) -> str:
    text = JUDGE_PROMPT
    for key in ("question", "response_text", "correct_answer", "misconception"):
        text = text.replace("{" + key + "}", str(item.get(key, "")))
    return text


# ---------------------------------------------------------------------------
# Parsing + validation
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict:
    """Pull the first {...} object out of a reply, tolerating ``` fences and prose."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in reply")
    obj = json.loads(cleaned[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("top-level JSON is not an object")
    return obj


def validate_verdict(obj: dict) -> dict:
    """Return a normalised verdict or raise ValueError describing what is wrong."""
    scores_in = obj.get("rubric_scores")
    if not isinstance(scores_in, dict):
        raise ValueError("rubric_scores missing or not an object")
    scores: dict[str, int] = {}
    for key in RUBRIC_DIM_KEYS:
        if key not in scores_in:
            raise ValueError(f"rubric_scores missing '{key}'")
        val = scores_in[key]
        if isinstance(val, bool):
            raise ValueError(f"rubric_scores.{key} is a boolean")
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        if isinstance(val, str) and val.strip().isdigit():
            val = int(val.strip())
        if not isinstance(val, int) or not 1 <= val <= 5:
            raise ValueError(f"rubric_scores.{key}={val!r} is not an integer 1-5")
        scores[key] = val

    judgement = str(obj.get("judgement", "")).strip().lower()
    if judgement not in JUDGEMENTS:
        raise ValueError(f"judgement={obj.get('judgement')!r} not one of {JUDGEMENTS}")

    reasoning = str(obj.get("reasoning") or "").strip()
    if not reasoning:
        raise ValueError("reasoning is empty")

    refine_detail = str(obj.get("refine_detail") or "").strip()
    if judgement == "refine" and not refine_detail:
        raise ValueError("judgement is refine but refine_detail is empty")

    return {
        "rubric_scores": scores,
        "judgement": judgement,
        "reasoning": reasoning,
        "refine_detail": refine_detail,
    }


# ---------------------------------------------------------------------------
# One item
# ---------------------------------------------------------------------------

def judge_item(item: dict, judge_cfg: dict, params: dict) -> dict:
    """Call the judge for one blinded item. Never raises; failures are recorded."""
    prompt = render_judge_prompt(item)
    attempts_log: list[str] = []
    row = {
        "blind_id": item["blind_id"],
        "case_id": item["case_id"],
        "variant_index": item.get("variant_index"),
        "prompt_hash": item.get("prompt_hash", ""),
        "rubric_scores": {},
        "judgement": "",
        "reasoning": "",
        "refine_detail": "",
        "timestamp": None,
    }

    for parse_attempt in (1, 2):
        text_prompt = prompt if parse_attempt == 1 else prompt + RETRY_SUFFIX
        result = call_model_with_retries(judge_cfg, text_prompt, params)
        if result.get("error"):
            attempts_log.append(f"api: {result['error']}")
            break  # transport-level failure already retried inside call_model_with_retries
        raw = result.get("response_text") or ""
        try:
            verdict = validate_verdict(extract_json(raw))
        except (ValueError, json.JSONDecodeError) as e:
            attempts_log.append(f"parse attempt {parse_attempt}: {e}")
            continue
        row.update(verdict)
        row["timestamp"] = datetime.now(timezone.utc).isoformat()
        row["judge_attempts"] = parse_attempt
        return row

    row["error"] = " | ".join(attempts_log) or "unknown failure"
    row["timestamp"] = datetime.now(timezone.utc).isoformat()
    return row


def is_valid_row(row: dict) -> bool:
    try:
        validate_verdict(row)
        return not row.get("error")
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Whole pack
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _api_host(judge_cfg: dict) -> str:
    base = os.environ.get(judge_cfg.get("api_base_env", ""), "")
    return re.sub(r"^https?://", "", base).split("/")[0] if base else "(default)"


def assert_matches_human_file(pack: dict, human_path: Path) -> None:
    human = json.loads(human_path.read_text(encoding="utf-8"))
    if human.get("pack_id") != pack["pack_id"]:
        raise SystemExit(
            f"pack mismatch: human file is '{human.get('pack_id')}', judge pack is '{pack['pack_id']}'"
        )
    human_ids = {r.get("blind_id") for r in human.get("responses", [])}
    pack_ids = {it["blind_id"] for it in pack["items"]}
    if human_ids != pack_ids:
        raise SystemExit("blind_id sets differ between the human file and the judge pack")
    by_id = {r["blind_id"]: r for r in human["responses"]}
    bad = [it["blind_id"] for it in pack["items"] if by_id[it["blind_id"]].get("case_id") != it["case_id"]]
    if bad:
        raise SystemExit(f"case_id disagrees for {len(bad)} blind_ids, e.g. {bad[:3]}")
    print(f"Alignment OK: {len(pack_ids)} blind_ids match {human_path.name} (pack {pack['pack_id']})")


def run_judge(
    *,
    run_id: str = DEFAULT_RUN_ID,
    output: Path = DEFAULT_OUTPUT,
    limit: int | None = None,
    fresh: bool = False,
    match: Path | None = None,
) -> dict:
    cfg = load_config(str(CONFIG_PATH))
    judge_cfg = dict(cfg.get("judge") or {})
    if not judge_cfg:
        raise SystemExit("config.yaml has no `judge:` block")
    judge_cfg.setdefault("name", judge_cfg.get("rater_id", "judge"))
    key_env = judge_cfg.get("api_key_env")
    if not key_env or not os.environ.get(key_env):
        raise SystemExit(f"Missing API key: set {key_env or 'the judge api_key_env'} in .env")

    params = {
        "temperature": float(judge_cfg.get("temperature", 0.0)),
        "max_tokens": int(judge_cfg.get("max_tokens", 600)),
        "retries": int(judge_cfg.get("retries", 3)),
        "retry_backoff_seconds": float(judge_cfg.get("retry_backoff_seconds", 5)),
    }

    pack, _blind_map = build_pack(run_id=run_id)
    if match is not None:
        assert_matches_human_file(pack, match)

    items = pack["items"][:limit] if limit else pack["items"]

    # Resume: keep already-valid rows from a previous partial run.
    previous: dict[str, dict] = {}
    if output.exists() and not fresh:
        try:
            prev = json.loads(output.read_text(encoding="utf-8"))
            if prev.get("pack_id") == pack["pack_id"]:
                previous = {r["blind_id"]: r for r in prev.get("responses", []) if is_valid_row(r)}
        except (json.JSONDecodeError, KeyError, TypeError):
            previous = {}
    if previous:
        print(f"Resuming: {len(previous)} valid verdicts already on disk")

    started = datetime.now(timezone.utc).isoformat()
    rows: dict[str, dict] = dict(previous)

    def payload() -> dict:
        ordered = [rows.get(it["blind_id"]) for it in items if rows.get(it["blind_id"])]
        n_complete = sum(1 for r in ordered if is_valid_row(r))
        return {
            "pack_id": pack["pack_id"],
            "run_id": pack["run_id"],
            "rater_id": judge_cfg.get("rater_id", "judge"),
            "rater_name": judge_cfg.get("rater_name", judge_cfg.get("rater_id", "judge")),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "n_items": len(items),
            "n_complete": n_complete,
            "judge_meta": {
                "provider": judge_cfg.get("provider"),
                "model_id": judge_cfg.get("model_id"),
                "api_host": _api_host(judge_cfg),
                "temperature": params["temperature"],
                "max_tokens": params["max_tokens"],
                "request_extras": judge_cfg.get("request_extras") or {},
                "judge_prompt_sha256": sha256_of(JUDGE_PROMPT),
                "blind_to_model": True,
                "started_at": started,
            },
            "responses": ordered,
        }

    total = len(items)
    t0 = time.monotonic()
    aborted = None
    for i, item in enumerate(items, start=1):
        bid = item["blind_id"]
        if bid in rows:
            continue
        rows[bid] = judge_item(item, judge_cfg, params)
        r = rows[bid]
        status = (
            f"{r['judgement']} {sum(r['rubric_scores'].values())}/35"
            if is_valid_row(r) else f"FAILED ({r.get('error', '')[:120]})"
        )
        print(f"[{i}/{total}] {bid} {item['case_id']}: {status}", flush=True)
        _atomic_write(output, payload())
        # A billing/auth/config failure will hit every remaining item identically — stop now.
        if r.get("error") and _is_permanent_error(r["error"]):
            aborted = r["error"]
            rows.pop(bid, None)  # don't persist a doomed row; re-run resumes from here
            _atomic_write(output, payload())
            break

    if aborted:
        print(
            f"\nABORTED after a non-retryable error: {aborted}\n"
            "Fix the cause (balance / key / model id) and re-run — completed verdicts are kept.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    final = payload()
    _atomic_write(output, final)
    elapsed = time.monotonic() - t0
    try:
        shown = output.relative_to(ROOT)
    except ValueError:
        shown = output
    print(f"\nDone: {final['n_complete']}/{final['n_items']} valid verdicts in {elapsed:.0f}s -> {shown}")
    failed = [r["blind_id"] for r in final["responses"] if not is_valid_row(r)]
    if failed:
        print(f"Incomplete (re-run to retry): {failed}")
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-as-judge pilot over the blinded peer-review pack")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=None, help="Judge only the first N items (smoke test)")
    parser.add_argument("--fresh", action="store_true", help="Ignore any existing output file")
    parser.add_argument("--match", default=None, help="Human rater's returned JSON to verify alignment against")
    args = parser.parse_args()
    run_judge(
        run_id=args.run_id,
        output=Path(args.output),
        limit=args.limit,
        fresh=args.fresh,
        match=Path(args.match) if args.match else None,
    )


if __name__ == "__main__":
    main()
