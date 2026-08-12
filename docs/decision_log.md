# Decision Log

Running record of key methodology/build decisions and why they were made, for the thesis methodology chapter and for defending choices in supervisor meetings.

| Date | Decision | Reason |
|---|---|---|
| 2026-07-21 | Prompt copied verbatim from SIT723 thesis, locked at v1.0.0 | Keep results comparable across trimesters; isolate model/case effects from prompt effects (see prompts/PROMPT_LOCK.md) |
| 2026-07-21 | Rubric copied verbatim from SIT723 thesis (7 dimensions, 1-5 scale) | Same reasoning as prompt lock — comparability |
| 2026-07-21 | Q1-Q10 migrated unchanged from SIT723; new cases start at Q11 | Preserve the original baseline cases exactly so SIT723 scores remain a valid reference point |
| 2026-07-21 | New cases require supervisor review before promotion from 'draft' to 'final' | Prevent unreviewed case wording from silently entering evaluation runs |
| 2026-07-21 | Retry policy: 3 attempts, 5s fixed backoff, failures logged not fatal | Fallback plan for API rate limits / transient downtime (Jack's feedback, 22 Jul) — one failed call should not lose the rest of a batch run |
| 2026-07-21 | Every rendered prompt is SHA-256 hashed and stored per record | Detect prompt drift even if prompt_version wasn't bumped; reproducibility |
| 2026-07-21 | Output run directories are write-once (fail on collision) | Prevent accidentally overwriting a previous run's results |
| 2026-08-12 | Live runs call only models whose API key env var is set; missing keys are skipped (logged in manifest) rather than blocking the whole run | Lets a partial live test proceed (e.g. DeepSeek only) without requiring every provider key up front; a full SIT724 comparison still needs all models |

## Open decisions (pending discussion with Jack)

- Case source for cases 16-40/50: hand-authored vs public dataset (and licence check if public).
- Second scorer: human (via Jack) vs LLM-as-judge, or both for a pilot comparison.
- Target case count: minimum 30, aiming for 40-50 if time allows.
- Reliability statistic: weighted Cohen's kappa per rubric dimension (addresses Jack's 22 Jul feedback).
