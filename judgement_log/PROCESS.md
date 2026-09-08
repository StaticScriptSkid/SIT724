# Reliability Judgement Log — Process

## Why this exists

Jack's feedback (meeting, 5 Aug 2026): the SIT724 reliability metric needs
two parts, not just a statistic:

1. **Statistical** — weighted Cohen's kappa, computed per rubric dimension,
   between two (or more) raters' scores.
2. **Judgement/reflection** — for each prompt, a documented record of what
   was asked, what the AI said, and *why* the rater accepted, rejected, or
   refined that response, not just the resulting number.

This log is part 2. Part 1 (kappa) is computed **from** the `rubric_scores`
field across raters once enough entries exist; this document covers how
entries get created in the first place, and it is itself the artefact Jack
asked to see — a process, not only an output.

## When an entry gets created

One entry per **(rater, blinded item)** pair — i.e. every time a rater
independently scores one AI response. Items are keyed by `blind_id` (and
`case_id` + `variant_index`) from the peer-review pack, not by model name.
The model that wrote the response is stored only in the local
`peer_review/generated/blind_map.json` and is applied later for analysis.
At full scale (30 cases × 5 models × 2+ raters) expect
`cases × models × raters` entries.

## Workflow per entry

1. Rater reads the case (`question`, `correct_answer`, `wrong_answer`,
   `misconception`) from `cases/cases.json` — blind to which model produced
   the response. The HTML pack in `peer_review/` and the Score tab both
   show `blind_id` / "AI reply N of 5", never the model slug.
2. Rater reads the AI response for that blinded item. The log does **not**
   store a model name or `ai_response_ref`; it stores `pack_id`, `run_id`,
   `blind_id`, `case_id`, `variant_index`, and `prompt_hash` so the row can
   be joined to the run later without unblinding the rater.
3. Rater scores all 7 rubric dimensions per `rubric/rubric.json`'s 1-5
   anchors (`accuracy`, `selectivity`, `clarity`, `informativeness`,
   `specificity`, `level_of_detail`, `ethics_safety`).
4. Rater writes `reasoning` (free text, required, non-empty): what stood
   out in the response, what supports each score, and specifically what —
   if anything — moves the judgement away from the default of "accept."
5. Rater sets `judgement`:
   - **accept** — default. Response is graded on its rubric merits and
     counts as-is toward the reliability analysis. `refine_detail` is an
     empty string.
   - **reject** — response is unusable as evidence for this case (e.g. it
     doesn't address the misconception at all, contains unsafe content, or
     is an error/refusal rather than feedback). `reasoning` must explain
     why. `refine_detail` is an empty string. A rejected entry is excluded
     from that item's kappa calculation, but the rejection itself is still
     logged and reported — a high reject rate is itself a finding, not
     something to hide.
   - **refine** — the rater's own initial score changed after a second
     look (e.g. re-reading the misconception definition changed how
     "accuracy" was scored). `refine_detail` is required and non-empty:
     what should change, or what changed between first and final scores.
     This exists so the log captures genuine second-guessing honestly,
     instead of silently overwriting a first score with no trace.
6. Entry appended to `judgement_log/entries.json`, validated against
   `schema.json` (see `validate_log.py`). Required fields: `rater_id`,
   `pack_id`, `run_id`, `blind_id`, `case_id`, `variant_index`,
   `prompt_hash`, `rubric_scores`, `judgement`, `reasoning`,
   `refine_detail`, `timestamp`. Duplicate `(rater_id, blind_id)` pairs
   are rejected.

## Relationship to Cohen's kappa

Once two or more raters have independently produced entries for the same
`blind_id` (same pack), their `rubric_scores` per dimension are compared
to compute weighted kappa (linear vs. quadratic weights — TBD). Entries
marked `reject` by **either** rater are excluded from that pair's kappa
calculation and reported separately as a reject-rate metric instead, since
agreement on a categorical usability judgement isn't the same statistical
object as agreement on an ordinal 1-5 score. Model-level breakdowns need
the local blind map; they are not stored in the log.

## Relationship to the peer-review survey

Software engineer peer reviewers (approved by Jack, 5 Aug meeting) act as
an additional `rater_id` in this same log, using the same schema — their
form responses map onto `rubric_scores` + `reasoning` + `judgement`, so
their input joins the same kappa calculation as a third-plus rater rather
than being a separate, disconnected analysis.

The form they fill is the blinded HTML pack in `peer_review/` (built from
the 150/150 live run, Q1–Q30 × 5 models). It is Google-Forms-like but
stays local: model names are stripped, replies are grouped by case, and
the returned JSON uses the same field list as `schema.json`. The LLM-as-
judge script (`pipeline/llm_judge.py`) writes that same shape
(`rater_id: GLM-5.2`). Do not send the rater `outputs/` or
`peer_review/generated/blind_map.json`.

## Status

Schema + process designed 12 Aug 2026 (break week); schema switched to
the blinded pack shape on 9 Sep 2026 (no `model` / `entry_id` /
`ai_response_ref` on log rows).

**Current log:** 300 entries for run `20260819T010032Z-477c3a3e`, pack
`sit724-150-bycase-20260819T010032Z-477c3a3e-seed724` — 150 from peer
rater `SS` and 150 from `GLM-5.2`. Rows join on `blind_id`. An unblinded
copy of the earlier SS import (with `model` names) is kept only as
`entries_RECOVERED_unblinded.json` for recovery, not as the live log.
