"""Lab: the batch experiment. Every prompt is generated in both modes,
scored, and logged with a batch id; the summary gives the true-positive and
false-positive rates per length. Long runs belong on the command line."""

import time

import streamlit as st

import experiment
from ui import common, lab

common.require_role("teacher")
state = st.session_state
config = common.load_config()

st.title("Experiment", anchor=False)
st.caption("Measure detection instead of demonstrating it. The summary gives the true-positive "
           "rate (watermarked rows flagged) and the false-positive rate (normal rows flagged).")
if state["exp_msg"]:
    st.success(state["exp_msg"], icon=":material/check_circle:")
    state["exp_msg"] = ""

try:
    all_prompts = experiment.load_prompts()
except OSError as exc:
    all_prompts = []
    st.error("Could not read {}: {}".format(experiment.PROMPT_FILE, exc), icon=":material/error:")

with st.container(border=True):
    st.subheader("New batch", anchor=False)
    x1, x2, x3, x4 = st.columns(4)
    n_prompts = x1.number_input("Prompts (of {})".format(len(all_prompts)), 1, max(len(all_prompts), 1),
                                min(3, max(len(all_prompts), 1)), key="exp_prompts")
    lengths = x2.multiselect("Lengths (max tokens)", [50, 150, 300, 500], default=[150],
                             key="exp_lengths")
    runs = x3.number_input("Runs per cell", 1, 5, 1, key="exp_runs")
    seed_base = x4.number_input("Seed base", 0, 10_000_000, 100, key="exp_seed")
    known = experiment.known_batches()
    resume = st.selectbox("Resume an existing batch (finished cells are skipped)",
                          ["(new batch)"] + ["{} ({} rows)".format(b, n) for b, n in sorted(known.items())],
                          key="exp_resume")
    total = int(n_prompts) * len(lengths) * 2 * int(runs)
    est_s = sum(int(n_prompts) * int(runs) * L * (1 / 4.3 + 1 / 8.0) for L in lengths)
    st.caption("{} generations, roughly {:.0f} min on this CPU. For runs over an hour use the command "
               "line, which can be interrupted and resumed:".format(total, est_s / 60))
    st.code("python experiment.py --lengths {} --runs {} --seed {}".format(
        " ".join(str(L) for L in lengths), int(runs), int(seed_base)), language="bash")
    start = st.button("Run experiment", type="primary", icon=":material/play_arrow:",
                      disabled=not lengths or not all_prompts, key="exp_run")

if start:
    engine, lock = common.engine()
    st.button("Stop after the current generation", icon=":material/stop_circle:", key="exp_stop",
              help="Any click during a run stops it after the generation in progress; finished "
                   "cells stay logged and the batch can be resumed.")
    bar = st.progress(0.0)
    line = st.empty()
    t0 = time.time()

    def progress(done, total_cells, row):
        bar.progress(done / total_cells)
        eta = (time.time() - t0) / max(done, 1) * (total_cells - done)
        line.caption("{}/{}  prompt {}  length {}  {}  z = {:.2f}  {}  (about {:.0f} min left)".format(
            done, total_cells, row["prompt_idx"], row["length"], row["mode"], row["z"],
            common.verdict_text(row["label"]), eta / 60))

    batch_id = None if resume == "(new batch)" else resume.split(" ")[0]
    try:
        with st.status("Running the batch...", expanded=True):
            batch_id = experiment.run_batch(
                engine, all_prompts[:int(n_prompts)], lengths, int(runs),
                seed_base=int(seed_base) if batch_id is None else None,
                batch_id=batch_id, on_progress=progress, lock=lock)
        state["exp_batch"] = batch_id
        state["exp_msg"] = "Batch {} finished.".format(batch_id)
        st.rerun()
    except (OSError, ValueError) as exc:
        st.error("Experiment failed: {}".format(exc), icon=":material/error:")

known = experiment.known_batches()
with st.container(border=True):
    st.subheader("Results", anchor=False)
    if not known:
        st.caption("No batches yet.")
    else:
        choices = sorted(known, reverse=True)
        default = state["exp_batch"] if state["exp_batch"] in choices else choices[0]
        show = st.selectbox("Batch", choices, index=choices.index(default),
                            format_func=lambda b: "{} ({} rows)".format(b, known[b]), key="exp_show")
        bdf = experiment.batch_frame(show)
        summary = experiment.summarise_batch(bdf, config)
        try:
            settings = experiment.read_settings(show)
            st.caption("Created {}; prompt file hash {}; seed base {}; lengths {}.".format(
                settings.get("created"), settings.get("prompt_file_hash"), settings.get("seed_base"),
                settings.get("lengths")))
        except (OSError, ValueError):
            st.caption("No settings file for this batch.")
        st.dataframe(summary, hide_index=True, column_config={
            "mean_z": st.column_config.NumberColumn("mean z", format="%.2f"),
            "mean_green_pct": st.column_config.NumberColumn("mean green %", format="%.1f"),
            "flagged_rate": st.column_config.NumberColumn("flagged", format="percent"),
            "possible_or_above_rate": st.column_config.NumberColumn("z ≥ possible", format="percent"),
            "inconclusive_rate": st.column_config.NumberColumn("inconclusive", format="percent")})
        if not bdf.empty:
            st.altair_chart(lab.z_chart(bdf.assign(result=bdf["mode"] + " / " + bdf["result"]),
                                        float(config["detection_threshold"])))
        state["exp_summary_export"] = summary
        st.download_button("Export batch summary", data=summary.to_csv(index=False).encode("utf-8"),
                           file_name="experiment_{}_summary.csv".format(show), mime="text/csv",
                           on_click=lab.on_export,
                           args=("exp_summary_export", "experiment_{}_summary".format(show)),
                           icon=":material/download:", key="exp_export")
        if state["export_msg"]:
            st.success(state["export_msg"], icon=":material/check_circle:")
            state["export_msg"] = ""
