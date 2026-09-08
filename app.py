#!/usr/bin/env python3
"""
app.py — lightweight local Streamlit GUI for the SIT724 feedback-evaluation pipeline.

Thin UI layer over pipeline/validate_cases.py and pipeline/generate.py so the GUI
and CLI share the same validation and generation code paths.

Launch:
    streamlit run app.py
"""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from datetime import datetime, timezone

import streamlit as st
import yaml

from judgement_log.validate_log import validate_entries
from pipeline.generate import (
    MissingAPIKeysError,
    api_key_status,
    load_config,
    load_dotenv,
    missing_api_key_envs,
    run_pipeline,
)
from pipeline.peer_review import (
    DEFAULT_RUN_ID as PEER_RUN_ID,
    build_pack,
    import_peer_file,
    pack_leak_warnings,
    write_generated_pack,
)
from pipeline.validate_cases import load_json, validate_benchmark

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
CASES_PATH = ROOT / "cases" / "cases.json"
SCHEMA_PATH = ROOT / "cases" / "schema.json"
RUBRIC_PATH = ROOT / "rubric" / "rubric.json"
CONFIG_PATH = ROOT / "config.yaml"
OUTPUTS_DIR = ROOT / "outputs"
JUDGEMENT_ENTRIES = ROOT / "judgement_log" / "entries.json"
JUDGEMENT_SCHEMA = ROOT / "judgement_log" / "schema.json"

DF_WIDTH = "stretch"

RUBRIC_DIM_KEYS = [
    "accuracy",
    "selectivity",
    "clarity",
    "informativeness",
    "specificity",
    "level_of_detail",
    "ethics_safety",
]


def _load_cases_table() -> tuple[list[dict], str]:
    data = load_json(CASES_PATH)
    return data.get("cases", []), data.get("benchmark_version", "unknown")


def _list_run_dirs() -> list[Path]:
    if not OUTPUTS_DIR.exists():
        return []
    dirs = [p for p in OUTPUTS_DIR.iterdir() if p.is_dir() and (p / "manifest.json").exists()]
    return sorted(dirs, key=lambda p: p.name, reverse=True)


def _load_responses(run_dir: Path) -> list[dict]:
    path = run_dir / "responses.jsonl"
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _safe_config_display(cfg: dict) -> dict:
    """Return a config copy safe for display — API key values never shown, only env var names."""
    display = {
        "prompt_version": cfg.get("prompt_version"),
        "benchmark_version": cfg.get("benchmark_version"),
        "generation_params": cfg.get("generation_params"),
        "models": [],
        "pricing_usd_per_1k_tokens": cfg.get("pricing_usd_per_1k_tokens"),
        "paths": cfg.get("paths"),
    }
    for m in cfg.get("models", []):
        entry = {
            "name": m.get("name"),
            "provider": m.get("provider"),
            "model_id": m.get("model_id"),
            "api_key_env": m.get("api_key_env"),
        }
        if "api_base_env" in m:
            entry["api_base_env"] = m["api_base_env"]
        display["models"].append(entry)
    return display


def _init_run_state() -> None:
    if "pipeline_job" not in st.session_state:
        st.session_state.pipeline_job = None


def _start_pipeline_job(*, dry_run: bool, include_drafts: bool) -> None:
    """Launch run_pipeline on a background thread so the UI can cancel / refresh."""
    progress_q: queue.Queue = queue.Queue()
    cancel_event = threading.Event()
    result_box: dict = {}

    def on_progress(msg: str) -> None:
        progress_q.put(("log", msg))

    def worker() -> None:
        try:
            summary = run_pipeline(
                config_path=str(CONFIG_PATH),
                dry_run=dry_run,
                include_drafts=include_drafts,
                output_dir=str(OUTPUTS_DIR),
                on_progress=on_progress,
                should_cancel=cancel_event.is_set,
            )
            result_box["summary"] = summary
        except MissingAPIKeysError as e:
            result_box["error"] = str(e)
            result_box["missing_keys"] = e.missing
        except Exception as e:  # noqa: BLE001
            result_box["error"] = str(e)
        finally:
            progress_q.put(("done", None))

    thread = threading.Thread(target=worker, daemon=True)
    st.session_state.pipeline_job = {
        "thread": thread,
        "queue": progress_q,
        "cancel_event": cancel_event,
        "result": result_box,
        "lines": [],
        "done": 0,
        "total": 1,
        "finished": False,
        "dry_run": dry_run,
        "include_drafts": include_drafts,
    }
    thread.start()


def _drain_job_queue(job: dict) -> None:
    q: queue.Queue = job["queue"]
    while True:
        try:
            kind, payload = q.get_nowait()
        except queue.Empty:
            break
        if kind == "log":
            job["lines"].append(payload)
            msg = payload
            if msg.startswith("[") and "/" in msg.split("]", 1)[0]:
                try:
                    part = msg.split("]", 1)[0].lstrip("[")
                    done_s, total_s = part.split("/", 1)
                    job["done"] = int(done_s)
                    job["total"] = max(int(total_s), 1)
                except ValueError:
                    pass
        elif kind == "done":
            job["finished"] = True


def _render_job_summary(summary: dict) -> None:
    if summary.get("cancelled"):
        st.warning(f"Run `{summary['run_id']}` cancelled")
    else:
        st.success(f"Run `{summary['run_id']}` finished")
    st.write(
        f"**Records written:** {summary['n_records']}  ·  "
        f"**Succeeded:** {summary['n_succeeded']}  ·  "
        f"**Failed:** {summary['n_failed']}"
    )
    if summary["dry_run"]:
        st.info("Dry run — no API calls were made, no cost incurred.")
    skipped = summary.get("models_skipped_missing_key") or []
    if skipped:
        st.caption(f"Skipped (no API key): {', '.join(skipped)}")
    st.session_state["selected_run"] = Path(summary["run_dir"]).name
    st.write("**Output folder** (open the Past Runs tab to inspect this run):")
    st.code(summary["run_dir"], language=None)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def view_benchmark() -> None:
    st.subheader("Benchmark")
    cases, version = _load_cases_table()
    st.caption(f"Loaded from `cases/cases.json` · benchmark v{version} · {len(cases)} cases")

    statuses = sorted({c.get("status", "") for c in cases if c.get("status")})
    topics = sorted({c.get("topic", "") for c in cases if c.get("topic")})

    col1, col2 = st.columns(2)
    with col1:
        status_filter = st.multiselect("Filter by status", options=statuses, default=statuses)
    with col2:
        topic_filter = st.multiselect("Filter by topic", options=topics, default=topics)

    filtered = [
        c for c in cases
        if c.get("status") in status_filter and c.get("topic") in topic_filter
    ]

    columns = ["id", "topic", "status", "difficulty", "question", "correct_answer", "wrong_answer", "misconception"]
    table = [{k: c.get(k, "") for k in columns} for c in filtered]
    st.dataframe(table, width=DF_WIDTH, hide_index=True)
    st.caption(f"Showing {len(filtered)} of {len(cases)} cases")

    st.divider()
    if st.button("Validate", type="primary"):
        result = validate_benchmark(CASES_PATH, SCHEMA_PATH)
        if result["ok"]:
            st.success(f"OK: benchmark v{result['benchmark_version']} is valid")
        else:
            st.error(f"FAILED: {len(result['errors'])} error(s)")
            for err in result["errors"]:
                st.write(f"- {err}")

        st.write(
            f"**{result['n_cases']} cases total:** "
            f"{result['final_count']} final, {result['draft_count']} draft"
        )
        st.write("**Topic coverage (final+draft):**")
        coverage_rows = [
            {"topic": topic, "count": count}
            for topic, count in result["topic_counts"].items()
        ]
        st.dataframe(coverage_rows, width=DF_WIDTH, hide_index=True)
        st.write(
            "**Difficulty tiers (final+draft):** "
            + " · ".join(f"{t} {n}" for t, n in result.get("difficulty_counts", {}).items())
        )


def view_rubric() -> None:
    st.subheader("Rubric")
    data = load_json(RUBRIC_PATH)
    st.caption(
        f"rubric v{data.get('rubric_version', '?')} · {data.get('scale', '')}"
    )
    if data.get("source"):
        st.write(data["source"])

    rows = []
    for dim in data.get("dimensions", []):
        anchors = dim.get("anchors", {})
        rows.append({
            "Dimension": dim.get("name", dim.get("key", "")),
            "Definition": dim.get("definition", ""),
            "1": anchors.get("1", ""),
            "2": anchors.get("2", ""),
            "3": anchors.get("3", ""),
            "4": anchors.get("4", ""),
            "5": anchors.get("5", ""),
        })
    st.dataframe(rows, width=DF_WIDTH, hide_index=True)


def view_run_pipeline() -> None:
    st.subheader("Run Pipeline")
    st.caption(
        "Calls the same `run_pipeline` path as `python pipeline/generate.py` "
        "(dry-run / live, optional drafts)."
    )
    _init_run_state()
    job = st.session_state.pipeline_job
    running = bool(job and job["thread"].is_alive() and not job["finished"])

    cfg = load_config(str(CONFIG_PATH))
    key_rows = api_key_status(cfg["models"])
    missing = missing_api_key_envs(cfg["models"])

    with st.expander(
        f"API keys for live mode — "
        + ("all set" if not missing else f"{len(missing)} missing"),
        expanded=False,
    ):
        st.dataframe(
            [
                {
                    "model": r["name"],
                    "env_var": r["api_key_env"],
                    "status": "set" if r["present"] else "MISSING",
                }
                for r in key_rows
            ],
            width=DF_WIDTH,
            hide_index=True,
        )
        if missing:
            ready_names = [r["name"] for r in key_rows if r["present"]]
            st.caption(
                "Live mode calls only models with a key set"
                + (f" (will run: {', '.join(ready_names)})." if ready_names else ".")
                + " Put keys in `.env` (copy from `.env.example`) or export them in this shell, "
                "then restart Streamlit. Still missing: "
                + ", ".join(missing)
            )
        else:
            st.caption("All configured API key env vars are set.")

    with st.form("run_pipeline_form"):
        mode = st.radio(
            "Mode",
            options=["dry-run", "live"],
            horizontal=True,
            help="Dry-run renders prompts and writes records with no API calls.",
            disabled=running,
        )
        include_drafts = st.checkbox(
            "Include draft cases", value=False, disabled=running
        )
        submitted = st.form_submit_button("Run", type="primary", disabled=running)

    if submitted and not running:
        ready_names = [r["name"] for r in key_rows if r["present"]]
        skipped_names = [r["name"] for r in key_rows if not r["present"]]
        if mode == "live" and not ready_names:
            st.error(
                "Cannot start a live run — no API keys set. "
                "Export at least one (e.g. DEEPSEEK_API_KEY) in this shell "
                "and restart Streamlit."
            )
        else:
            if mode == "live":
                st.warning(
                    "Live mode will call APIs and may incur cost. "
                    f"Running: {', '.join(ready_names)}."
                    + (
                        f" Skipping (no key): {', '.join(skipped_names)}."
                        if skipped_names
                        else ""
                    )
                )
            _start_pipeline_job(dry_run=(mode == "dry-run"), include_drafts=include_drafts)
            st.rerun()

    job = st.session_state.pipeline_job
    if not job:
        return

    _drain_job_queue(job)
    running = job["thread"].is_alive() and not job["finished"]
    finished = job["finished"] or not job["thread"].is_alive()
    if finished:
        job["finished"] = True

    result = job["result"]

    # Finished: summary first, log tucked away. In-progress: live progress + Cancel.
    if finished:
        if "error" in result:
            st.error(f"Pipeline failed: {result['error']}")
            if result.get("missing_keys"):
                st.info("Fix: export the env vars listed above, then restart Streamlit.")
        elif "summary" in result:
            _render_job_summary(result["summary"])
        if job["lines"]:
            with st.expander("Run log", expanded=False):
                st.code("\n".join(job["lines"]), language=None)
        if st.button("Clear run status", key="clear_pipeline_job"):
            st.session_state.pipeline_job = None
            st.rerun()
        return

    c1, c2 = st.columns([3, 1])
    with c1:
        st.write("**Run progress**")
    with c2:
        if st.button("Cancel", type="secondary", key="cancel_pipeline"):
            job["cancel_event"].set()
            st.toast("Cancel requested — stopping after the current call…")

    frac = min(job["done"] / max(job["total"], 1), 1.0)
    status_text = job["lines"][-1] if job["lines"] else "Starting…"
    st.progress(frac, text=status_text)
    if job["lines"]:
        st.code("\n".join(job["lines"][-40:]), language=None)

    time.sleep(1.0)
    st.rerun()


def view_past_runs() -> None:
    st.subheader("Past Runs")
    runs = _list_run_dirs()
    if not runs:
        st.info("No runs found under `outputs/`.")
        return

    run_names = [p.name for p in runs]
    default_idx = 0
    if st.session_state.get("selected_run") in run_names:
        default_idx = run_names.index(st.session_state["selected_run"])

    chosen = st.selectbox("Select a run", options=run_names, index=default_idx)
    run_dir = OUTPUTS_DIR / chosen

    manifest = load_json(run_dir / "manifest.json")
    st.write("**manifest.json**")
    st.json(manifest)

    records = _load_responses(run_dir)
    st.write(f"**responses.jsonl** ({len(records)} records)")

    if not records:
        st.warning("No response records in this run.")
        return

    model_names = sorted({r.get("model_name", "") for r in records})
    case_ids = sorted({r.get("case_id", "") for r in records}, key=lambda x: (len(x), x))

    f1, f2, f3 = st.columns(3)
    with f1:
        model_filter = st.multiselect("Model", options=model_names, default=model_names)
    with f2:
        case_filter = st.multiselect("Case", options=case_ids, default=case_ids)
    with f3:
        error_only = st.checkbox("Errors only", value=False)

    rows = []
    for r in records:
        if r.get("model_name") not in model_filter:
            continue
        if r.get("case_id") not in case_filter:
            continue
        err = r.get("error")
        if error_only and not err:
            continue
        rows.append({
            "case_id": r.get("case_id", ""),
            "model_name": r.get("model_name", ""),
            "response_text": r.get("response_text") or "",
            "error": err or "",
        })

    st.dataframe(rows, width=DF_WIDTH, hide_index=True)
    st.caption(f"Showing {len(rows)} of {len(records)} records (sortable via column headers)")


def view_config() -> None:
    st.subheader("Config")
    st.caption(
        "Read-only view of `config.yaml`. API keys are never shown — "
        "only the environment variable names they are read from."
    )
    cfg = load_config(str(CONFIG_PATH))
    safe = _safe_config_display(cfg)

    st.write("**Generation params**")
    st.json(safe["generation_params"])

    st.write("**Models** (key values omitted)")
    st.dataframe(safe["models"], width=DF_WIDTH, hide_index=True)

    st.write("**Versions & paths**")
    st.json({
        "prompt_version": safe["prompt_version"],
        "benchmark_version": safe["benchmark_version"],
        "paths": safe["paths"],
    })

    st.write("**Pricing** (USD per 1K tokens)")
    st.json(safe["pricing_usd_per_1k_tokens"])

    with st.expander("Raw YAML (keys redacted)"):
        # Re-serialize the safe dict so no secret values appear.
        st.code(yaml.safe_dump(safe, sort_keys=False), language="yaml")


def _load_judgement_entries() -> list[dict]:
    if not JUDGEMENT_ENTRIES.exists():
        return []
    data = load_json(JUDGEMENT_ENTRIES)
    return data if isinstance(data, list) else []


def build_judgement_entry(
    *,
    rater_id: str,
    pack_id: str,
    run_id: str,
    blind_id: str,
    case_id: str,
    variant_index: int,
    prompt_hash: str,
    rubric_scores: dict[str, int],
    judgement: str,
    reasoning: str,
    refine_detail: str = "",
    timestamp: str | None = None,
) -> dict:
    """Build one judgement_log row in the current blinded schema (no model name)."""
    return {
        "rater_id": rater_id.strip(),
        "pack_id": pack_id,
        "run_id": run_id,
        "blind_id": blind_id,
        "case_id": case_id,
        "variant_index": int(variant_index),
        "prompt_hash": prompt_hash,
        "rubric_scores": {k: int(rubric_scores[k]) for k in RUBRIC_DIM_KEYS},
        "judgement": judgement,
        "reasoning": reasoning.strip(),
        "refine_detail": refine_detail.strip() if judgement == "refine" else "",
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }


def _scored_blind_ids(entries: list[dict], rater_id: str) -> set[str]:
    return {
        e.get("blind_id")
        for e in entries
        if e.get("rater_id") == rater_id and e.get("blind_id")
    }


def view_score() -> None:
    st.subheader("Score")
    st.caption(
        "Write reliability judgements into `judgement_log/entries.json` "
        "(Jack’s accept/reject/refine + 7 rubric scores). "
        "Uses the blinded schema in `judgement_log/schema.json` — no model names."
    )

    runs = _list_run_dirs()
    live_runs = [p for p in runs if not p.name.startswith("dryrun_")]
    if not live_runs:
        st.info("No live runs under `outputs/` yet — run the pipeline first.")
        return

    run_names = [p.name for p in live_runs]
    default_idx = run_names.index(PEER_RUN_ID) if PEER_RUN_ID in run_names else 0

    rater_id = st.text_input("Rater ID", value="andrei", help="Must stay consistent for kappa joins.")
    run_name = st.selectbox("Pipeline run to score", options=run_names, index=default_idx)
    try:
        pack, _blind_map = build_pack(run_id=run_name)
    except (FileNotFoundError, ValueError) as e:
        st.warning(str(e))
        return

    items = pack.get("items") or []
    if not items:
        st.warning("This run has no scorable live responses.")
        return

    cases_by_id = {c["id"]: c for c in _load_cases_table()[0]}
    entries = _load_judgement_entries()
    scored = _scored_blind_ids(entries, rater_id.strip())

    case_ids = sorted(
        {it["case_id"] for it in items},
        key=lambda x: (len(x), int(x[1:]) if x[1:].isdigit() else x),
    )

    show_unscored_only = st.checkbox(
        "Only show unscored blinded items for this rater",
        value=True,
    )

    c1, c2 = st.columns(2)
    with c1:
        case_id = st.selectbox("Case", options=case_ids)
    with c2:
        variants = [it for it in items if it["case_id"] == case_id]
        variants.sort(key=lambda it: it.get("variant_index") or 0)
        if show_unscored_only:
            variants = [it for it in variants if it["blind_id"] not in scored]
        if not variants:
            st.info("All blinded replies for this case are already scored by this rater.")
            item = None
        else:
            labels = {
                it["blind_id"]: (
                    f"{it['blind_id']} · AI reply {it['variant_index']} of {it['variant_total']}"
                )
                for it in variants
            }
            chosen = st.selectbox("Blinded reply", options=list(labels.keys()), format_func=lambda b: labels[b])
            item = next(it for it in variants if it["blind_id"] == chosen)

    st.caption(
        f"Log coverage for `{rater_id.strip() or '?'}`: "
        f"{sum(1 for e in entries if e.get('rater_id') == rater_id.strip())} entries "
        f"· pack `{pack.get('pack_id', '')}` has {len(items)} blinded items"
    )

    if not item or not rater_id.strip():
        return

    case = cases_by_id.get(case_id, {})
    rubric = load_json(RUBRIC_PATH)
    dims = {d["key"]: d for d in rubric.get("dimensions", [])}

    st.divider()
    left, right = st.columns(2)
    with left:
        st.write("**Case**")
        st.markdown(f"**{case_id}** · `{case.get('topic', '')}` · status `{case.get('status', '')}`")
        st.write("Question")
        st.code(case.get("question", ""), language=None)
        st.write(f"Correct: `{case.get('correct_answer', '')}`")
        st.write(f"Wrong: `{case.get('wrong_answer', '')}`")
        st.write(f"Misconception: {case.get('misconception', '')}")
    with right:
        st.write(
            f"**AI reply {item['variant_index']} of {item['variant_total']}** "
            f"(`{item['blind_id']}` — model hidden)"
        )
        st.text_area(
            "response",
            value=item.get("response_text") or "",
            height=280,
            disabled=True,
            label_visibility="collapsed",
        )

    with st.expander("Rubric anchors (1–5)", expanded=False):
        for key in RUBRIC_DIM_KEYS:
            d = dims.get(key, {})
            anchors = d.get("anchors", {})
            st.markdown(
                f"**{d.get('name', key)}** — {d.get('definition', '')}\n\n"
                + " · ".join(f"{i}: {anchors.get(str(i), '')}" for i in range(1, 6))
            )

    already = item["blind_id"] in scored
    if already:
        st.warning(
            "This rater already has an entry for this blind_id. "
            "Saving would create a duplicate (validator will reject)."
        )

    with st.form("score_entry_form"):
        st.write("**Rubric scores (1–5)**")
        score_cols = st.columns(4)
        scores: dict[str, int] = {}
        for i, key in enumerate(RUBRIC_DIM_KEYS):
            label = dims.get(key, {}).get("name", key)
            with score_cols[i % 4]:
                scores[key] = st.selectbox(label, options=[1, 2, 3, 4, 5], index=2, key=f"score_{key}")

        judgement = st.radio(
            "Judgement",
            options=["accept", "reject", "refine"],
            horizontal=True,
            help="accept = counts as evidence; reject = unusable; refine = you revised after a second look.",
        )
        reasoning = st.text_area(
            "Reasoning (required)",
            height=140,
            placeholder="What the AI said, what stood out, and why these scores / this judgement.",
        )
        refine_detail = st.text_area(
            "Refine detail (required only if judgement=refine)",
            height=80,
            placeholder="What changed between first and final scores, and why.",
        )
        submitted = st.form_submit_button("Save to judgement log", type="primary", disabled=already)

    if submitted:
        if not reasoning.strip():
            st.error("Reasoning is required.")
            return
        if judgement == "refine" and not refine_detail.strip():
            st.error("refine_detail is required when judgement is refine.")
            return

        entry = build_judgement_entry(
            rater_id=rater_id.strip(),
            pack_id=pack["pack_id"],
            run_id=pack["run_id"],
            blind_id=item["blind_id"],
            case_id=case_id,
            variant_index=item["variant_index"],
            prompt_hash=item.get("prompt_hash") or "",
            rubric_scores=scores,
            judgement=judgement,
            reasoning=reasoning,
            refine_detail=refine_detail,
        )

        # Validate candidate against schema before writing.
        try:
            import jsonschema
            schema = load_json(JUDGEMENT_SCHEMA)
            jsonschema.Draft202012Validator(schema).validate(entry)
        except Exception as e:  # noqa: BLE001
            st.error(f"Entry failed schema validation: {e}")
            return

        new_entries = list(entries) + [entry]
        JUDGEMENT_ENTRIES.write_text(
            json.dumps(new_entries, indent=2) + "\n",
            encoding="utf-8",
        )
        check = validate_entries(JUDGEMENT_ENTRIES, JUDGEMENT_SCHEMA)
        if not check["ok"]:
            # Roll back write if full-file validation fails.
            JUDGEMENT_ENTRIES.write_text(
                json.dumps(entries, indent=2) + "\n",
                encoding="utf-8",
            )
            st.error("Appended entry made the log invalid — write rolled back.")
            for err in check["errors"]:
                st.write(f"- {err}")
            return

        st.success(
            f"Saved `{entry['blind_id']}` · {case_id} · "
            f"{judgement} · total {check['n_entries']} entries"
        )
        st.rerun()

    if st.button("Validate judgement log"):
        check = validate_entries(JUDGEMENT_ENTRIES, JUDGEMENT_SCHEMA)
        if check["ok"]:
            st.success(f"OK: {check['n_entries']} entries valid")
            if check["n_entries"]:
                st.write(check["rater_counts"], check["judgement_counts"])
        else:
            st.error(f"FAILED: {len(check['errors'])} issue(s)")
            for err in check["errors"]:
                st.write(f"- {err}")


def _peer_payload_from_session(pack: dict, rater_id: str, rater_name: str) -> dict:
    answers = st.session_state.get("peer_answers") or {}
    responses = []
    for item in pack["items"]:
        bid = item["blind_id"]
        saved = answers.get(bid) or {}
        responses.append(
            {
                "blind_id": bid,
                "case_id": item["case_id"],
                "prompt_hash": item.get("prompt_hash") or "",
                "rubric_scores": saved.get("rubric_scores") or {},
                "judgement": saved.get("judgement") or "",
                "reasoning": (saved.get("reasoning") or "").strip(),
                "refine_detail": (saved.get("refine_detail") or "").strip(),
                "timestamp": saved.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            }
        )
    return {
        "pack_id": pack["pack_id"],
        "run_id": pack["run_id"],
        "rater_id": rater_id.strip(),
        "rater_name": rater_name.strip(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "n_items": pack["n_items"],
        "responses": responses,
    }


def _capture_peer_item(item: dict, dims: list[dict]) -> dict:
    bid = item["blind_id"]
    scores = {}
    for d in dims:
        val = st.session_state.get(f"peer_dim_{bid}_{d['key']}")
        if val is not None:
            scores[d["key"]] = int(val)
    return {
        "blind_id": bid,
        "rubric_scores": scores,
        "judgement": st.session_state.get(f"peer_j_{bid}") or "",
        "reasoning": st.session_state.get(f"peer_r_{bid}") or "",
        "refine_detail": st.session_state.get(f"peer_rd_{bid}") or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _peer_item_ready(ans: dict, dims: list[dict]) -> str | None:
    if len(ans.get("rubric_scores") or {}) < len(dims):
        return "Score all 7 dimensions."
    if not ans.get("judgement"):
        return "Pick accept, reject, or refine."
    if not (ans.get("reasoning") or "").strip():
        return "Reasoning is required."
    if ans.get("judgement") == "refine" and not (ans.get("refine_detail") or "").strip():
        return "refine_detail is required when judgement is refine."
    return None


def view_peer_review() -> None:
    st.subheader("Peer review")
    st.caption(
        "Blinded Google-Forms-style scoring of the 150-item run "
        f"(`{PEER_RUN_ID}`, Q1–Q30 × 5 models). Model names are hidden. "
        "Email the HTML to a friend, or fill it here."
    )

    try:
        if "peer_pack" not in st.session_state:
            pack, _mmap = build_pack(run_id=PEER_RUN_ID)
            st.session_state.peer_pack = pack
        pack = st.session_state.peer_pack
    except (FileNotFoundError, ValueError) as e:
        st.error(str(e))
        return

    dims = pack.get("dimensions") or []
    st.write(
        f"**{pack['n_items']} items** · run `{pack['run_id']}` · "
        "shuffled, model names stripped"
    )

    mode = st.radio(
        "Mode",
        options=["Download HTML for a friend", "Fill here", "Import returned JSON"],
        horizontal=True,
    )

    if mode == "Download HTML for a friend":
        st.markdown(
            "Send **only** the HTML file. Do not send this repo, `outputs/`, "
            "or `blind_map.json` — those would unblind the models."
        )
        if st.button("Prepare HTML form"):
            built, mmap = build_pack(run_id=PEER_RUN_ID)
            leaks = pack_leak_warnings(built)
            paths = write_generated_pack(built, mmap)
            st.session_state.peer_html = paths["html"].read_text(encoding="utf-8")
            if leaks:
                st.warning("Possible model-name leak in the pack: " + ", ".join(leaks))
            else:
                st.success(f"Wrote `{paths['html']}`")
        if st.session_state.get("peer_html"):
            st.download_button(
                "Download SIT724_peer_review.html",
                data=st.session_state.peer_html,
                file_name="SIT724_peer_review.html",
                mime="text/html",
                type="primary",
            )
        return

    if mode == "Import returned JSON":
        uploaded = st.file_uploader("JSON your friend downloaded", type=["json"])
        if uploaded is None:
            return
        try:
            payload = json.loads(uploaded.getvalue().decode("utf-8"))
        except json.JSONDecodeError as e:
            st.error(f"Not valid JSON: {e}")
            return
        if not isinstance(payload, dict):
            st.error("File must be a JSON object.")
            return
        st.write(
            f"Rater `{payload.get('rater_id') or '?'}` · "
            f"{len(payload.get('responses') or payload.get('answers') or [])} rows · "
            f"pack `{payload.get('pack_id') or '?'}`"
        )
        if st.button("Import into judgement log", type="primary"):
            from tempfile import NamedTemporaryFile

            with NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
                json.dump(payload, tmp)
                tmp_path = Path(tmp.name)
            result = import_peer_file(tmp_path, run_id=payload.get("run_id") or PEER_RUN_ID)
            tmp_path.unlink(missing_ok=True)
            for w in result["warnings"]:
                st.warning(w)
            if result["ok"]:
                st.success(
                    f"Imported {result['n_imported']} entries "
                    f"(log now has {result['n_total']})."
                )
            else:
                st.error("Import failed.")
                for err in result["errors"]:
                    st.write(f"- {err}")
        return

    # Fill here (blinded, one item at a time).
    if "peer_idx" not in st.session_state:
        st.session_state.peer_idx = 0
    if "peer_answers" not in st.session_state:
        st.session_state.peer_answers = {}

    rater_cols = st.columns(2)
    with rater_cols[0]:
        rater_id = st.text_input("Rater ID", value="", placeholder="e.g. peer-alex")
    with rater_cols[1]:
        rater_name = st.text_input("Name (optional)", value="")
    if not rater_id.strip():
        st.info("Enter a rater ID to start. Use the same ID if you pause and come back.")
        return

    items = pack["items"]
    idx = max(0, min(st.session_state.peer_idx, len(items) - 1))
    st.session_state.peer_idx = idx
    item = items[idx]
    bid = item["blind_id"]
    n_done = sum(
        1
        for it in items
        if _peer_item_ready(st.session_state.peer_answers.get(it["blind_id"]) or {}, dims) is None
    )
    st.progress((idx + 1) / len(items), text=f"{idx + 1} of {len(items)} · {n_done} complete")

    left, right = st.columns(2)
    with left:
        st.write(f"**{item['case_id']}** · {item.get('topic', '')} · `{bid}`")
        st.write("Question")
        st.code(item.get("question") or "", language=None)
        st.write(f"Correct: `{item.get('correct_answer', '')}`")
        st.write(f"Wrong: `{item.get('wrong_answer', '')}`")
        st.write(f"Misconception: {item.get('misconception', '')}")
    with right:
        st.write("**AI feedback** (model hidden)")
        st.text_area(
            "ai_feedback",
            value=item.get("response_text") or "",
            height=280,
            disabled=True,
            label_visibility="collapsed",
        )

    st.write("**Rubric scores (1–5)**")
    score_cols = st.columns(4)
    for i, d in enumerate(dims):
        with score_cols[i % 4]:
            st.radio(
                d.get("name") or d["key"],
                options=[1, 2, 3, 4, 5],
                index=None,
                key=f"peer_dim_{bid}_{d['key']}",
                help=d.get("definition") or "",
            )

    with st.expander("Rubric anchors", expanded=False):
        for d in dims:
            anchors = d.get("anchors") or {}
            st.markdown(
                f"**{d.get('name', d['key'])}** — {d.get('definition', '')}\n\n"
                + " · ".join(f"{n}: {anchors.get(str(n), '')}" for n in range(1, 6))
            )

    st.radio(
        "Judgement",
        options=["accept", "reject", "refine"],
        index=None,
        horizontal=True,
        key=f"peer_j_{bid}",
    )
    st.text_area("Reasoning (required)", key=f"peer_r_{bid}", height=120)
    if st.session_state.get(f"peer_j_{bid}") == "refine":
        st.text_area("What changed on the second look", key=f"peer_rd_{bid}", height=80)

    nav1, nav2, nav3 = st.columns([1, 1, 2])
    with nav1:
        if st.button("Back", disabled=idx == 0):
            st.session_state.peer_answers[bid] = _capture_peer_item(item, dims)
            st.session_state.peer_idx = idx - 1
            st.rerun()
    with nav2:
        next_label = "Finish" if idx == len(items) - 1 else "Next"
        if st.button(next_label, type="primary"):
            ans = _capture_peer_item(item, dims)
            st.session_state.peer_answers[bid] = ans
            if idx == len(items) - 1:
                st.session_state.peer_finished = True
            else:
                st.session_state.peer_idx = idx + 1
            st.rerun()

    st.session_state.peer_answers[bid] = _capture_peer_item(item, dims)
    payload = _peer_payload_from_session(pack, rater_id, rater_name)
    st.download_button(
        "Download answers JSON (backup / send this if you used Fill here)",
        data=json.dumps(payload, indent=2),
        file_name=f"sit724-peer-{rater_id.strip()}.json",
        mime="application/json",
    )

    if st.session_state.get("peer_finished"):
        ready_n = sum(
            1 for it in items
            if _peer_item_ready(st.session_state.peer_answers.get(it["blind_id"]) or {}, dims) is None
        )
        if ready_n == len(items):
            st.success(
                f"All {len(items)} items have scores. Download the JSON and/or write it to the log."
            )
            if st.button("Write this session into the judgement log"):
                from tempfile import NamedTemporaryFile

                with NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
                    json.dump(payload, tmp)
                    tmp_path = Path(tmp.name)
                result = import_peer_file(tmp_path, run_id=PEER_RUN_ID)
                tmp_path.unlink(missing_ok=True)
                for w in result["warnings"]:
                    st.warning(w)
                if result["ok"]:
                    st.success(f"Imported {result['n_imported']} entries.")
                    st.session_state.peer_finished = False
                else:
                    st.error("Write failed.")
                    for e in result["errors"]:
                        st.write(f"- {e}")
        else:
            st.warning(f"{ready_n}/{len(items)} complete — go back and finish the rest before importing.")


# ---------------------------------------------------------------------------
# App shell
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="SIT724 Feedback Eval",
        layout="wide",
    )
    st.title("SIT724 Feedback-Evaluation Pipeline")
    st.caption("Local GUI · same validation & generation logic as the CLI scripts")

    tabs = st.tabs(
        ["Benchmark", "Rubric", "Run Pipeline", "Past Runs", "Score", "Peer review", "Config"]
    )
    with tabs[0]:
        view_benchmark()
    with tabs[1]:
        view_rubric()
    with tabs[2]:
        view_run_pipeline()
    with tabs[3]:
        view_past_runs()
    with tabs[4]:
        view_score()
    with tabs[5]:
        view_peer_review()
    with tabs[6]:
        view_config()


if __name__ == "__main__":
    main()
