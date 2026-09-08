#!/usr/bin/env python3
"""
Validate judgement_log/entries.json against judgement_log/schema.json.

Mirrors the pattern of pipeline/validate_cases.py: schema validation plus
cross-checks a bare JSON Schema can't express, then a coverage summary.

Usage:
    python3 validate_log.py
    python3 validate_log.py --entries path/to/entries.json
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import jsonschema
except ImportError:
    jsonschema = None

RUBRIC_DIMS = (
    "accuracy",
    "selectivity",
    "clarity",
    "informativeness",
    "specificity",
    "level_of_detail",
    "ethics_safety",
)
EXPECTED_CASES = tuple(f"Q{i}" for i in range(1, 31))
VARIANTS_PER_CASE = 5


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _empty_result(errors, entries_path):
    return {
        "ok": False,
        "errors": errors,
        "n_entries": 0,
        "rater_counts": {},
        "judgement_counts": {},
        "n_cases": 0,
        "n_models": 0,
        "entries_path": str(entries_path),
    }


def validate_entries(entries_path, schema_path) -> dict:
    """
    Validate judgement log entries. Returns a result dict (does not exit).

    Keys: ok, errors, n_entries, rater_counts, judgement_counts,
          n_cases, n_models, entries_path
    """
    entries_path = Path(entries_path)
    schema_path = Path(schema_path)

    if jsonschema is None:
        return _empty_result(
            ["jsonschema not installed. Run: pip install jsonschema"],
            entries_path,
        )
    if not entries_path.exists():
        return _empty_result([f"entries file not found: {entries_path}"], entries_path)
    if not schema_path.exists():
        return _empty_result([f"schema file not found: {schema_path}"], schema_path)

    schema = load_json(schema_path)
    entries = load_json(entries_path)

    if not isinstance(entries, list):
        return _empty_result(["entries.json must be a JSON array."], entries_path)

    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    seen_pairs = Counter()
    judgement_counts = Counter()
    rater_counts = Counter()
    # rater_id -> case_id -> count
    case_per_rater = defaultdict(Counter)

    for i, entry in enumerate(entries):
        label = f"{entry.get('rater_id', '?')}/{entry.get('blind_id', '?')}"
        entry_errors = sorted(validator.iter_errors(entry), key=lambda e: e.path)
        for err in entry_errors:
            errors.append(f"entries[{i}] ({label}): {err.message}")

        pair = (entry.get("rater_id"), entry.get("blind_id"))
        seen_pairs[pair] += 1
        judgement_counts[entry.get("judgement")] += 1
        rater_counts[entry.get("rater_id")] += 1
        if entry.get("case_id"):
            case_per_rater[entry.get("rater_id")][entry.get("case_id")] += 1

        scores = entry.get("rubric_scores") or {}
        for dim in RUBRIC_DIMS:
            val = scores.get(dim)
            if not isinstance(val, int) or isinstance(val, bool) or val < 1 or val > 5:
                errors.append(
                    f"entries[{i}] ({label}): {dim} must be an integer 1-5, got {val!r}"
                )

        judgement = entry.get("judgement")
        refine = entry.get("refine_detail")
        refine_present = isinstance(refine, str) and refine.strip() != ""
        if judgement == "refine" and not refine_present:
            errors.append(
                f"entries[{i}] ({label}): judgement='refine' requires a non-empty refine_detail"
            )
        if judgement != "refine" and refine_present:
            errors.append(
                f"entries[{i}] ({label}): refine_detail must be empty unless judgement='refine'"
            )

    for pair, count in seen_pairs.items():
        if count > 1:
            errors.append(f"duplicate (rater_id, blind_id) pair {pair}: {count} entries")

    # Full-pack coverage (30 cases × 5 variants) only for raters who already
    # have a complete 150-row pass. Incremental Score-tab saves stay valid.
    if entries:
        expected_n = len(EXPECTED_CASES) * VARIANTS_PER_CASE
        for rater, counts in case_per_rater.items():
            if sum(counts.values()) < expected_n:
                continue
            missing = [c for c in EXPECTED_CASES if counts.get(c, 0) == 0]
            wrong = [
                f"{c}×{counts[c]}"
                for c in EXPECTED_CASES
                if counts.get(c, 0) not in (0, VARIANTS_PER_CASE)
            ]
            extra = sorted(c for c in counts if c not in EXPECTED_CASES)
            if missing:
                errors.append(
                    f"rater {rater!r}: missing case_id(s) {missing} "
                    f"(need all 30 cases, {VARIANTS_PER_CASE} each)"
                )
            if wrong:
                errors.append(
                    f"rater {rater!r}: case_id counts must be {VARIANTS_PER_CASE} each, got {wrong}"
                )
            if extra:
                errors.append(f"rater {rater!r}: unexpected case_id(s) {extra}")

    cases = {e.get("case_id") for e in entries if e.get("case_id")}

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "n_entries": len(entries),
        "rater_counts": dict(rater_counts),
        "judgement_counts": dict(judgement_counts),
        "n_cases": len(cases),
        "n_models": 0,
        "entries_path": str(entries_path),
    }


def main():
    here = Path(__file__).parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--entries", default=str(here / "entries.json"))
    parser.add_argument("--schema", default=str(here / "schema.json"))
    args = parser.parse_args()

    if jsonschema is None:
        print(
            "ERROR: jsonschema not installed. Run: pip install jsonschema --break-system-packages",
            file=sys.stderr,
        )
        sys.exit(1)

    result = validate_entries(args.entries, args.schema)
    if not result["ok"]:
        print(f"FAILED: {len(result['errors'])} issue(s) found in {result['entries_path']}\n")
        for e in result["errors"]:
            print(f"  - {e}")
        sys.exit(1)

    print(f"OK: {result['n_entries']} judgement log entries valid against schema.")
    if result["n_entries"]:
        print(f"Raters: {result['rater_counts']}")
        print(f"Judgements: {result['judgement_counts']}")
        print(f"Coverage: {result['n_cases']} case(s), blinded (no model names)")
    else:
        print(
            "(entries.json is empty — expected until the live pipeline run "
            "+ first scoring pass happen)"
        )


if __name__ == "__main__":
    main()
