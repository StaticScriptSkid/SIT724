# judgement_log/

Reliability judgement/reflection log — the second half of the SIT724
reliability metric Jack asked for (5 Aug 2026 meeting), alongside the
weighted Cohen's kappa statistic. See `PROCESS.md` for the full workflow
and reasoning; this file is just the quick orientation.

| File | Purpose |
|---|---|
| `schema.json` | JSON Schema for one log entry (one case + model + rater judgement). |
| `PROCESS.md` | Why this exists, when an entry gets created, the accept/reject/refine workflow, and how it feeds the kappa calculation and the peer-review survey. |
| `entries.json` | The actual log. **Currently `[]`** — stays empty until the live pipeline run exists and a real scoring pass happens. Do not pre-fill. |
| `example_entry.SCHEMA_DEMO.json` | Format reference only. Deliberately uses out-of-range placeholder values (score `0`, which fails schema validation on purpose) so it can never be mistaken for a real entry or accidentally pass validation if copy-pasted without editing. |
| `validate_log.py` | Validates `entries.json` against `schema.json`, checks for duplicate entries, and prints a coverage summary (raters / cases / models / accept-reject-refine mix). Run: `python3 validate_log.py`. |

## Drop-in instructions

Copy this whole `judgement_log/` folder into the repo root (alongside
`cases/`, `rubric/`, `pipeline/`), then:

1. Add a line to `PROJECT_CONTEXT.md`'s repo-structure section pointing at
   `judgement_log/` and `PROCESS.md`, so Cursor knows this exists and
   what it's for.
2. `pip install jsonschema` if not already installed (same dependency
   `validate_cases.py` uses).
3. Run `python3 judgement_log/validate_log.py` to confirm it's wired up —
   should print `OK: 0 judgement log entries valid against schema.`
4. Leave `entries.json` empty until the live pipeline run happens and a
   real scoring pass is done. This log is infrastructure right now, not
   data — see the Status section of `PROCESS.md`.
