# Prompt Lock Policy

**Current prompt_version: 1.0.0**
**Locked: 21 July 2026**

## Why the prompt is locked

The prompt in `prompts/template.txt` is copied verbatim from the SIT723 thesis (Appendix A: AI Testing Prompt). It is locked so that any score differences observed in SIT724 are attributable to the model, the case set, or the scoring process — not to a changed prompt. This is the same principle Section 3.4 of the SIT723 thesis relies on ("the same prompt structure was used across all cases and models so that differences in the output were more likely to come from the model response rather than from different instructions").

## Rules

1. Do not edit `prompts/template.txt` without bumping `prompt_version` in `config.yaml`.
2. Any prompt change requires re-running **all** cases for **all** models under the new version — partial re-runs mixing prompt versions are not valid for comparison.
3. Every generated response record stores `prompt_version` and a `prompt_sha256` hash of the fully rendered prompt (case values substituted in), so any accidental drift is detectable after the fact even if `prompt_version` was not bumped.
4. Record the reason for any change in `docs/decision_log.md` before touching the template.

## Version history

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-07-21 | Initial lock — verbatim SIT723 prompt, no changes. |
