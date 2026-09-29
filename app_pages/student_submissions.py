"""Student: everything you handed in, and what came back."""

import pandas as pd
import streamlit as st

from classroom import assignments, classes, reviews, submissions
from ui import common

user = common.require_role("student")
state = st.session_state
SOURCE_TEXT = {"editor": "Typed", "upload": "Uploaded", "assistant": "Assistant draft",
               "teacher": "Handed in by your teacher"}

st.title("My submissions", anchor=False)
mine = submissions.list_submissions(username=user["username"], current_only=False)
if not mine:
    common.empty_state("Nothing handed in yet", "Open an assignment from your home page to write "
                       "or upload your answer.", "inventory_2")
    st.stop()

tasks = {t["assignment_id"]: t for t in assignments.list_assignments()}
class_names = {c["class_id"]: c["name"] for c in classes.list_classes(include_archived=True)}
latest = reviews.latest_by_submission()

rows = []
for sub in mine:
    shown = reviews.shown_to_student(latest.get(sub["submission_id"]))
    rows.append({
        "submission_id": sub["submission_id"],
        "Assignment": tasks.get(sub["assignment_id"], {}).get("title", sub["assignment_id"]),
        "Class": class_names.get(sub["class_id"], ""),
        "Version": int(sub["version"]),
        "Handed in": common.when(sub["submitted_at"]),
        "How": SOURCE_TEXT.get(sub["source"], sub["source"]),
        "Words": int(sub["words"]),
        "Latest": sub["status"] == "current",
        "Teacher's decision": common.decision_text(shown["decision"]) if shown else "",
        "Points": "{:g} / {}".format(float(shown["points"]), tasks[sub["assignment_id"]]["points"])
                  if shown and shown.get("points") and tasks.get(sub["assignment_id"], {}).get("points") else "",
    })
table = pd.DataFrame(rows)

with st.container(border=True):
    st.dataframe(table.drop(columns=["submission_id"]), hide_index=True, column_config={
        "Version": st.column_config.NumberColumn(format="%d"),
        "Words": st.column_config.NumberColumn(format="%d"),
        "Latest": st.column_config.CheckboxColumn(help="The version your teacher reviews."),
    })

with st.container(border=True):
    labels = {r["submission_id"]: "{} · version {} · {}".format(r["Assignment"], r["Version"], r["Handed in"])
              for r in rows}
    where = {r["submission_id"]: r["Class"] for r in rows}
    chosen = common.choose("Open a submission", list(labels), "open_submission_id", labels.get,
                           detail=where.get)
    sub = submissions.get_submission(chosen)
    shown = reviews.shown_to_student(latest.get(chosen))
    if shown:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown("**Your teacher's decision**")
            common.decision_badge(shown["decision"])
        if shown["note"]:
            st.markdown(common.plain(shown["note"]))
    elif sub["status"] == "current":
        st.caption("Your teacher has not returned this version yet.")
    else:
        st.caption("A later version replaced this one.")
    if sub["version_note"]:
        st.caption("Your note: {}".format(common.md(sub["version_note"])))
    with st.container(height=300, border=True):
        text = common.submission_text(sub)
        if text is not None:
            st.markdown(common.plain(text))
