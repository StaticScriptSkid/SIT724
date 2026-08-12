#!/usr/bin/env python3
"""
Validate judgement_log/entries.json against judgement_log/schema.json.

Mirrors the pattern of pipeline/validate_cases.py: schema validation plus
a few cross-checks that a bare JSON Schema can't express, then a summary
report so it's obvious at a glance how much reliability-log coverage
exists (which raters, which case+model pairs, accept/reject/refine mix).

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
    print("ERROR: jsonschema not installed. Run: pip install jsonschema --break-system-packages")
    sys.exit(1)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    here = Path(__file__).parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--entries", default=str(here / "entries.json"))
    parser.add_argument("--schema", default=str(here / "schema.json"))
    args = parser.parse_args()

    schema = load_json(args.schema)
    entries = load_json(args.entries)

    if not isinstance(entries, list):
        print("ERROR: entries.json must be a JSON array.")
        sys.exit(1)

    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    seen_ids = set()
    seen_triples = Counter()  # (case_id, model, rater_id) -> count
    judgement_counts = Counter()
    rater_counts = Counter()

    for i, entry in enumerate(entries):
        entry_errors = sorted(validator.iter_errors(entry), key=lambda e: e.path)
        for err in entry_errors:
            errors.append(f"entries[{i}] ({entry.get('entry_id', '?')}): {err.message}")

        eid = entry.get("entry_id")
        if eid in seen_ids:
            errors.append(f"entries[{i}]: duplicate entry_id '{eid}'")
        seen_ids.add(eid)

        if entry.get("judgement") == "refine" and not entry.get("refine_detail"):
            errors.append(f"entries[{i}] ({eid}): judgement='refine' requires refine_detail")

        triple = (entry.get("case_id"), entry.get("model"), entry.get("rater_id"))
        seen_triples[triple] += 1
        judgement_counts[entry.get("judgement")] += 1
        rater_counts[entry.get("rater_id")] += 1

    for triple, count in seen_triples.items():
        if count > 1:
            errors.append(f"duplicate (case_id, model, rater_id) triple {triple}: {count} entries")

    if errors:
        print(f"FAILED: {len(errors)} issue(s) found in {args.entries}\n")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"OK: {len(entries)} judgement log entries valid against schema.")
    if entries:
        print(f"Raters: {dict(rater_counts)}")
        print(f"Judgements: {dict(judgement_counts)}")
        cases = {e.get("case_id") for e in entries}
        models = {e.get("model") for e in entries}
        print(f"Coverage: {len(cases)} case(s), {len(models)} model(s)")
    else:
        print("(entries.json is empty — expected until the live pipeline run + first scoring pass happen)")


if __name__ == "__main__":
    main()
