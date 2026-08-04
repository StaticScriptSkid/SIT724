# feedback-eval-pipeline

SIT724 automated feedback-evaluation pipeline — extends the SIT723 manual study (10 cases, chat-interface prompting, single scorer) into an automated, API-driven, reproducible pipeline with an expanded case set and a path to blinded multi-reviewer scoring.

Project: *Evaluating the Accuracy and Educational Quality of AI-Generated Feedback for Beginner Programming Mistakes*
Student: Andrei Angeles (s222225013) — Supervisor: Jack Li

## Structure

```
cases/schema.json      JSON schema every case must satisfy
cases/cases.json       Benchmark cases — Q1-Q10 final (verbatim from SIT723), Q11+ draft (Sprint 1 expansion)
cases/baseline.json    Non-AI baseline responses (PLACEHOLDER — see file header, needs verbatim SIT723 text)
rubric/rubric.json     7-dimension scoring rubric, verbatim from SIT723 thesis
prompts/template.txt   Locked prompt template
prompts/PROMPT_LOCK.md Policy for why/how the prompt is locked
config.yaml             Models, generation params, pricing (unfilled)
pipeline/validate_cases.py   Validates cases.json against schema.json, reports topic coverage
pipeline/generate.py         Renders prompts, calls each model, logs results (or --dry-run)
docs/decision_log.md   Running log of methodology decisions and open questions
outputs/<run_id>/      One folder per run: manifest.json + responses.jsonl (write-once)
```

## Quick start

```bash
pip install -r requirements.txt

# 1. Validate the benchmark
python pipeline/validate_cases.py

# 2. Prove the pipeline works with zero API calls / zero cost
python pipeline/generate.py --dry-run

# 3. (once API keys are set as env vars per config.yaml) estimate cost
python pipeline/generate.py --estimate

# 4. Real run
python pipeline/generate.py
```

## Status (as of this build)

- Benchmark v1.1.0-dev: 10 final cases (SIT723, unchanged) + 5 draft cases (Q11-Q15: dictionaries, while-loops, mutability/aliasing, scope, string immutability) awaiting supervisor review.
- Pipeline dry-run verified: 50/50 case x model combinations (10 final cases x 5 models), zero failures.
- No live API calls made yet — needs API keys and a confirmed model list/budget.
- `cases/baseline.json` is a placeholder and must be replaced with the verbatim SIT723 baseline text before any real scoring run (see file header and docs/decision_log.md).

See docs/decision_log.md for methodology decisions and open questions to raise with the supervisor.
