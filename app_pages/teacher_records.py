"""Teacher: the records behind the classroom.

Activity: data/audit.csv, the append-only log of who did what (filters and
an export). File check: classroom/integrity.py reads every data file and
reports what does not agree, without changing anything. Backups: the copies
in data/backups/ taken before every rewrite; one can be put back after a
check, and the file it replaces is backed up first.
"""

import math

import pandas as pd
import streamlit as st

from classroom import audit, backups, integrity, store
from ui import common

user = common.require_role("teacher")
teacher = user["username"]
state = st.session_state
PER_PAGE = 20

st.title("Records", anchor=False)
st.caption("What happened, whether the files agree, and the copies kept before every change.")
activity_tab, check_tab, backups_tab = st.tabs([":material/history: Activity", ":material/fact_check: File check",
                                                ":material/settings_backup_restore: Backups"])


# ------------------------------------------------------------ callbacks
@common.safely
def run_check():
    state["integrity_findings"] = integrity.run(by=teacher)


@common.safely
def export_findings():
    path = integrity.export(state.get("integrity_findings") or [], by=teacher)
    common.flash("Findings saved to {}.".format(common.data_label(path)), ":material/download:")


@common.safely
def export_activity(rows):
    path = audit.export(rows, by=teacher)
    common.flash("Activity saved to {}.".format(common.data_label(path)), ":material/download:")


# ------------------------------------------------------------ activity
with activity_tab:
    rows = audit.read()
    if not rows:
        common.empty_state("Nothing recorded yet", "Sign-ins, hand-ins, scores and decisions appear "
                           "here as they happen.", "history")
    else:
        people = sorted({r["actor"] for r in rows if r["actor"]})
        actions = sorted({r["action"] for r in rows})
        with st.container(horizontal=True, vertical_alignment="bottom"):
            who = st.selectbox("Person", ["Everyone"] + people, key="activity_who")
            what = st.selectbox("Action", ["Everything"] + actions, key="activity_what",
                                format_func=lambda a: audit.ACTIONS.get(a, a))
        shown = [r for r in rows if (who == "Everyone" or r["actor"] == who)
                 and (what == "Everything" or r["action"] == what)]
        pages = max(1, math.ceil(len(shown) / PER_PAGE))
        if state.get("activity_page", 1) > pages:
            state["activity_page"] = 1
        table_slot = st.empty()
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption("{:,} of {:,} entries, newest first. The log is only ever appended to.".format(
                len(shown), len(rows)))
            current = st.pagination(pages, key="activity_page") if pages > 1 else 1
            st.download_button("Export", icon=":material/download:", key="activity_export",
                               data=store.csv_text(audit.COLUMNS, shown).encode("utf-8"),
                               file_name="activity.csv", mime="text/csv",
                               on_click=export_activity, args=(shown,),
                               help="Saves these entries under data/reports/ and downloads a copy.")
        start = (current - 1) * PER_PAGE
        view = pd.DataFrame(shown[start:start + PER_PAGE], columns=audit.COLUMNS)
        view["action"] = view["action"].map(lambda a: audit.ACTIONS.get(a, a))
        table_slot.dataframe(view, hide_index=True, column_config={
            "timestamp": st.column_config.TextColumn("When"),
            "actor": st.column_config.TextColumn("Who"),
            "action": st.column_config.TextColumn("What"),
            "target": st.column_config.TextColumn("On", help="The account, class, submission, review "
                                                            "or file the action was about."),
            "details": st.column_config.TextColumn("Details")})

# ------------------------------------------------------------ integrity
with check_tab:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.button("Check the files now", type="primary", icon=":material/fact_check:", key="check_run",
                  on_click=run_check,
                  help="Reads every data file and text; changes nothing. A few seconds.")
        findings = state.get("integrity_findings")
        if findings:
            st.download_button("Export findings", icon=":material/download:", key="check_export",
                               data=store.csv_text(integrity.FINDING_COLUMNS, findings).encode("utf-8"),
                               file_name="integrity.csv", mime="text/csv", on_click=export_findings)
    if findings is None:
        st.caption("Checks that every submission's text is on disk and unchanged (SHA-256), that "
                   "every sidecar, review, roster row and assignment points at something that exists, "
                   "that no file has unexpected columns, and that no half-written file was left behind.")
    else:
        counts = integrity.summary(findings)
        common.metric_row([("Errors", counts["error"], "Something is lost or wrong."),
                           ("Warnings", counts["warning"], "Worth a look."),
                           ("Notes", counts["info"], None)])
        table = pd.DataFrame(findings, columns=integrity.FINDING_COLUMNS)
        table["severity"] = table["severity"].map(lambda s: [s])
        st.dataframe(table, hide_index=True,
                     column_config={
                         "severity": st.column_config.MultiselectColumn(
                             "Severity", options=list(integrity.SEVERITIES), color=["red", "orange", "gray"]),
                         "file": st.column_config.TextColumn("File"),
                         "problem": st.column_config.TextColumn("Problem"),
                         "detail": st.column_config.TextColumn("Detail")},
                     key="check_table")

# ------------------------------------------------------------ backups
with backups_tab:
    copies = backups.listing()
    st.caption("A copy of a data file is taken before every change to it. The newest {} copies of "
               "each file are kept (classroom.keep_backups in the config).".format(store.KEEP_BACKUPS))
    if not copies:
        common.empty_state("No backup copies yet", "The first change to a data file makes one.",
                           "settings_backup_restore")
    else:
        files = ["Every file"] + list(backups.DATA_FILES)
        which = st.segmented_control("File", files, default="Every file", key="backup_file",
                                     required=True)
        listed = [c for c in copies if which in (None, "Every file") or c["file"] == which]
        st.dataframe(pd.DataFrame(listed), hide_index=True, column_config={
            "file": st.column_config.TextColumn("Data file"),
            "backup": st.column_config.TextColumn("Copy"),
            "taken_at": st.column_config.TextColumn("Taken"),
            "size_kb": st.column_config.NumberColumn("Size (KB)", format="%.1f")})
        with st.container(border=True):
            st.subheader("Put a copy back", icon=":material/settings_backup_restore:", anchor=False)
            pick = st.selectbox("Copy", [c["backup"] for c in listed], index=None,
                                placeholder="Choose a copy", key="backup_pick",
                                format_func=lambda b: "{} · {}".format(backups.taken_at(b), b))
            if pick:
                try:
                    name, records = backups.check_copy(pick)
                except ValueError as exc:
                    st.error(common.md(str(exc)), icon=":material/error:")
                else:
                    st.caption("This copy of {} holds {} record{} and passes the check.".format(
                        name, records, "" if records == 1 else "s"))
                    if name == "users.json":
                        st.warning("Putting back users.json also puts back the passwords as they were "
                                   "then.", icon=":material/key:")
                    st.button("Restore this copy", icon=":material/settings_backup_restore:",
                              key="backup_restore", on_click=common.open_dialog, args=("restore",),
                              kwargs={"copy": pick, "teacher": teacher})


@st.dialog("Restore a backup copy?", icon=":material/settings_backup_restore:",
           on_dismiss=common.close_dialog)
def restore_dialog(copy, teacher):
    name, records = backups.check_copy(copy)
    st.write("**data/{}** is replaced by the copy taken {}. The current file is backed up first, so "
             "this can be undone the same way.".format(name, backups.taken_at(copy)))
    with st.form("restore_form", border=False):
        with st.container(horizontal=True, horizontal_alignment="right"):
            cancel = st.form_submit_button("Cancel", key="restore_cancel")
            confirm = st.form_submit_button("Restore", type="primary", key="restore_confirm")
    if cancel:
        common.finish_dialog()
    if confirm:
        try:
            undo = backups.restore(copy, by=teacher)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            common.finish_dialog("Restored data/{}. The replaced file was saved as {}.".format(
                name, undo.name if undo else "nothing (there was no file)"),
                ":material/settings_backup_restore:")


common.render_dialogs({"restore": restore_dialog})
