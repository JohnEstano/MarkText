"""MarkText — Streamlit web front-end.

Run with:  streamlit run app.py

Same four sections as the Tkinter app (main.py), built on the same core:
  config.py    JSON configuration
  engine.py    generation + watermark detection
  history.py   CSV detection history

Streamlit reruns this whole script on every interaction, so anything that
must survive a rerun lives in st.session_state (per browser tab) or in
st.cache_resource (the model, shared by the whole server process).
"""

import datetime
import json
import pathlib
import threading
import time

import altair as alt
import pandas as pd
import streamlit as st

import config as cfg
import experiment
import history
from engine import (
    Engine, LABEL_INCONCLUSIVE, LABEL_LIKELY, LABEL_NOT_DETECTED, LABEL_POSSIBLE,
)

BASE_DIR = pathlib.Path(__file__).resolve().parent
GENERATED_DIR = BASE_DIR / "generated"
EXPORT_DIR = BASE_DIR / "logs" / "exports"
README_PATH = BASE_DIR / "README.md"

MIN_TOKENS = 50
MAX_TOKENS = 2000

# Engine.detect() label -> badge tone, the same four tones the web site uses
VERDICT_TONE = {
    LABEL_LIKELY: "accent",
    LABEL_POSSIBLE: "warn",
    LABEL_NOT_DETECTED: "neutral",
    LABEL_INCONCLUSIVE: "muted",
}

# Badge colours per theme (web/src/app/globals.css tokens). Streamlit tells
# us which theme the browser resolved through st.context.theme.
BADGE_COLOURS = {
    "light": {
        "accent": ("#e6f2ec", "#1f5c42"), "warn": ("#fbf1dc", "#9a6b1f"),
        "neutral": ("#f1f1ef", "#52525b"), "muted": ("#f1f1ef", "#a1a1aa"),
    },
    "dark": {
        "accent": ("#163526", "#a7dcc3"), "warn": ("#2d2412", "#d4a24c"),
        "neutral": ("#1c1c1f", "#a1a1aa"), "muted": ("#1c1c1f", "#71717a"),
    },
}

def theme_type() -> str:
    """'light' or 'dark' as the browser resolved it; light if unknown."""
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # older Streamlit or no browser context
        return "light"


def badge(label: str) -> str:
    """HTML for a verdict badge in the web site's style."""
    bg, fg = BADGE_COLOURS[theme_type()][VERDICT_TONE.get(label, "muted")]
    return ('<span style="display:inline-block;padding:4px 12px;border-radius:999px;'
            'background:{bg};color:{fg};font-family:Geist,sans-serif;font-size:13px;'
            'font-weight:500;letter-spacing:0.01em">{label}</span>'
            ).format(bg=bg, fg=fg, label=label)


def render_header() -> None:
    """Wordmark row: the mark, the name and the one-line promise. The mark is
    static/mark.svg (served at app/static, same geometry as the web site's
    mark-paths.ts); st.html strips inline SVG, an <img> survives."""
    st.html(
        '<div style="display:flex;align-items:center;gap:12px;margin:4px 0 2px">'
        '<img src="app/static/mark.svg" width="30" height="30" alt="">'
        '<span style="font-family:Geist,sans-serif;font-size:26px;font-weight:600;'
        'letter-spacing:-0.02em">MarkText</span></div>'
        '<p style="margin:0 0 6px;opacity:0.7;font-size:15px">Watermark the text you '
        'generate. Prove it later with a statistical test.</p>'
    )


ABOUT_FALLBACK = """\
### MarkText

README.md was not found next to app.py. MarkText detects ONLY text it
generated with its own watermark key and parameters; it is NOT a universal
AI-text detector.
"""


# ---------------------------------------------------------------- resources
@st.cache_resource(show_spinner="Loading model (first run may download ~1 GB)...")
def get_engine():
    """Load the model once per server process; every session shares it.

    The lock serialises model and detector calls, because the cached Engine
    is one object shared by all browser tabs.
    """
    return Engine(cfg.load_config()), threading.Lock()


def read_readme():
    try:
        return README_PATH.read_text(encoding="utf-8-sig")
    except OSError:
        return ABOUT_FALLBACK


def ensure_dirs():
    for d in (GENERATED_DIR / "normal", GENERATED_DIR / "watermarked", EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------ file handling
def save_txt(info):
    """Write the text to generated/<mode>/ plus a <name>.json sidecar holding
    the mode, seed and parameters it was generated with."""
    mode = info["mode"]
    folder = GENERATED_DIR / mode
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / default_filename(mode)
    path.write_text(info["text"], encoding="utf-8")
    record = {k: v for k, v in info.items() if k != "text"}
    record["saved_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record["text_file"] = path.name
    with open(path.with_suffix(".json"), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=4)
    return path


def default_filename(mode):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return "marktext_{}_{}.txt".format(mode, stamp)


def stamped(stem, suffix):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return EXPORT_DIR / "{}_{}{}".format(stem, stamp, suffix)


def load_history_df():
    """The history CSV as a DataFrame. history.py writes it row by row with
    the csv module; pandas only reads it for filtering and summaries."""
    history.ensure_history()
    try:
        df = pd.read_csv(history.HISTORY_PATH, parse_dates=["timestamp"], encoding="utf-8")
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=history.COLUMNS)
    for c in ("filename", "mode", "batch_id", "source", "note", "seeding_scheme"):
        df[c] = df[c].fillna("").astype(str)
    df["run_id"] = df["run_id"].astype(str)
    return df


def export_csv(df, stem):
    """Write a NEW csv under logs/exports/; the history file is never edited."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = stamped(stem, ".csv")
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def summarise(df, by=("result",)):
    by = list(by)
    if df.empty:
        return pd.DataFrame(columns=by + ["analyses", "mean_z", "mean_green_pct", "mean_tokens"])
    return (df.groupby(by)
              .agg(analyses=("z_score", "count"),
                   mean_z=("z_score", "mean"),
                   mean_green_pct=("green_pct", "mean"),
                   mean_tokens=("tokens_scored", "mean"))
              .reset_index())


def z_chart(df, threshold):
    """Scatter of z vs tokens with a rule at the detection threshold."""
    base = alt.Chart(df).mark_circle(size=70).encode(
        x=alt.X("tokens_scored:Q", title="tokens scored"),
        y=alt.Y("z_score:Q", title="z-score"),
        color=alt.Color("result:N", title="result"),
        tooltip=["run_id", "source", "mode", "tokens_scored", "z_score", "result"])
    rule = alt.Chart(pd.DataFrame({"z": [threshold]})).mark_rule(
        strokeDash=[6, 4], color="#cc0000").encode(y="z:Q")
    return (base + rule).properties(height=320).interactive()


# ---------------------------------------------------------------- callbacks
# Callbacks run before the rerun, which is the only moment a widget's value
# may be set through st.session_state.
def on_save():
    state = st.session_state
    try:
        state["gen_saved"] = str(save_txt(state["gen_info"]))
        state["gen_save_error"] = ""
    except OSError as exc:
        state["gen_saved"] = ""
        state["gen_save_error"] = str(exc)


def on_upload():
    state = st.session_state
    state["upload_error"] = ""
    uploaded = state.get("uploader")
    if uploaded is None:
        state["detect_filename"] = ""
        state["detect_loaded"] = ""
        return
    try:
        text = uploaded.getvalue().decode("utf-8-sig")   # tolerate a BOM
    except UnicodeDecodeError as exc:
        state["upload_error"] = "{} is not valid UTF-8 text: {}".format(uploaded.name, exc)
        return
    state["detect_text"] = text
    state["detect_loaded"] = text.strip()
    state["detect_filename"] = uploaded.name
    state["detect_stats"] = None


def on_clear_detect():
    state = st.session_state
    state["detect_text"] = ""
    state["detect_loaded"] = ""
    state["detect_filename"] = ""
    state["detect_stats"] = None
    state["upload_error"] = ""


def on_export(key, stem):
    # the frame to export was stashed in session_state by the History tab
    state = st.session_state
    try:
        state["export_msg"] = "Exported to: {}".format(export_csv(state[key], stem))
        state["export_error"] = ""
    except OSError as exc:
        state["export_msg"] = ""
        state["export_error"] = "Export failed: {}".format(exc)


def on_update_record():
    state = st.session_state
    rid = state.get("manage_id", "").strip()
    try:
        backup = history.update_record(rid, note=state.get("manage_note", ""),
                                       filename=state.get("manage_filename", ""))
        state["history_msg"] = "Record {} updated. Backup: {}".format(rid, backup)
    except (ValueError, OSError) as exc:
        state["history_msg"] = "Record NOT updated: {}".format(exc)


def on_delete_record():
    state = st.session_state
    rid = state.get("manage_id", "").strip()
    try:
        backup = history.delete_record(rid)
        state["history_msg"] = "Record {} deleted. Backup: {}".format(rid, backup)
        state["manage_id"] = ""
    except (ValueError, OSError) as exc:
        state["history_msg"] = "Record NOT deleted: {}".format(exc)
    state["confirm_delete"] = False


def on_clear_history():
    state = st.session_state
    try:
        backup = history.clear_history()   # writes a backup copy first
        state["history_msg"] = "History cleared. Backup saved to: {}".format(backup)
    except OSError as exc:
        state["history_msg"] = "History NOT cleared: {}".format(exc)
    state["confirm_clear"] = False


# --------------------------------------------------------------------- page
st.set_page_config(page_title="MarkText", page_icon="static/mark.svg", layout="wide")
render_header()

config_notes = []
try:
    config = cfg.load_config(notes=config_notes)
except ValueError as exc:
    st.error("Configuration error:\n\n{}".format(exc))
    st.stop()
ensure_dirs()
for note in config_notes:
    st.warning(note)

state = st.session_state
for key, default in (
    ("gen_text", ""), ("gen_mode", ""), ("gen_info", None),
    ("gen_saved", ""), ("gen_save_error", ""),
    ("detect_text", ""), ("detect_loaded", ""), ("detect_filename", ""),
    ("detect_stats", None), ("upload_error", ""), ("history_msg", ""),
    ("export_msg", ""), ("export_error", ""),
    ("export_rows", None), ("export_summary", None),
    ("exp_msg", ""), ("exp_batch", ""), ("exp_summary_export", None),
):
    state.setdefault(key, default)

try:
    engine, engine_lock = get_engine()
except Exception as exc:
    st.error("Failed to load the model:\n\n{}".format(exc))
    st.stop()

st.caption("Ready — {} on {}".format(config["model_id"], engine.device))

tab_gen, tab_det, tab_hist, tab_exp, tab_about = st.tabs(
    ["Generate", "Detect", "History", "Experiment", "About"])

# ----- TAB 1 — GENERATE
with tab_gen:
    with st.form("generate_form"):
        prompt = st.text_area("Prompt", height=140,
                              value="Tell me about the history of cryptography.")
        col_tok, col_mode = st.columns(2)
        default_tokens = min(max(int(config.get("max_new_tokens", 300)), MIN_TOKENS),
                             MAX_TOKENS)
        max_tok = col_tok.number_input(
            "Max tokens ({}–{})".format(MIN_TOKENS, MAX_TOKENS),
            min_value=MIN_TOKENS, max_value=MAX_TOKENS,
            value=default_tokens, step=10)
        mode_label = col_mode.radio("Mode", ["Watermarked", "Normal"], horizontal=True)
        submitted = st.form_submit_button("Generate", type="primary")

    if submitted:
        if not prompt.strip():
            st.error("Please enter a prompt.")
        else:
            mode = mode_label.lower()
            try:
                with st.spinner("Generating {} text...".format(mode)):
                    with engine_lock:
                        info = engine.generate(prompt.strip(),
                                               max_new_tokens=int(max_tok),
                                               watermarked=(mode == "watermarked"))
            except Exception as exc:
                st.error("Generation failed: {}".format(exc))
            else:
                # remember the mode this text was made with, not the radio's
                # later position
                state["gen_info"] = info
                state["gen_text"] = info["text"]
                state["gen_mode"] = info["mode"]
                state["gen_saved"] = ""
                state["gen_save_error"] = ""

    if state["gen_text"]:
        st.subheader("Output ({})".format(state["gen_mode"]))
        # st.code gives a built-in copy-to-clipboard button
        st.code(state["gen_text"], language=None, wrap_lines=True)
        info = state["gen_info"] or {}
        st.caption("{:,} words generated, seed {}, {} tokens".format(
            len(state["gen_text"].split()), info.get("seed", "?"), info.get("new_tokens", "?")))
        st.download_button(
            "Save .TXT",
            data=state["gen_text"].encode("utf-8"),
            file_name=default_filename(state["gen_mode"]),
            mime="text/plain",
            on_click=on_save,
            help="Writes the text and a .json sidecar (mode, seed, parameters) into "
                 "generated/{}/ and downloads a copy.".format(state["gen_mode"]))
        if state["gen_saved"]:
            st.success("Saved to: {}".format(state["gen_saved"]))
        if state["gen_save_error"]:
            st.error("Save failed: {}".format(state["gen_save_error"]))

# ----- TAB 2 — DETECT
with tab_det:
    col_in, col_out = st.columns([2, 1])

    with col_in:
        st.file_uploader("Open TXT", type=["txt"], key="uploader", on_change=on_upload)
        if state["upload_error"]:
            st.error(state["upload_error"])
        st.text_area("Text to analyze", key="detect_text", height=380)
        col_a, col_c = st.columns(2)
        analyze = col_a.button("Analyze", type="primary")
        col_c.button("Clear", on_click=on_clear_detect)

    if analyze:
        text = state["detect_text"].strip()
        state["detect_stats"] = None
        if not text:
            col_in.error("Paste or open text to analyze.")
        else:
            try:
                with st.spinner("Analyzing..."):
                    with engine_lock:
                        stats = engine.detect(text)
            except Exception as exc:
                col_in.error("Detection failed: {}".format(exc))
            else:
                if stats is None:
                    col_in.warning("Text is too short for analysis. Need at least "
                                   "{} tokens (a sentence or two).".format(engine.min_tokens))
                else:
                    state["detect_stats"] = stats
                    # the file name only applies if the box still holds that file
                    unchanged = state["detect_filename"] and text == state["detect_loaded"]
                    try:
                        history.append_history(
                            stats, source="file" if unchanged else "manual",
                            filename=state["detect_filename"] if unchanged else "")
                    except OSError as exc:
                        col_in.error("Result shown but NOT logged; could not write "
                                     "the history CSV (is it open in Excel?): "
                                     "{}".format(exc))

    with col_out:
        st.subheader("Detection Results")
        stats = state["detect_stats"]
        if stats is None:
            st.write("—")
        else:
            m1, m2 = st.columns(2)
            m1.metric("Tokens analyzed", stats["num_tokens_scored"])
            m2.metric("Green tokens", stats["num_green_tokens"])
            m1.metric("Watermark signal", "{:.1f}%".format(stats["green_fraction"] * 100.0))
            m2.metric("Z-score", "{:.2f}".format(stats["z_score"]))
            m1.metric("p-value", "{:.2e}".format(stats["p_value"]))
            st.html(badge(stats["label"]))
        st.caption("MarkText detects ONLY text it generated with its own watermark "
                   "key and parameters. It is NOT a universal AI-text detector. "
                   "'NOT DETECTED' means this watermark was not found, not that a "
                   "human wrote the text.")

# ----- TAB 3 — HISTORY
with tab_hist:
    if state["history_msg"]:
        st.info(state["history_msg"])
        state["history_msg"] = ""
    if state["export_msg"]:
        st.success(state["export_msg"])
        state["export_msg"] = ""
    if state["export_error"]:
        st.error(state["export_error"])
        state["export_error"] = ""

    try:
        df = load_history_df()
    except (OSError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        df = pd.DataFrame(columns=history.COLUMNS)
        st.error("Could not read the history CSV: {}".format(exc))

    if df.empty:
        st.write("No detection history yet.")
    else:
        # --- filters: one Boolean mask, original df untouched
        st.subheader("Filter records")
        f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
        results = sorted(df["result"].unique())
        pick = f1.multiselect("Result", results, default=results)
        query = f2.text_input("Filename contains", "")
        dmin, dmax = df["timestamp"].min().date(), df["timestamp"].max().date()
        dates = f3.date_input("Date range", (dmin, dmax), min_value=dmin, max_value=dmax)
        tmax = int(df["tokens_scored"].max())
        min_tok = f4.number_input("Min tokens", 0, tmax, 0, step=10)
        g1, g2 = st.columns(2)
        sources = sorted(df["source"].unique())
        pick_src = g1.multiselect("Source", sources, default=sources)
        batches = ["(all)"] + sorted(b for b in df["batch_id"].unique() if b)
        pick_batch = g2.selectbox("Batch", batches)

        mask = df["result"].isin(pick) & df["source"].isin(pick_src)
        if pick_batch != "(all)":
            mask &= df["batch_id"] == pick_batch
        if query:
            mask &= df["filename"].str.contains(query, case=False, na=False)
        if isinstance(dates, tuple) and len(dates) == 2:
            mask &= df["timestamp"].dt.date.between(dates[0], dates[1])
        mask &= df["tokens_scored"] >= min_tok
        filtered = df[mask]

        # --- KPIs, chart, summary, table: all driven by `filtered`
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Analyses in view", len(filtered))
        k2.metric("Mean z-score", "{:.2f}".format(filtered["z_score"].mean())
                  if len(filtered) else "—")
        k3.metric("Flagged LIKELY MARKTEXT",
                  "{:.0%}".format((filtered["result"] == "LIKELY MARKTEXT").mean())
                  if len(filtered) else "—")
        k4.metric("Median tokens", int(filtered["tokens_scored"].median())
                  if len(filtered) else "—")

        if filtered.empty:
            st.warning("No records match the filters.")
        else:
            st.subheader("Z-score vs tokens analysed")
            st.altair_chart(z_chart(filtered, float(config["detection_threshold"])),
                            width="stretch")
            st.caption("Dashed line: detection_threshold = {}".format(config["detection_threshold"]))

            has_modes = (filtered["mode"] != "").any()
            summary = summarise(filtered, ("mode", "result") if has_modes else ("result",))
            st.subheader("Summary by {}result".format("mode and " if has_modes else ""))
            st.dataframe(summary, hide_index=True, width="stretch",
                         column_config={
                             "mean_z": st.column_config.NumberColumn(format="%.2f"),
                             "mean_green_pct": st.column_config.NumberColumn(format="%.1f"),
                             "mean_tokens": st.column_config.NumberColumn(format="%.0f")})

            st.subheader("Records")
            st.dataframe(filtered.sort_values("timestamp", ascending=False),
                         hide_index=True, width="stretch",
                         column_config={
                             "timestamp": st.column_config.DatetimeColumn(
                                 format="YYYY-MM-DD HH:mm:ss"),
                             "green_pct": st.column_config.NumberColumn(
                                 "green %", format="%.2f"),
                             "z_score": st.column_config.NumberColumn(format="%.2f"),
                             "p_value": st.column_config.NumberColumn(format="%.2e")})

            # export: the app writes a new csv under logs/exports/ and the
            # browser downloads a copy; the history file itself is never edited
            state["export_rows"] = filtered
            state["export_summary"] = summary
            e1, e2 = st.columns(2)
            e1.download_button("Export filtered rows (CSV)",
                               data=filtered.to_csv(index=False).encode("utf-8"),
                               file_name="history_filtered.csv", mime="text/csv",
                               on_click=on_export, args=("export_rows", "history_filtered"))
            e2.download_button("Export summary (CSV)",
                               data=summary.to_csv(index=False).encode("utf-8"),
                               file_name="history_summary.csv", mime="text/csv",
                               on_click=on_export, args=("export_summary", "history_summary"))

        # --- one record at a time, by run_id (backup before every write)
        with st.expander("Manage one record (by run_id)"):
            st.text_input("run_id", key="manage_id")
            rid = state.get("manage_id", "").strip()
            rec = history.find_record(rid) if rid else None
            if rid and rec is None:
                st.warning("No record with run_id {!r}.".format(rid))
            if rec:
                st.dataframe(pd.DataFrame([rec]), hide_index=True, width="stretch")
                st.text_input("filename", value=rec.get("filename", ""), key="manage_filename")
                st.text_input("note", value=rec.get("note", ""), key="manage_note")
                st.caption("Only note and filename can change; measurements are immutable. "
                           "A backup is written before any change.")
                c1, c2 = st.columns(2)
                c1.button("Save changes", on_click=on_update_record)
                confirm_del = c2.checkbox("Yes, delete this record", key="confirm_delete")
                c2.button("Delete record", disabled=not confirm_del, on_click=on_delete_record)

        st.caption("{} analyses in {} - writes go through history.py (csv module); "
                   "this tab reads with pandas and writes only new files.".format(
                       len(df), history.HISTORY_PATH))
        confirm = st.checkbox("Yes, clear all detection records "
                              "(a backup copy is written to logs/exports/ first)",
                              key="confirm_clear")
        st.button("Clear History", disabled=not confirm, on_click=on_clear_history)

# ----- TAB 4 — EXPERIMENT
with tab_exp:
    st.markdown("Measure detection instead of demonstrating it: every prompt is generated "
                "in both modes, scored, and logged as a history row tagged with a batch id. "
                "The summary gives the **true-positive rate** (watermarked rows flagged) and "
                "the **false-positive rate** (normal rows flagged) per length.")
    if state["exp_msg"]:
        st.info(state["exp_msg"])
        state["exp_msg"] = ""

    try:
        all_prompts = experiment.load_prompts()
    except OSError as exc:
        all_prompts = []
        st.error("Could not read {}: {}".format(experiment.PROMPT_FILE, exc))

    x1, x2, x3, x4 = st.columns(4)
    n_prompts = x1.number_input("Prompts (of {})".format(len(all_prompts)),
                                1, max(len(all_prompts), 1), min(100, max(len(all_prompts), 1)))
    lengths = x2.multiselect("Lengths (max tokens)", [50, 150, 300, 500], default=[150])
    runs = x3.number_input("Runs per cell", 1, 5, 1)
    seed_base = x4.number_input("Seed base", 0, 10_000_000, 100)
    known = experiment.known_batches()
    resume = st.selectbox("Resume an existing batch (skips finished cells)",
                          ["(new batch)"] + ["{} ({} rows)".format(b, n) for b, n in sorted(known.items())])
    total = int(n_prompts) * len(lengths) * 2 * int(runs)
    est_s = sum(int(n_prompts) * int(runs) * L * (1 / 4.3 + 1 / 8.0) for L in lengths)
    st.caption("{} generations, roughly {:.0f} min on this CPU. For runs over an hour use the "
               "command line, which can be interrupted and resumed:  "
               "`python experiment.py --lengths {} --runs {} --seed {}`".format(
                   total, est_s / 60, " ".join(str(L) for L in lengths), int(runs), int(seed_base)))

    run_col, stop_col = st.columns([1, 3])
    start = run_col.button("Run experiment", type="primary", disabled=not lengths or not all_prompts)
    if start:
        cancel = threading.Event()
        stop_col.button("Stop after the current generation", on_click=cancel.set)
        bar = st.progress(0.0)
        status = st.empty()
        t0 = time.time()

        def progress(done, total, row):
            bar.progress(done / total)
            eta = (time.time() - t0) / max(done, 1) * (total - done)
            status.write("{}/{}  p{} L{} {}  z={:.2f} {}  (eta {:.0f} min)".format(
                done, total, row["prompt_idx"], row["length"], row["mode"],
                row["z"], row["label"], eta / 60))

        batch_id = None if resume == "(new batch)" else resume.split(" ")[0]
        try:
            with st.status("Running batch...", expanded=True):
                batch_id = experiment.run_batch(
                    engine, all_prompts[:int(n_prompts)], lengths, int(runs),
                    seed_base=int(seed_base) if batch_id is None else None,
                    batch_id=batch_id, on_progress=progress, cancel_event=cancel,
                    lock=engine_lock)
            state["exp_batch"] = batch_id
            state["exp_msg"] = "Batch {} finished{}.".format(
                batch_id, " (stopped early)" if cancel.is_set() else "")
        except (OSError, ValueError) as exc:
            st.error("Experiment failed: {}".format(exc))

    st.subheader("Results")
    known = experiment.known_batches()
    if not known:
        st.write("No batches yet.")
    else:
        choices = sorted(known, reverse=True)
        default = state["exp_batch"] if state["exp_batch"] in choices else choices[0]
        show = st.selectbox("Batch", choices, index=choices.index(default))
        bdf = experiment.batch_frame(show)
        summary = experiment.summarise_batch(bdf, config)
        try:
            settings = experiment.read_settings(show)
            st.caption("{} rows; created {}; prompt file hash {}; seed base {}; lengths {}".format(
                len(bdf), settings.get("created"), settings.get("prompt_file_hash"),
                settings.get("seed_base"), settings.get("lengths")))
        except (OSError, ValueError):
            st.caption("{} rows (no settings file for this batch)".format(len(bdf)))
        st.dataframe(summary, hide_index=True, width="stretch",
                     column_config={"mean_z": st.column_config.NumberColumn(format="%.2f"),
                                    "mean_green_pct": st.column_config.NumberColumn(format="%.1f"),
                                    "flagged_rate": st.column_config.NumberColumn(format="%.0%%"),
                                    "possible_or_above_rate": st.column_config.NumberColumn(format="%.0%%"),
                                    "inconclusive_rate": st.column_config.NumberColumn(format="%.0%%")})
        if not bdf.empty:
            st.altair_chart(z_chart(bdf.assign(result=bdf["mode"] + " / " + bdf["result"]),
                                    float(config["detection_threshold"])), width="stretch")
        state["exp_summary_export"] = summary
        st.download_button("Export batch summary (CSV)",
                           data=summary.to_csv(index=False).encode("utf-8"),
                           file_name="experiment_{}_summary.csv".format(show), mime="text/csv",
                           on_click=on_export, args=("exp_summary_export", "experiment_{}_summary".format(show)))
        if state["export_msg"]:
            st.success(state["export_msg"])
            state["export_msg"] = ""


# ----- TAB 5 — ABOUT
with tab_about:
    st.markdown(read_readme())
    with st.expander("Current configuration (config/watermark_config.json)"):
        shown = json.loads(json.dumps(config))
        shown["watermark"]["hashing_key"] = "(hidden)"
        st.json(shown)
