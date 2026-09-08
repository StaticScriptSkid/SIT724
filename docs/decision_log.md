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
| 2026-08-12 | Gemini API slug updated from `gemini-1.5-flash` (retired, 404) to `gemini-3.5-flash` | Matches the SIT723 “Gemini 3.5 Flash” label; 1.5 Flash is no longer served on generateContent |
| 2026-08-12 | Gemini calls use `thinkingLevel: minimal` and only visible (non-thought) text parts | Gemini 3.5 thinking was consuming `max_tokens: 400`, so live “ok” records were truncated stubs; minimal thinking keeps the shared token cap comparable across models |
| 2026-08-12 | Reverted Gemini `thinkingLevel` (back to default thinking + `parts[0].text`) to test paid quota vs thinking as the truncation cause | Student added Gemini credit after a free-plan run; keep 3.5-flash slug and header auth |
| 2026-08-12 | Gemini live calls use maxOutputTokens ≥ 2048 and join non-thought text parts (not only parts[0]) | Paid quota did not fix 38–70 char stubs; Gemini was being cut off / returning a thought fragment as `parts[0]`. Other models still use config `max_tokens: 400` |
| 2026-08-19 | Kimi model_id changed from `kimi-k2.6-instant` (404) to `kimi-k2.6`, with per-model `temperature: 1` and `max_tokens: 800` | Live run failed: Moonshot has no `kimi-k2.6-instant`; available list is kimi-k2.6 / kimi-k3 / code variants, and kimi-k2.6 rejects temperature 0.0 |
| 2026-08-19 | Kimi uses `thinking: {type: disabled}` and `temperature: 0.6` | Live run `…7a73233f` had 3/10 Kimi failures: empty `content`, only `reasoning_content`. Disabling thinking fills the visible reply; Moonshot then requires temp 0.6 |
| 2026-08-19 | Kimi live calls use `min_interval_seconds: 22`, longer 429 backoff, and extra rate-limit retries | 30-case run `…a4a73323` lost Q22/Q29 Kimi to Moonshot RPM (~3/min); fixed 5s×3 retries were not enough |
| 2026-08-25 | Peer rater uses a local blinded HTML form on the 50/50 run (`…1df4856b`), not a hosted Google Form | 50 items × 7 scores + reasoning is unusable as one Google Form; PROCESS.md requires model blinding; import maps back into `judgement_log/` via a local `blind_map.json` that is never given to the rater |
| 2026-08-25 | Peer form groups the 5 AI replies per case and does not block Next on incomplete items | Raters mistook repeated student questions for duplicates; Next was a hard gate (7 scores + reasoning) so the form looked broken |
| 2026-09-08 | Peer form redesigned: one student question per page with all 5 blinded replies (A–E) beneath it; `judgement` pre-set to `accept`; Next never blocks; keyboard 1–5 entry; Download + Copy-to-clipboard export | Rater feedback on the one-reply-per-page form ("duplicate questions", "can't go next"). Side-by-side replies let the rater compare the 5 answers to the same misconception directly, which is the comparison the study makes. Accept-default follows PROCESS.md step 5 ("accept — default"); a reply still needs 7 scores + reasoning before import counts it, so a defaulted judgement can never enter the log on its own. Returned JSON shape unchanged, so `--import` and the blind map are untouched |
| 2026-09-08 | First peer scoring pass imported: rater `SS`, 150/150 responses of run `…477c3a3e`, entries `JL-0003`–`JL-0152`; log validates (152 entries) | Blinded form returned JSON keyed by blind ID; `pipeline/peer_review.py --import` unblinded it against the local map, verified every `prompt_hash` against the run output (0 mismatches), and rejected nothing. Descriptive only, one rater: mean /35 by tier easy 33.3, medium 29.9, hard 26.2 — the tier ordering behaves as intended. 27 rejects (13 on `openai-gpt`) to examine with Jack |
| 2026-09-08 | Added required `difficulty` field (`easy`/`medium`/`hard`) to every case; schema extended and validator reports tier counts. Tiers classified case-by-case on error visibility × misconception depth (Qian & Lehman 2017; du Boulay notional machine), per the Difficulty Tiers doc v1.0. Result: 10 easy (Q1–Q10), 12 medium, 8 hard | Jack (19 Aug): don't split 1–10/11–20/21–30 by ID order — ground tiers in an assessment-design framework. Uneven 10/12/8 is the classification's output, not a target. Q1–Q10 question/answer/misconception text untouched (metadata key only); no prompt text or hash affected since `generate.py` renders only the four content fields |

## Open decisions (pending discussion with Jack)

- Case source for cases 16-40/50: hand-authored vs public dataset (and licence check if public).
- Second scorer: human (via Jack) vs LLM-as-judge, or both for a pilot comparison.
- Target case count: minimum 30, aiming for 40-50 if time allows.
- Reliability statistic: weighted Cohen's kappa per rubric dimension (addresses Jack's 22 Jul feedback).
