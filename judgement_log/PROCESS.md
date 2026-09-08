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

One entry per **(case, model, rater)** combination — i.e. every time a
rater independently scores one AI response to one case, for one model. At
full scale (>=30 cases x TBD model count x 2+ raters) expect
`cases x models x raters` entries.

## Workflow per entry

1. Rater reads the case (`question`, `correct_answer`, `wrong_answer`,
   `misconception`) from `cases/cases.json` — blind to which model produced
   the response, per the blinding tool planned for W7 of the Weekly Plan.
2. Rater reads the AI response for that case+model from the pipeline's run
   output (`ai_response_ref` points at it — never paraphrase the response
   being judged into the log).
3. Rater scores all 7 rubric dimensions per `rubric/rubric.json`'s 1-5
   anchors.
4. Rater writes `reasoning` (free text): what stood out in the response,
   what supports each score, and specifically what — if anything — moves
   the judgement away from the default of "accept."
5. Rater sets `judgement`:
   - **accept** — default. Response is graded on its rubric merits and
     counts as-is toward the reliability analysis.
   - **reject** — response is unusable as evidence for this case (e.g. it
     doesn't address the misconception at all, contains unsafe content, or
     is an error/refusal rather than feedback). `reasoning` must explain
     why. A rejected entry is excluded from that case+model pair's kappa
     calculation, but the rejection itself is still logged and reported —
     a high reject rate is itself a finding, not something to hide.
   - **refine** — the rater's own initial score changed after a second
     look (e.g. re-reading the misconception definition changed how
     "accuracy" was scored). `refine_detail` records the before/after and
     what triggered the change. This exists so the log captures genuine
     second-guessing honestly, instead of silently overwriting a first
     score with no trace.
6. Entry appended to `judgement_log/entries.json`, validated against
   `schema.json` (see `validate_log.py`).

## Relationship to Cohen's kappa

Once two or more raters have independently produced entries for the same
case+model pairs, their `rubric_scores` per dimension are compared to
compute weighted kappa (linear vs. quadratic weights — TBD, decide once
pilot data exists in W7 per the Weekly Plan). Entries marked `reject` by
**either** rater are excluded from that pair's kappa calculation and
reported separately as a reject-rate metric instead, since agreement on a
categorical usability judgement isn't the same statistical object as
agreement on an ordinal 1-5 score.

## Relationship to the peer-review survey

Software engineer peer reviewers (approved by Jack, 5 Aug meeting) act as
an additional `rater_id` in this same log, using the same schema — their
survey responses map onto `rubric_scores` + `reasoning`, so their input
joins the same kappa calculation as a third-plus rater rather than being a
separate, disconnected analysis.

The form they fill is the blinded HTML pack in `peer_review/` (built from
the 150/150 live run, Q1–Q30 × 5 models). It is Google-Forms-like (one item at a time) but
stays local: model names are stripped, item order is shuffled, and the
returned JSON is imported with `python pipeline/peer_review.py --import`.
Do not send the rater `outputs/` or `peer_review/generated/blind_map.json`.

## Status

Schema + process designed 12 Aug 2026 (break week). Entries can only be
created honestly once (a) the live pipeline run has produced real AI
responses to score and (b) a rater does a real scoring pass. Do not
pre-fill `entries.json` with invented judgements.

**First real scoring pass: 8 Sep 2026.** Peer rater `SS` scored all 150
responses of run `20260819T010032Z-477c3a3e` (Q1–Q30 × 5 models) through
the blinded form in `peer_review/`, imported as `JL-0003`–`JL-0152`
(103 accept / 27 reject / 20 refine). Entries `JL-0001`–`JL-0002`
(rater `andrei`, 19 Aug) were Score-tab smoke tests during GUI
development, not a scoring pass — replace or remove them before any
kappa calculation. A second rater's full pass is still needed for kappa.
