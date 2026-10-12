"""Helpers for the Lab pages (Generate, Detect, History, Experiment): the
original single-page MarkText, now one page each for the teacher.

File handling here, same as before the classroom existed:
- Generate writes generated/<mode>/marktext_<mode>_<stamp>.txt plus a
  .json sidecar (mode, seed, parameters; never the hashing key);
- Detect appends one row to logs/detection_history.csv (history.py);
- History reads that CSV with pandas and writes only NEW files under
  logs/exports/ (filtered rows, summaries); record edits and deletes go
  through history.py, which backs the file up first.
"""

import datetime
import json
import pathlib

import altair as alt
import pandas as pd
import streamlit as st

import history
from ui import charts

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
GENERATED_DIR = BASE_DIR / "generated"
EXPORT_DIR = BASE_DIR / "logs" / "exports"
README_PATH = BASE_DIR / "README.md"
MIN_TOKENS = 50
MAX_TOKENS = 2000

ABOUT_FALLBACK = """\
### MarkText

README.md was not found next to app.py. MarkText detects only text it
generated with its own watermark key and parameters; it is not a universal
AI-text detector.
"""


def ensure_dirs():
    for folder in (GENERATED_DIR / "normal", GENERATED_DIR / "watermarked", EXPORT_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def read_readme():
    try:
        return README_PATH.read_text(encoding="utf-8-sig")
    except OSError:
        return ABOUT_FALLBACK


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def default_filename(mode):
    return "marktext_{}_{}.txt".format(mode, stamp())


def save_txt(info):
    """Write the text to generated/<mode>/ plus a <name>.json sidecar with the
    mode, seed and parameters it was generated with."""
    folder = GENERATED_DIR / info["mode"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / default_filename(info["mode"])
    path.write_text(info["text"], encoding="utf-8")
    record = {k: v for k, v in info.items() if k != "text"}
    record["saved_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record["text_file"] = path.name
    with open(path.with_suffix(".json"), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=4)
    return path


def load_history_df():
    """The history CSV as a DataFrame. history.py writes it row by row with
    the csv module; pandas only reads it here."""
    history.ensure_history()
    try:
        df = pd.read_csv(history.HISTORY_PATH, parse_dates=["timestamp"], encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=history.COLUMNS)
    for c in ("filename", "mode", "batch_id", "source", "note", "seeding_scheme"):
        df[c] = df[c].fillna("").astype(str)
    df["run_id"] = df["run_id"].astype(str)
    return df


def export_csv(df, stem):
    """Write a NEW csv under logs/exports/; the history file is never edited."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / "{}_{}.csv".format(stem, stamp())
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
    """Scatter of z against tokens scored, with a rule at the threshold. The
    verdicts are written as on the other pages ("Likely MarkText"), and each
    has a shape as well as a colour."""
    df = df.assign(result=df["result"].map(lambda r: charts.SHORT.get(r, r)))
    base = alt.Chart(df).mark_point(size=70, filled=True).encode(
        x=alt.X("tokens_scored:Q", title="tokens scored"),
        y=alt.Y("z_score:Q", title="z-score"),
        color=alt.Color("result:N", legend=charts.LEGEND),
        shape=alt.Shape("result:N", legend=charts.LEGEND),
        tooltip=["run_id", "source", "mode", "tokens_scored", "z_score", "result"])
    rule = alt.Chart(pd.DataFrame({"z": [threshold]})).mark_rule(
        strokeDash=[6, 4], color="#a33b3b").encode(y="z:Q")
    return (base + rule).properties(height=320).interactive()


# ---------------------------------------------------------------- callbacks
# Callbacks run before the rerun: the only moment a widget's value may be
# set through st.session_state.
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
        text = uploaded.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        state["upload_error"] = "{} is not valid UTF-8 text: {}".format(uploaded.name, exc)
        return
    state["detect_text"] = text
    state["detect_loaded"] = text.strip()
    state["detect_filename"] = uploaded.name
    state["detect_stats"] = None


def on_clear_detect():
    state = st.session_state
    for key, value in (("detect_text", ""), ("detect_loaded", ""), ("detect_filename", ""),
                       ("detect_stats", None), ("upload_error", "")):
        state[key] = value


def on_export(key, stem):
    state = st.session_state
    try:
        state["export_msg"] = "Exported to {}".format(export_csv(state[key], stem))
        state["export_error"] = ""
    except OSError as exc:
        state["export_msg"] = ""
        state["export_error"] = "Export failed: {}".format(exc)


LAB_DEFAULTS = (
    ("gen_text", ""), ("gen_mode", ""), ("gen_info", None), ("gen_saved", ""),
    ("gen_save_error", ""), ("detect_text", ""), ("detect_loaded", ""), ("detect_filename", ""),
    ("detect_stats", None), ("upload_error", ""), ("history_msg", ""), ("export_msg", ""),
    ("export_error", ""), ("export_rows", None), ("export_summary", None), ("exp_msg", ""),
    ("exp_batch", ""), ("exp_summary_export", None),
)


def init_state():
    for key, default in LAB_DEFAULTS:
        st.session_state.setdefault(key, default)
