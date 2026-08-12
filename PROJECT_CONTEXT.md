# SIT724 Project Context

**Read this before making any change to this repo.** This file exists so an AI coding assistant (or a new collaborator) understands what this project is, why it's structured the way it is, and which parts are load-bearing for an active university research assessment — not just a normal software repo.

---

## 1. Who this is for

- **Student:** Andrei Landayan Angeles (student ID s222225013), Bachelor/Software Engineering (Honours), Deakin University, online-only.
- **Unit:** SIT724 — Research Project, Trimester 2 2026 (teaching runs 6 Jul–25 Sep 2026, mid-trimester break 10–14 Aug, study week 28 Sep–2 Oct).
- **Supervisor:** Jack Li. Weekly meeting: Wednesdays 3:00pm AEST via Microsoft Teams.
- **Continuing from:** SIT723 — Research Techniques and Applications (T1 2026), completed with a Pass self-assessment.
- **Target grade:** Pass (stated in the SIT724 supervisor agreement).

This repo (`feedback-eval-pipeline`, hosted at `github.com/StaticScriptSkid/SIT724`) is the **artifact** for SIT724 — i.e. it is itself a piece of assessed evidence, not just internal tooling. Every file in it may end up referenced or shown in the final thesis (5.1P) and the artifact submission (4.1C).

---

## 2. What the research project is actually about

**Project title:** *Evaluating the Accuracy and Educational Quality of AI-Generated Feedback for Beginner Programming Mistakes*

**Main research question:** How does AI-generated feedback for common beginner programming mistakes compare with baseline standard non-AI feedback in terms of accuracy and educational quality?

**Sub-questions:**
1. How accurately does AI-generated feedback identify and address common beginner programming mistakes compared with baseline non-AI feedback?
2. How does AI-generated feedback compare with baseline non-AI feedback in terms of educational quality dimensions (specificity, actionability, pedagogical value, ethics and safety, learning goal alignment)?

**Scope boundary (deliberate, do not expand):** This project judges feedback *text quality*, not student learning outcomes. It does not test real students. It does not claim AI feedback improves grades. It is a controlled benchmark-and-rubric comparison.

---

## 3. What was already completed in SIT723 (do not redo this — extend it)

SIT723 (T1 2026) produced a finished thesis with:

- **10 beginner Python mistake cases** (Q1–Q10), each with: a question/code snippet, the correct answer, a common wrong answer, and a labelled misconception. Topics: variables, assignment-vs-comparison, if-statements, loops, lists, strings, boolean-logic, functions, integer-division, syntax-errors.
- **7-dimension scoring rubric** (1–5 scale each, 35 max per response): Accuracy, Selectivity, Clarity, Informativeness, Specificity, Level of Detail, Ethics & Safety.
- **6 AI models** compared against **1 fixed non-AI baseline**: DeepSeek, Gemini 3.5 Flash, ChatGPT 5.5, Claude Sonnet 4.6 (adaptive), Kimi K2.6 Instant, Manus 1.6 Lite.
- **Locked prompt template** (verbatim, see `prompts/template.txt`) used identically across every case/model combination, submitted manually through each model's chat interface (this manual step is exactly what SIT724's pipeline automates).
- **Results:** all 6 AI models scored above baseline (31.5/35). Final ranking after an independent scoring audit: DeepSeek 34.8, Gemini 33.8, ChatGPT 33.6, Claude 33.5, Kimi 33.2, Manus 32.1.
- **Known errors found in that data** (worth knowing — future cases/prompts should watch for the same failure modes): Manus called floor division (`//`) the "dot operator" in Q9 — a factual wording error. ChatGPT and Claude both partly validated the student's wrong idea about a missing quote in Q10, when the real issue was a missing closing parenthesis.
- **Stated limitations that SIT724 exists to fix** (see Section 4 — this is the core logic of the whole project): only 10 cases; single scorer with only an informal second-pass audit, no formal inter-rater statistic; no blinded scoring; no statistical significance testing; no real student answers (out of scope, stays out of scope).

Full detail (methodology, exact prompt text, full rubric anchors, all 60 model responses, references) lives in the project's stored copy of the SIT723 thesis if it's needed — do not regenerate this from scratch, it already exists and is finished.

---

## 4. What SIT724 must deliver — the core argument

**Every SIT723 limitation becomes a specific SIT724 deliverable, one-to-one:**

| SIT723 limitation | SIT724 fix | Sprint |
|---|---|---|
| Only 10 cases | Expand to 30–50 cases (never drop below 30) | Sprint 1 |
| Manual chat-interface prompting | Automated API pipeline (this repo) | Sprint 1 |
| Single scorer, informal audit | Blinded scoring + a second reviewer (human and/or LLM-as-judge) | Sprint 2 |
| No inter-rater reliability statistic | Weighted Cohen's kappa per rubric dimension | Sprint 2 |
| No significance testing | Wilcoxon (AI vs baseline) + Friedman with post-hoc (across models) + effect sizes | Sprint 3 |
| No real API rate-limit/downtime handling | Retry logic (3 attempts, 5s backoff) + documented fallback | Sprint 1 (done — see `pipeline/generate.py`) |

**Sprint breakdown (12-week unit):**

- **Sprint 1 — Build (weeks 3–6):** pipeline that calls each model's API directly (replacing manual chat-interface copy/paste), case set expanded from 10 to 30–50, prompt and rubric locked and versioned so results stay comparable to SIT723.
- **Sprint 2 — Validity (weeks 7–9):** blinding tool so scorers don't know which model produced a response, a second scorer (human via Jack and/or an LLM-as-judge, TBD), pilot inter-rater agreement, then full blinded scoring with weighted Cohen's kappa per dimension.
- **Sprint 3 — Analysis (weeks 10–12):** full statistical run (Wilcoxon, Friedman, effect sizes), finished thesis, artifact submission, defense prep if grade trajectory reaches D/HD (not the current target — target is Pass).

**Assessment logic to keep in mind:** the SIT724 grading panel (supervisor + 2–3 external moderators) grades from *evidence*, not task completion — every week needs a verifiable, specific output (numbers, named files, thesis section pointers), not a vague status update. This is why this repo has a `docs/decision_log.md` and versioned outputs instead of just "it works, trust me."

---

## 5. Current status (as of this file's creation — check `docs/decision_log.md` for the latest)

- **1.1P (Renewed Supervision Agreement)** — submitted, confirms continuation from SIT723, target grade Pass, weekly Wednesday 3pm Teams meeting.
- **3.1P (Research Progress Checkpoint 1)** — submitted, covering weeks 1–3 (honest "did nothing" week 1 after a late start, catch-up in week 2, setup work closed in week 3: repo, benchmark migration, pipeline dry-run, thesis skeleton).
- **Supervisor feedback received on 3.1P** (from Jack) — praised the continuity from SIT723 and the 3-sprint structure. Flagged three gaps, all now addressed in this repo's design:
  1. *"Add a fallback plan for API rate limits/downtime"* → `pipeline/generate.py` retries each call up to 3 times with a 5-second backoff before logging a failure instead of crashing the run; documented in `docs/decision_log.md`.
  2. *"Specify the benchmark expansion — nominate a target number and selection criterion"* → target is **30 minimum, 40–50 stretch**, selection criterion is **common beginner misconception categories** (one case per topic, e.g. the 15 topics currently tagged, expanding to cover more categories rather than duplicating existing ones).
  3. *"Define your reliability metric"* → **weighted Cohen's kappa**, calculated per rubric dimension (chosen over plain kappa because the rubric is 1–5 ordinal, not categorical — a 1-point disagreement should count less than a 4-point disagreement).
- **Benchmark:** `benchmark_version: 1.1.0-dev` in `cases/cases.json` — 10 final cases (Q1–Q10, unchanged from SIT723) + 5 draft cases (Q11–Q15: dictionaries/KeyError, while-loop non-termination, mutability/aliasing, scope, string immutability). Draft cases are **not yet reviewed by Jack** — do not promote them to `"status": "final"` without that sign-off.
- **Pipeline:** `pipeline/validate_cases.py` and `pipeline/generate.py` are both built and verified working (dry-run mode: 50/50 case×model combinations succeed with zero errors, zero API cost). No live API calls have been made yet — that needs API keys and a confirmed model/budget decision with Jack first.
- **`cases/baseline.json` is a known placeholder** — the exact verbatim SIT723 baseline responses for Q1–Q10 still need to be re-imported before any real scoring run. Do not treat the current text in that file as final data.
- **GUI:** a Streamlit-based web GUI is being added on top of this pipeline (via Cursor) as a demo/artifact layer — benchmark browser, rubric viewer, run trigger, past-run browser, config viewer. It should call into the existing `pipeline/generate.py` and `pipeline/validate_cases.py` functions rather than duplicating their logic, so the CLI and GUI never drift apart.

---

## 6. Repo structure and what's load-bearing

```
cases/schema.json      JSON schema every case must satisfy — LOCKED structure, extend carefully
cases/cases.json       Benchmark cases — Q1-Q10 are LOCKED (verbatim from SIT723), do not edit their text
cases/baseline.json    Non-AI baseline responses — currently a PLACEHOLDER, see file header
rubric/rubric.json     7-dimension scoring rubric — LOCKED verbatim from SIT723 thesis
prompts/template.txt   The locked prompt template — LOCKED, see PROMPT_LOCK.md before touching
prompts/PROMPT_LOCK.md Policy explaining why the prompt must not change without a version bump
config.yaml             Models, generation params, pricing — safe to edit as decisions get confirmed
pipeline/validate_cases.py   Validates cases.json against schema.json, reports topic coverage
pipeline/generate.py         Renders prompts, calls each model's API, logs results (supports --dry-run)
docs/decision_log.md   Running log of methodology decisions and open questions — UPDATE this whenever
                        a real decision is made, it feeds directly into the thesis methodology chapter
outputs/<run_id>/      One folder per pipeline run — write-once, never edit or delete past runs;
                        they are evidence of what the pipeline actually produced and when
judgement_log/         Reliability judgement/reflection log (Jack): per-response accept/reject/refine
                        + reasoning, alongside weighted Cohen's kappa. See judgement_log/PROCESS.md
```

### Things that must NOT change without explicit supervisor-facing justification:

1. **`prompts/template.txt`** — locked at `prompt_version: 1.0.0`. Any edit requires bumping the version in `config.yaml` and re-running every case/model combination under the new version (see `prompts/PROMPT_LOCK.md`). Comparability with SIT723 depends on this staying identical.
2. **`rubric/rubric.json`** — locked, copied verbatim from the SIT723 thesis, for the same comparability reason.
3. **Cases Q1–Q10 in `cases/cases.json`** — these are the original SIT723 cases. Their question/answer/misconception text must stay unchanged; only new cases get added, starting at Q11+.
4. **Case `status` field** — a case is `"draft"` until Jack has reviewed it; only then does it become `"final"` and enter real evaluation runs. Do not silently flip this.

### Things that are safe and expected to evolve:

- `config.yaml` (model list, pricing, generation params) — update as budget/model decisions are confirmed with Jack.
- `docs/decision_log.md` — append to this constantly; it's meant to grow.
- New cases (Q11 onward) — draft freely, but leave `status: "draft"` until reviewed.
- The GUI layer (`app.py` and friends) — this is new tooling on top of a stable core, iterate on it freely.
- `outputs/` — grows with every run; never delete old runs, they're audit trail.

---

## 7. Design decisions already made (and why — for the methodology chapter and for defending choices to Jack)

- **Retry policy:** 3 attempts, fixed 5-second backoff, failures logged per-record rather than crashing the whole run. This is the direct answer to Jack's fallback-plan feedback.
- **Every rendered prompt is SHA-256 hashed** and stored per output record, so prompt drift is detectable even if someone forgets to bump `prompt_version`.
- **Output run directories are write-once** (the pipeline errors out rather than overwriting an existing run folder) — this preserves a clean audit trail across the trimester.
- **Case selection criterion for expansion:** one case per distinct beginner misconception category, not multiple cases probing the same misconception — this is the answer to Jack's "specify the benchmark expansion" feedback.
- **Reliability statistic:** weighted Cohen's kappa, computed per rubric dimension (not one pooled score across all 7 dimensions) — because different dimensions may have different agreement levels, and pooling would hide that.

## 8. Open decisions — still pending, do not assume an answer

- **Case source for cases 16–50:** hand-authored (like Q1–Q15) vs sourced from a public beginner-mistake dataset (would need a licence check).
- **Second scorer for blinded scoring:** human reviewer (via Jack) vs LLM-as-judge vs both, piloted and compared.
- **Final model list and API budget** — `config.yaml` currently lists the same 5 of the 6 SIT723 models mapped to API slugs (Manus is not currently wired in — a provider/API decision, follow the "no API for a 723 model → substitute + document" fallback rule from the weekly plan if it can't be added).
- **4.3D midterm presentation** format/date — not yet confirmed.

## 9. Rules for AI-assisted coding on this repo

This project's supervisor agreement explicitly discloses AI-assisted development. The condition attached to that disclosure: **the student must be able to explain and defend every line of committed code.** Practically, that means:

- Don't introduce dependencies, patterns, or abstractions that can't be explained simply in a supervisor meeting.
- Don't change locked artifacts (Section 6) as a side effect of an unrelated feature — flag it instead of silently "fixing" it.
- Prefer small, explainable diffs over large rewrites.
- When adding the GUI or any new tooling, reuse the existing `pipeline/` functions rather than reimplementing pipeline logic in a second place — divergence between CLI and GUI behaviour would undermine the "reproducible pipeline" claim the whole artifact is built on.
- Any new dependency should be added to `requirements.txt`, not installed ad hoc.
