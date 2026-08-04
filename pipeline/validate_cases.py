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
    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate the SIT724 benchmark case set.")
    parser.add_argument("--cases", default="cases/cases.json", help="Path to cases.json")
    parser.add_argument("--schema", default="cases/schema.json", help="Path to schema.json")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    schema_path = Path(args.schema)

    if not cases_path.exists():
        print(f"ERROR: cases file not found: {cases_path}", file=sys.stderr)
        sys.exit(1)
    if not schema_path.exists():
        print(f"ERROR: schema file not found: {schema_path}", file=sys.stderr)
        sys.exit(1)

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

    # Duplicate ID check
    for case_id, count in ids_seen.items():
        if count > 1:
            all_errors.append(f"Duplicate case id used {count} times: {case_id}")

    if all_errors:
        print(f"FAILED: {len(all_errors)} error(s) found in {cases_path}\n", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    final_count = sum(1 for c in cases if c.get("status") == "final")
    draft_count = sum(1 for c in cases if c.get("status") == "draft")

    print(f"{len(cases)} cases total: {final_count} final, {draft_count} draft")
    print("Topic coverage (final+draft):")
    topic_counts = Counter(c.get("topic", "untagged") for c in cases)
    for topic in sorted(topic_counts):
        print(f"  {topic:<28}{topic_counts[topic]}")

    print(f"OK: benchmark v{benchmark_version} is valid")


if __name__ == "__main__":
    main()
