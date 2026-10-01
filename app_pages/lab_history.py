"""Lab: the detection history (logs/detection_history.csv).

Reads the CSV with pandas for filters, charts and summaries, and writes only
NEW files under logs/exports/. Editing or deleting one record, or clearing
the whole log, goes through history.py, which backs the file up first.
"""

import math

import pandas as pd
import streamlit as st

import history
from ui import common, lab

common.require_role("teacher")
state = st.session_state
config = common.load_config()
PER_PAGE = 25


@st.dialog("Delete this record?", icon=":material/delete:", on_dismiss=common.close_dialog)
def delete_record_dialog(run_id):
    st.write("Record **{}** will be removed from the history. A backup copy of the whole file is "
             "written to logs/exports/ first.".format(run_id))
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Cancel", key="delete_cancel"):
            common.finish_dialog()
        if st.button("Delete record", type="primary", key="delete_confirm"):
            try:
                backup = history.delete_record(run_id)
            except (ValueError, OSError) as exc:
                st.error(str(exc), icon=":material/error:")
            else:
                state["manage_id"] = ""
                common.finish_dialog("Record deleted. Backup: {}".format(backup.name),
                                     ":material/delete:")


@st.dialog("Clear the whole history?", icon=":material/delete_sweep:", on_dismiss=common.close_dialog)
def clear_history_dialog():
    st.write("Every detection record will be removed, including classroom detections. The "
             "teacher's reviews keep their own copy of the numbers, so no classroom decision is "
             "lost. A backup copy of the file is written to logs/exports/ first.")
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Cancel", key="clear_cancel"):
            common.finish_dialog()
        if st.button("Clear history", type="primary", key="clear_confirm"):
            try:
                backup = history.clear_history()
            except OSError as exc:
                st.error(str(exc), icon=":material/error:")
            else:
                common.finish_dialog("History cleared. Backup: {}".format(backup.name),
                                     ":material/delete_sweep:")


def on_update_record():
    rid = state.get("manage_id", "").strip()
    try:
        backup = history.update_record(rid, note=state.get("manage_note", ""),
                                       filename=state.get("manage_filename", ""))
        common.flash("Record {} updated. Backup: {}".format(rid, backup.name))
    except (ValueError, OSError) as exc:
        common.fail("manage_record", "Record not updated: {}".format(exc))


st.title("History", anchor=False)
st.caption("Every analysis, one row each, from the lab and from classroom reviews.")
if state["export_msg"]:
    st.success(state["export_msg"], icon=":material/check_circle:")
    state["export_msg"] = ""
if state["export_error"]:
    st.error(state["export_error"], icon=":material/error:")
    state["export_error"] = ""

try:
    df = lab.load_history_df()
except (OSError, pd.errors.ParserError, UnicodeDecodeError) as exc:
    df = pd.DataFrame(columns=history.COLUMNS)
    st.error("Could not read the history CSV: {}".format(exc), icon=":material/error:")

if df.empty:
    common.empty_state("No detections yet", "Analyze a text on the Detect page, score a "
                       "submission on the Review page, or run an experiment.", "history")
    st.stop()

with st.container(border=True):
    f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
    results = sorted(df["result"].unique())
    pick = f1.multiselect("Result", results, default=results, key="hist_results")
    query = f2.text_input("Filename contains", "", key="hist_query")
    dmin, dmax = df["timestamp"].min().date(), df["timestamp"].max().date()
    dates = f3.date_input("Date range", (dmin, dmax), min_value=dmin, max_value=dmax, key="hist_dates")
    min_tok = f4.number_input("Min tokens", 0, int(df["tokens_scored"].max()), 0, step=10,
                              key="hist_min_tokens")
    g1, g2 = st.columns(2)
    sources = sorted(df["source"].unique())
    pick_src = g1.pills("Source", sources, default=sources, selection_mode="multi", key="hist_sources")
    batches = ["(all)"] + sorted(b for b in df["batch_id"].unique() if b)
    pick_batch = g2.selectbox("Batch", batches, key="hist_batch")

mask = df["result"].isin(pick) & df["source"].isin(pick_src or [])
if pick_batch != "(all)":
    mask &= df["batch_id"] == pick_batch
if query:
    mask &= df["filename"].str.contains(query, case=False, na=False, regex=False)
if isinstance(dates, tuple) and len(dates) == 2:
    mask &= df["timestamp"].dt.date.between(dates[0], dates[1])
mask &= df["tokens_scored"] >= min_tok
filtered = df[mask]

common.metric_row([
    ("Analyses in view", "{:,}".format(len(filtered)), "of {:,} in the file".format(len(df))),
    ("Mean z-score", "{:.2f}".format(filtered["z_score"].mean()) if len(filtered) else "–", None),
    ("Likely MarkText", "{:.0%}".format((filtered["result"] == "LIKELY MARKTEXT").mean())
     if len(filtered) else "–", "Share of rows at or above the detection threshold."),
    ("Median tokens", int(filtered["tokens_scored"].median()) if len(filtered) else "–", None),
])

if filtered.empty:
    common.empty_state("No records match the filters", "Widen the date range or pick more "
                       "results and sources.", "filter_alt_off")
else:
    left, right = st.columns([3, 2], gap="large")
    with left:
        with st.container(border=True):
            st.subheader("z-score against tokens scored", anchor=False)
            st.altair_chart(lab.z_chart(filtered, float(config["detection_threshold"])))
            st.caption("Dashed line: the detection threshold, z = {}.".format(
                config["detection_threshold"]))
    has_modes = (filtered["mode"] != "").any()
    summary = lab.summarise(filtered, ("mode", "result") if has_modes else ("result",))
    with right:
        with st.container(border=True):
            st.subheader("Summary by {}result".format("mode and " if has_modes else ""), anchor=False)
            st.dataframe(summary, hide_index=True, column_config={
                "mean_z": st.column_config.NumberColumn("mean z", format="%.2f"),
                "mean_green_pct": st.column_config.NumberColumn("mean green %", format="%.1f"),
                "mean_tokens": st.column_config.NumberColumn("mean tokens", format="%.0f")})
            state["export_summary"] = summary
            st.download_button("Export summary", data=summary.to_csv(index=False).encode("utf-8"),
                               file_name="history_summary.csv", mime="text/csv",
                               on_click=lab.on_export, args=("export_summary", "history_summary"),
                               icon=":material/download:", key="hist_export_summary")

    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.subheader("Records", anchor=False)
            state["export_rows"] = filtered
            st.download_button("Export filtered rows", data=filtered.to_csv(index=False).encode("utf-8"),
                               file_name="history_filtered.csv", mime="text/csv",
                               on_click=lab.on_export, args=("export_rows", "history_filtered"),
                               icon=":material/download:", key="hist_export_rows")
        ordered = filtered.sort_values("timestamp", ascending=False)
        pages = max(1, math.ceil(len(ordered) / PER_PAGE))
        if state.get("history_page", 1) > pages:
            state["history_page"] = 1
        table_slot = st.empty()
        with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
            st.caption("{:,} records".format(len(ordered)))
            current = st.pagination(pages, key="history_page")
        start = (current - 1) * PER_PAGE
        table_slot.dataframe(ordered.iloc[start:start + PER_PAGE], hide_index=True, placeholder="",
                         column_config={
            "timestamp": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
            "green_pct": st.column_config.NumberColumn("green %", format="%.2f"),
            "z_score": st.column_config.NumberColumn("z", format="%.2f"),
            "p_value": st.column_config.NumberColumn(format="%.2e"),
            "repeated": st.column_config.NumberColumn(format="%d", help="Repeated n-grams, counted once"),
            "passage_z": st.column_config.NumberColumn("passage z", format="%.2f",
                                                       help="z of the strongest 150-token passage"),
            "passage_p": st.column_config.NumberColumn("passage p", format="%.2e",
                                                       help="Its p-value, corrected for every passage tried")})

with st.expander("Manage one record by its run id", icon=":material/edit:"):
    rid = st.text_input("Run id", key="manage_id", placeholder="843167dd").strip()
    record = history.find_record(rid) if rid else None
    if rid and record is None:
        st.warning("No record has the run id {}.".format(rid), icon=":material/search_off:")
    if record:
        st.dataframe(pd.DataFrame([record]), hide_index=True)
        st.text_input("Filename", value=record.get("filename", ""), key="manage_filename")
        st.text_input("Note", value=record.get("note", ""), key="manage_note")
        st.caption("Only the note and the filename can change; measurements cannot. A backup is "
                   "written before any change.")
        with st.container(horizontal=True):
            st.button("Save changes", on_click=on_update_record, key="manage_save")
            st.button("Delete record", icon=":material/delete:", key="manage_delete",
                      on_click=common.open_dialog, args=("delete_record",), kwargs={"run_id": rid})
    common.error_here("manage_record")

with st.container(horizontal=True, vertical_alignment="center"):
    st.caption("{:,} analyses in {}. Writes go through history.py (csv module); this page reads "
               "with pandas and writes only new files.".format(len(df), history.HISTORY_PATH.name))
    st.button("Clear history", icon=":material/delete_sweep:", key="clear_history",
              on_click=common.open_dialog, args=("clear_history",))

common.render_dialogs({"delete_record": delete_record_dialog, "clear_history": clear_history_dialog})
