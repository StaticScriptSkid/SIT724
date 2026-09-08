# judgement_log/

Reliability judgement/reflection log — the second half of the SIT724
reliability metric Jack asked for (5 Aug 2026 meeting), alongside the
weighted Cohen's kappa statistic. See `PROCESS.md` for the full workflow
and reasoning; this file is just the quick orientation.

| File | Purpose |
|---|---|
| `schema.json` | JSON Schema for one log entry: one rater × one blinded item (`blind_id`). No model name. |
| `PROCESS.md` | Why this exists, when an entry gets created, the accept/reject/refine workflow, and how it feeds the kappa calculation and the peer-review survey. |
| `entries.json` | The live log. Currently **300** rows (150 `SS` + 150 `GLM-5.2`) for pack `sit724-150-bycase-20260819T010032Z-477c3a3e-seed724`. Do not invent extra judgements. |
| `example_entry.SCHEMA_DEMO.json` | Format reference only. Deliberately uses out-of-range placeholder values (score `0`, which fails schema validation on purpose) so it can never be mistaken for a real entry or accidentally pass validation if copy-pasted without editing. |
| `validate_log.py` | Validates `entries.json` against `schema.json`, checks for duplicate `(rater_id, blind_id)` pairs, score ranges, refine_detail rules, and (for complete 150-row raters) 30 cases × 5 variants. Run: `python3 validate_log.py`. |

## Entry shape (current)

Each row must have: `rater_id`, `pack_id`, `run_id`, `blind_id`,
`case_id`, `variant_index`, `prompt_hash`, `rubric_scores` (7 dims, 1–5),
`judgement` (`accept` / `reject` / `refine`), `reasoning` (non-empty),
`refine_detail` (non-empty iff `refine`, otherwise `""`), `timestamp`.

Model names live only in `peer_review/generated/blind_map.json`, not here.

## Check the log

1. `pip install jsonschema` if not already installed (same dependency
   `validate_cases.py` uses).
2. Run `python3 judgement_log/validate_log.py` — should print
   `OK: 300 judgement log entries valid against schema.` when the SS +
   GLM-5.2 merge is in place.
