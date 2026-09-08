#!/usr/bin/env python3
"""
validate_cases.py — validate cases/cases.json against cases/schema.json and
print a topic-coverage report.

Usage:
    python pipeline/validate_cases.py
    python pipeline/validate_cases.py --cases cases/cases.json --schema cases/schema.json

Exit code is 0 and prints "OK: benchmark v<version> is valid" when every case
passes; otherwise prints each error and exits 1.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


# Order matters for the coverage report (easy -> hard). Must match the enum in cases/schema.json.
DIFFICULTY_TIERS = ("easy", "medium", "hard")


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_case_manually(case: dict, required_fields: list) -> list:
    """Fallback validator used if the jsonschema package isn't installed."""
    errors = []
    for field in required_fields:
        if field not in case:
            errors.append(f"{case.get('id', '<no id>')}: missing required field '{field}'")
    if "status" in case and case["status"] not in ("final", "draft"):
        errors.append(f"{case.get('id')}: status must be 'final' or 'draft', got {case['status']!r}")
    if "difficulty" in case and case["difficulty"] not in DIFFICULTY_TIERS:
        errors.append(
            f"{case.get('id')}: difficulty must be one of {DIFFICULTY_TIERS}, got {case['difficulty']!r}"
        )
    return errors


def validate_benchmark(cases_path: str | Path, schema_path: str | Path) -> dict:
    """
    Validate the benchmark case set against the schema and compute coverage.

    Returns a dict with keys:
        ok, errors, benchmark_version, n_cases, final_count, draft_count,
        topic_counts, difficulty_counts, cases_path
    Does not print or exit — callers (CLI or GUI) decide how to present results.
    """
    cases_path = Path(cases_path)
    schema_path = Path(schema_path)

    if not cases_path.exists():
        return {
            "ok": False,
            "errors": [f"cases file not found: {cases_path}"],
            "benchmark_version": "unknown",
            "n_cases": 0,
            "final_count": 0,
            "draft_count": 0,
            "topic_counts": {},
            "difficulty_counts": {},
            "cases_path": str(cases_path),
        }
    if not schema_path.exists():
        return {
            "ok": False,
            "errors": [f"schema file not found: {schema_path}"],
            "benchmark_version": "unknown",
            "n_cases": 0,
            "final_count": 0,
            "draft_count": 0,
            "topic_counts": {},
            "difficulty_counts": {},
            "cases_path": str(cases_path),
        }

    data = load_json(cases_path)
    schema = load_json(schema_path)
    cases = data.get("cases", [])
    benchmark_version = data.get("benchmark_version", "unknown")

    all_errors = []
    ids_seen = Counter()

    for case in cases:
        if jsonschema is not None:
            validator = jsonschema.Draft7Validator(schema)
            for err in validator.iter_errors(case):
                all_errors.append(f"{case.get('id', '<no id>')}: {err.message}")
        else:
            all_errors.extend(validate_case_manually(case, schema.get("required", [])))
        ids_seen[case.get("id")] += 1

    for case_id, count in ids_seen.items():
        if count > 1:
            all_errors.append(f"Duplicate case id used {count} times: {case_id}")

    topic_counts = Counter(c.get("topic", "untagged") for c in cases)
    final_count = sum(1 for c in cases if c.get("status") == "final")
    draft_count = sum(1 for c in cases if c.get("status") == "draft")
    # Fixed easy->hard order so the report reads as a tier ladder, not alphabetically.
    raw_difficulty = Counter(c.get("difficulty", "untagged") for c in cases)
    difficulty_counts = {t: raw_difficulty.get(t, 0) for t in DIFFICULTY_TIERS}
    for other, n in raw_difficulty.items():
        if other not in DIFFICULTY_TIERS:
            difficulty_counts[other] = n

    return {
        "ok": len(all_errors) == 0,
        "errors": all_errors,
        "benchmark_version": benchmark_version,
        "n_cases": len(cases),
        "final_count": final_count,
        "draft_count": draft_count,
        "topic_counts": dict(sorted(topic_counts.items())),
        "difficulty_counts": difficulty_counts,
        "cases_path": str(cases_path),
    }


def main():
    parser = argparse.ArgumentParser(description="Validate the SIT724 benchmark case set.")
    parser.add_argument("--cases", default="cases/cases.json", help="Path to cases.json")
    parser.add_argument("--schema", default="cases/schema.json", help="Path to schema.json")
    args = parser.parse_args()

    result = validate_benchmark(args.cases, args.schema)

    if not result["ok"]:
        # Preserve prior CLI messaging for missing-file vs validation errors.
        file_missing = any("not found" in e for e in result["errors"])
        if file_missing:
            for err in result["errors"]:
                print(f"ERROR: {err}", file=sys.stderr)
            sys.exit(1)
        print(
            f"FAILED: {len(result['errors'])} error(s) found in {result['cases_path']}\n",
            file=sys.stderr,
        )
        for err in result["errors"]:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    print(
        f"{result['n_cases']} cases total: "
        f"{result['final_count']} final, {result['draft_count']} draft"
    )
    print("Topic coverage (final+draft):")
    for topic, count in result["topic_counts"].items():
        print(f"  {topic:<28}{count}")
    print("Difficulty tiers (final+draft):")
    for tier, count in result["difficulty_counts"].items():
        print(f"  {tier:<28}{count}")

    print(f"OK: benchmark v{result['benchmark_version']} is valid")


if __name__ == "__main__":
    main()
