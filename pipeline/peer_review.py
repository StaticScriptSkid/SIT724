#!/usr/bin/env python3
"""
Blinded peer-review pack for the 150/150 live run.

Builds a Google-Forms-style HTML file (model names stripped, item order
shuffled) so a second rater can score Q1–Q30 × 5 models without seeing
which model wrote each reply. Returned JSON is imported into
judgement_log/entries.json using a local blind map that is never embedded
in the form.

Usage:
    python pipeline/peer_review.py --build
    python pipeline/peer_review.py --import path/to/friend-scores.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from judgement_log.validate_log import validate_entries
from pipeline.validate_cases import load_json
CASES_PATH = ROOT / "cases" / "cases.json"
RUBRIC_PATH = ROOT / "rubric" / "rubric.json"
OUTPUTS_DIR = ROOT / "outputs"
JUDGEMENT_ENTRIES = ROOT / "judgement_log" / "entries.json"
JUDGEMENT_SCHEMA = ROOT / "judgement_log" / "schema.json"
TEMPLATE_PATH = ROOT / "peer_review" / "form_template.html"
GENERATED_DIR = ROOT / "peer_review" / "generated"

DEFAULT_RUN_ID = "20260819T010032Z-477c3a3e"
SHUFFLE_SEED = 724

RUBRIC_DIM_KEYS = [
    "accuracy",
    "selectivity",
    "clarity",
    "informativeness",
    "specificity",
    "level_of_detail",
    "ethics_safety",
]

# Strings that would unblind a rater if they leaked into the HTML pack.
_MODEL_LEAK_NEEDLES = (
    "deepseek-chat",
    "gemini-flash",
    "openai-gpt",
    "claude-sonnet",
    "gpt-4o",
    "gemini-3.5",
    "kimi-k2",
    "anthropic",
    "moonshot",
)


def next_entry_id(entries: list[dict]) -> str:
    nums = []
    for e in entries:
        eid = e.get("entry_id") or ""
        if eid.startswith("JL-"):
            try:
                nums.append(int(eid.split("-", 1)[1]))
            except ValueError:
                continue
    n = (max(nums) + 1) if nums else 1
    return f"JL-{n:04d}"


def load_responses(run_dir: Path) -> list[dict]:
    path = run_dir / "responses.jsonl"
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def scorable_records(run_dir: Path) -> list[dict]:
    out = []
    for r in load_responses(run_dir):
        text = r.get("response_text") or ""
        if r.get("error") or not text or "DRY RUN" in text:
            continue
        out.append(r)
    return out


def _blind_id(n: int) -> str:
    return f"I{n:03d}"


def build_pack(
    *,
    run_id: str = DEFAULT_RUN_ID,
    seed: int = SHUFFLE_SEED,
) -> tuple[dict, list[dict]]:
    """Return (public pack for the form, local blind map). Model names stay in the map only."""
    run_dir = OUTPUTS_DIR / run_id
    if not (run_dir / "manifest.json").exists():
        raise FileNotFoundError(f"No pipeline run at outputs/{run_id}/")

    cases_by_id = {c["id"]: c for c in load_json(CASES_PATH).get("cases", [])}
    rubric = load_json(RUBRIC_PATH)
    records = scorable_records(run_dir)
    records.sort(key=lambda r: (r.get("case_id") or "", r.get("model_name") or ""))
    if not records:
        raise ValueError(f"Run {run_id} has no scorable live responses.")

    rng = random.Random(seed)
    by_case: dict[str, list[dict]] = {}
    for rec in records:
        by_case.setdefault(rec["case_id"], []).append(rec)
    case_ids = list(by_case.keys())
    rng.shuffle(case_ids)

    # Blind IDs are only meaningful relative to one pack build, so every map row
    # carries the pack_id and import refuses a returned file from a different build.
    pack_id = f"sit724-150-bycase-{run_id}-seed{seed}"

    items = []
    blind_map = []
    seq = 0
    for case_id in case_ids:
        recs = list(by_case[case_id])
        rng.shuffle(recs)
        variant_total = len(recs)
        case = cases_by_id.get(case_id) or {}
        for variant_index, rec in enumerate(recs, start=1):
            seq += 1
            bid = _blind_id(seq)
            model_name = rec["model_name"]
            items.append(
                {
                    "blind_id": bid,
                    "case_id": case_id,
                    "topic": case.get("topic", ""),
                    "question": case.get("question", ""),
                    "correct_answer": case.get("correct_answer", ""),
                    "wrong_answer": case.get("wrong_answer", ""),
                    "misconception": case.get("misconception", ""),
                    "response_text": rec.get("response_text") or "",
                    "prompt_hash": rec.get("prompt_sha256") or "",
                    "variant_index": variant_index,
                    "variant_total": variant_total,
                }
            )
            blind_map.append(
                {
                    "pack_id": pack_id,
                    "blind_id": bid,
                    "case_id": case_id,
                    "model": model_name,
                    "prompt_hash": rec.get("prompt_sha256") or "",
                    "ai_response_ref": (
                        f"outputs/{run_id}/responses.jsonl"
                        f"#case_id={case_id}&model_name={model_name}"
                    ),
                }
            )

    pack = {
        "pack_id": pack_id,
        "run_id": run_id,
        "n_items": len(items),
        "shuffle_seed": seed,
        "rubric_version": rubric.get("rubric_version", ""),
        "rubric_scale": rubric.get("scale", ""),
        "dimensions": rubric.get("dimensions", []),
        "items": items,
    }
    return pack, blind_map


def pack_leak_warnings(pack: dict) -> list[str]:
    """Warn if a model slug appears in the public pack (would unblind the rater)."""
    blob = json.dumps(pack, ensure_ascii=False).lower()
    return [n for n in _MODEL_LEAK_NEEDLES if n.lower() in blob]


def render_html(pack: dict) -> str:
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Missing form template: {TEMPLATE_PATH}")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = json.dumps(pack, ensure_ascii=False).replace("<", "\\u003c")
    if "__PACK_JSON__" not in template:
        raise ValueError("form_template.html is missing the __PACK_JSON__ placeholder")
    return template.replace("__PACK_JSON__", payload)


def write_generated_pack(pack: dict, blind_map: list[dict]) -> dict[str, Path]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    html_path = GENERATED_DIR / "SIT724_peer_review.html"
    pack_path = GENERATED_DIR / "pack.json"
    map_path = GENERATED_DIR / "blind_map.json"
    html_path.write_text(render_html(pack), encoding="utf-8")
    pack_path.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    map_path.write_text(json.dumps(blind_map, indent=2) + "\n", encoding="utf-8")
    return {"html": html_path, "pack": pack_path, "blind_map": map_path}


def load_generated_map(run_id: str = DEFAULT_RUN_ID) -> list[dict]:
    map_path = GENERATED_DIR / "blind_map.json"
    if map_path.exists():
        data = json.loads(map_path.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            return data
    _, blind_map = build_pack(run_id=run_id)
    return blind_map


def peer_file_to_entries(
    payload: dict,
    blind_map: list[dict],
    existing: list[dict],
) -> tuple[list[dict], list[str]]:
    """Turn a friend's downloaded JSON into judgement-log entries. Does not write."""
    warnings: list[str] = []
    by_blind = {row["blind_id"]: row for row in blind_map}
    rater_id = (payload.get("rater_id") or "").strip()
    if not rater_id:
        raise ValueError("Returned file is missing rater_id.")

    # Refuse a file produced by a different form build: same blind IDs would map
    # to different (case, model) pairs and the scores would land on the wrong model.
    map_pack_ids = {row.get("pack_id") for row in blind_map if row.get("pack_id")}
    file_pack_id = payload.get("pack_id")
    if map_pack_ids and file_pack_id and file_pack_id not in map_pack_ids:
        raise ValueError(
            f"Returned file is from form build '{file_pack_id}' but the local blind map is for "
            f"'{sorted(map_pack_ids)[0]}'. The rater used an older HTML file — ask them to open the "
            f"current SIT724_peer_review.html (their progress carries over) and export again."
        )
    if map_pack_ids and not file_pack_id:
        warnings.append("returned file has no pack_id — cannot confirm it matches the current form build")

    run_id = payload.get("run_id") or DEFAULT_RUN_ID
    answers = payload.get("responses") or payload.get("answers") or []
    if not isinstance(answers, list) or not answers:
        raise ValueError("Returned file has no responses array.")

    existing_triples = {
        (e.get("case_id"), e.get("model"), e.get("rater_id")) for e in existing
    }
    next_id = next_entry_id(existing)
    new_entries: list[dict] = []
    used_blinds = set()

    for i, ans in enumerate(answers):
        bid = ans.get("blind_id")
        if not bid:
            warnings.append(f"response[{i}] skipped: no blind_id")
            continue
        if bid in used_blinds:
            warnings.append(f"{bid} skipped: duplicate in returned file")
            continue
        used_blinds.add(bid)
        mapped = by_blind.get(bid)
        if mapped is None:
            warnings.append(f"{bid} skipped: not in blind map (wrong pack?)")
            continue
        # Second, per-row guard: the form writes case_id next to each blind_id.
        if ans.get("case_id") and ans["case_id"] != mapped["case_id"]:
            warnings.append(
                f"{bid} skipped: file says {ans['case_id']} but blind map says "
                f"{mapped['case_id']} (wrong pack?)"
            )
            continue

        scores = ans.get("rubric_scores") or {}
        judgement = ans.get("judgement")
        reasoning = (ans.get("reasoning") or "").strip()
        if not judgement or not reasoning:
            warnings.append(f"{bid} skipped: missing judgement or reasoning")
            continue
        if judgement == "refine" and not (ans.get("refine_detail") or "").strip():
            warnings.append(f"{bid} skipped: refine requires refine_detail")
            continue

        try:
            scored = {k: int(scores[k]) for k in RUBRIC_DIM_KEYS}
        except (KeyError, TypeError, ValueError):
            warnings.append(f"{bid} skipped: incomplete rubric_scores")
            continue
        if judgement not in ("accept", "reject", "refine"):
            warnings.append(f"{bid} skipped: invalid judgement {judgement!r}")
            continue

        triple = (mapped["case_id"], mapped["model"], rater_id)
        if triple in existing_triples:
            warnings.append(
                f"{bid} skipped: {mapped['case_id']} × {mapped['model']} "
                f"already logged for {rater_id}"
            )
            continue

        entry = {
            "entry_id": next_id,
            "run_id": run_id,
            "case_id": mapped["case_id"],
            "model": mapped["model"],
            "rater_id": rater_id,
            "prompt_hash": mapped.get("prompt_hash") or ans.get("prompt_hash") or "",
            "ai_response_ref": mapped["ai_response_ref"],
            "rubric_scores": scored,
            "judgement": judgement,
            "reasoning": reasoning,
            "timestamp": ans.get("timestamp")
            or payload.get("completed_at")
            or datetime.now(timezone.utc).isoformat(),
        }
        if judgement == "refine":
            entry["refine_detail"] = (ans.get("refine_detail") or "").strip()

        new_entries.append(entry)
        existing_triples.add(triple)
        n = int(next_id.split("-", 1)[1]) + 1
        next_id = f"JL-{n:04d}"

    return new_entries, warnings


def import_peer_file(path: Path, *, run_id: str = DEFAULT_RUN_ID) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Returned file must be a JSON object.")
    existing = load_json(JUDGEMENT_ENTRIES) if JUDGEMENT_ENTRIES.exists() else []
    if not isinstance(existing, list):
        existing = []
    blind_map = load_generated_map(run_id=payload.get("run_id") or run_id)
    new_entries, warnings = peer_file_to_entries(payload, blind_map, existing)
    if not new_entries:
        return {
            "ok": False,
            "n_imported": 0,
            "n_total": len(existing),
            "warnings": warnings or ["Nothing to import."],
            "errors": [],
        }

    combined = list(existing) + new_entries
    backup = JUDGEMENT_ENTRIES.read_text(encoding="utf-8") if JUDGEMENT_ENTRIES.exists() else "[]\n"
    JUDGEMENT_ENTRIES.write_text(json.dumps(combined, indent=2) + "\n", encoding="utf-8")
    check = validate_entries(JUDGEMENT_ENTRIES, JUDGEMENT_SCHEMA)
    if not check["ok"]:
        JUDGEMENT_ENTRIES.write_text(backup, encoding="utf-8")
        return {
            "ok": False,
            "n_imported": 0,
            "n_total": len(existing),
            "warnings": warnings,
            "errors": check["errors"],
        }
    return {
        "ok": True,
        "n_imported": len(new_entries),
        "n_total": check["n_entries"],
        "warnings": warnings,
        "errors": [],
        "rater_counts": check["rater_counts"],
    }


def _cmd_build(run_id: str) -> int:
    pack, blind_map = build_pack(run_id=run_id)
    leaks = pack_leak_warnings(pack)
    paths = write_generated_pack(pack, blind_map)
    print(f"Built blinded pack: {pack['n_items']} items from run {run_id}")
    print(f"  HTML (send this to your friend): {paths['html']}")
    print(f"  Pack JSON:                       {paths['pack']}")
    print(f"  Blind map (keep local):          {paths['blind_map']}")
    if leaks:
        print("WARNING: possible model-name leak in the public pack:")
        for needle in leaks:
            print(f"  - {needle}")
        return 1
    return 0


def _cmd_import(path: Path, run_id: str) -> int:
    result = import_peer_file(path, run_id=run_id)
    for w in result["warnings"]:
        print(f"  skip: {w}")
    if not result["ok"]:
        print("IMPORT FAILED")
        for err in result["errors"]:
            print(f"  - {err}")
        return 1
    print(
        f"Imported {result['n_imported']} entries "
        f"(log now has {result['n_total']})."
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Blinded SIT724 peer-review form")
    parser.add_argument("--build", action="store_true", help="Write the HTML form + local blind map")
    parser.add_argument("--import", dest="import_path", help="Import a friend's downloaded JSON")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    args = parser.parse_args()
    if args.build:
        sys.exit(_cmd_build(args.run_id))
    if args.import_path:
        sys.exit(_cmd_import(Path(args.import_path), args.run_id))
    parser.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
