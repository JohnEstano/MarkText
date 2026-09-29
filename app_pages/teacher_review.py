"""Teacher: review one assignment, student by student.

Scoring a submission reads its text file, runs the detector and writes two
files: a row in logs/detection_history.csv (source "submission") and a row
in data/reviews.csv with the numbers and room for a decision. Saving a
decision or returning the work is a backed-up rewrite of that review row.
The report export writes a new CSV under data/reports/.
"""

import math

import pandas as pd
import streamlit as st

import config as cfg
from classroom import assignments, classes, detection, reports, reviews, store, submissions
from ui import common, dialogs

user = common.require_role("teacher")
teacher = user["username"]
state = st.session_state
PER_PAGE = 15
SOURCE_TEXT = {"editor": "Typed in the editor", "upload": "Uploaded", "assistant": "Drafted with the assistant"}

st.title("Review")
mine = classes.list_classes(teacher)
if not mine:
    common.empty_state("Nothing to review yet", "Create a class and an assignment first; "
                       "submissions appear here as students hand them in.", "fact_check")
    st.stop()

names = {c["class_id"]: c["name"] for c in mine}
pick_class, pick_task = st.columns(2)
with pick_class:
    class_id = common.choose("Class", list(names), "review_class", names.get)
tasks = assignments.list_assignments(class_id)
titles = {t["assignment_id"]: t["title"] for t in tasks}
with pick_task:
    if titles:
        assignment_id = common.choose("Assignment", list(titles), "review_assignment", titles.get)
    else:
        st.selectbox("Assignment", ["No assignments yet"], disabled=True, key="review_no_task")
if not titles:
    common.empty_state("This class has no assignments", "Create one on the Classes page.", "assignment")
    st.stop()
task = assignments.get_assignment(assignment_id)


# ------------------------------------------------------------ callbacks
def request_scoring(what):
    state["run_detect"] = {"assignment_id": assignment_id, "what": what}


def save_decision(review_id):
    decision = state.get("decision_" + review_id)
    try:
        reviews.decide(review_id, decision or "pending", state.get("note_" + review_id, ""), teacher)
    except ValueError as exc:
        common.flash(str(exc), ":material/error:")
    else:
        common.flash("Decision saved: {}.".format(common.decision_text(decision)), ":material/task_alt:")


def export_report():
    path = reports.export_assignment_report(assignment_id)
    common.flash("Report saved to {}.".format(common.data_label(path)), ":material/download:")


def on_table_pick():
    try:
        rows = list(state["review_table"]["selection"]["rows"])
    except (KeyError, TypeError):
        rows = []
    shown = state.get("_review_rows", [])
    if rows and rows[0] < len(shown):
        state["review_pick"] = shown[rows[0]]


# ------------------------------------------------- scoring, before drawing
request = state.get("run_detect")
if request and request["assignment_id"] == assignment_id:
    state["run_detect"] = None
    todo = (detection.pending(assignment_id) if request["what"] == "all"
            else [s for s in [submissions.get_submission(request["what"])] if s])
    if todo:
        engine, lock = common.engine()
        with st.status("Scoring {} submission{}...".format(len(todo), "" if len(todo) == 1 else "s"),
                       expanded=True) as status:
            st.button("Stop after this one", icon=":material/stop_circle:", key="detect_stop",
                      help="Submissions already scored keep their results.")
            bar = st.progress(0.0)

            def progress(done, total, review):
                bar.progress(done / total, text="{}/{}  {}: {}".format(
                    done, total, common.display_name(review["username"]),
                    common.verdict_text(review["label"])))
            written = detection.detect_many(engine, lock, todo, teacher, on_progress=progress)
            status.update(label="Scored {} submission{}".format(len(written), "" if len(written) == 1 else "s"),
                          state="complete", expanded=False)

frame = reports.assignment_frame(assignment_id)
counts = reports.state_counts(frame)

# ------------------------------------------------------------ assignment
with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="center"):
        with st.container():
            st.subheader(task["title"])
            due = "Due {}".format(common.day(task["due_at"])) if task["due_at"] else "No due date"
            st.caption("{} · {}".format(names[class_id], due))
        if task["status"] == "open":
            st.badge("Open", color="green")
        else:
            st.badge("Closed", color="gray", icon=":material/lock:")
    if task["instructions"]:
        with st.expander("Instructions", icon=":material/description:"):
            st.markdown(common.plain(task["instructions"]))

common.metric_row([
    ("Students", len(frame), None),
    ("Handed in", len(frame) - counts["not submitted"], None),
    ("Not scored", counts["awaiting detection"], "Handed in, not yet checked for the watermark."),
    ("To decide", counts["awaiting decision"], "Scored, no decision yet."),
    ("Returned", counts["returned"], "The student can see your decision and note."),
])

with st.container(horizontal=True, vertical_alignment="center"):
    pending = counts["awaiting detection"]
    st.button("Score all not scored ({})".format(pending), type="primary", icon=":material/fact_check:",
              key="score_all", disabled=pending == 0, on_click=request_scoring, args=("all",),
              help="Runs the watermark detector on every submission that has no score yet.")
    st.download_button("Export report", icon=":material/download:",
                       data=store.csv_text(reports.REPORT_COLUMNS,
                                           reports.assignment_report_rows(assignment_id)).encode("utf-8"),
                       file_name="assignment_{}.csv".format(assignment_id), mime="text/csv",
                       on_click=export_report, key="export_report",
                       help="Saves the table under data/reports/ and downloads a copy.")

# ------------------------------------------------------------ students
if len(frame) == 0:
    common.empty_state("No students in this class", "Share the join code {} or import a roster on "
                       "the Classes page.".format(classes.format_code(classes.get_class(class_id)["join_code"])),
                       "group_add")
    st.stop()

usernames = list(frame["username"])
if state.get("review_pick") not in usernames:
    waiting = frame[frame["state"].isin(["awaiting decision", "awaiting detection"])]
    state["review_pick"] = (waiting["username"].iloc[0] if len(waiting) else usernames[0])

table_col, detail_col = st.columns([3, 2], gap="large")
with table_col:
    with st.container(border=True):
        st.subheader("Students")
        view = pd.DataFrame({
            "Student": frame["display_name"],
            "Status": frame["state"].map(lambda s: [s]),
            "Version": frame["version"],
            "Handed in": frame["submitted_at"].map(common.when),
            "Words": frame["words"],
            "z": frame["z_score"],
            "Green %": frame["green_pct"],
            "Detector": frame["label"].map(lambda l: common.verdict_text(l) if l else ""),
            "Decision": frame["decision"].map(lambda d: common.decision_text(d) if d != "pending" else ""),
        })
        pages = max(1, math.ceil(len(view) / PER_PAGE))
        if state.get("review_page", 1) > pages:
            state["review_page"] = 1
        slot = st.empty()
        if pages > 1:
            with st.container(horizontal_alignment="right"):
                current_page = st.pagination(pages, key="review_page")
        else:
            current_page = 1
        start = (current_page - 1) * PER_PAGE
        state["_review_rows"] = usernames[start:start + PER_PAGE]
        slot.dataframe(view.iloc[start:start + PER_PAGE], hide_index=True, key="review_table",
                       on_select=on_table_pick, selection_mode="single-row", column_config={
                           "Status": st.column_config.MultiselectColumn(
                               "Status", options=common.STATE_ORDER, color=common.STATE_COLOURS,
                               format_func=lambda s: common.STATE_BADGE[s][0]),
                           "Version": st.column_config.NumberColumn(format="%d"),
                           "Words": st.column_config.NumberColumn(format="%d"),
                           "z": st.column_config.NumberColumn(format="%.2f", help="z-score: how far the "
                                                              "green share sits above chance."),
                           "Green %": st.column_config.ProgressColumn(min_value=0, max_value=100,
                                                                     format="%.1f"),
                       })
        st.caption("Select a row, or pick the student on the right.")

with detail_col:
    with st.container(border=True):
        labels = dict(zip(frame["username"], frame["display_name"]))
        states = dict(zip(frame["username"], frame["state"]))
        username = common.choose("Student", usernames, "review_pick",
                                 lambda u: "{} · {}".format(labels[u], common.STATE_BADGE[states[u]][0]))
        common.state_badge(states[username])
        sub = submissions.current_submission(assignment_id, username)
        if sub is None:
            st.caption("Nothing handed in yet.")
        else:
            side = submissions.sidecar(sub) or {}
            how = SOURCE_TEXT.get(sub["source"], sub["source"])
            if sub["source"] == "upload" and sub["upload_filename"]:
                how += " as {}".format(sub["upload_filename"])
            gen = side.get("generation")
            if gen:
                how += " (seed {}, {} tokens)".format(gen.get("seed"), gen.get("new_tokens"))
            st.caption("Version {} · {} · {} words · {}".format(
                sub["version"], common.when(sub["submitted_at"]), sub["words"], how))
            if sub["version_note"]:
                st.caption("Student's note: {}".format(sub["version_note"]))
            with st.container(height=300, border=True):
                st.markdown(common.plain(submissions.read_text(sub)))

            review = reviews.latest_review(sub["submission_id"])
            if review is None:
                st.button("Score this submission", type="primary", icon=":material/fact_check:",
                          key="score_one", on_click=request_scoring, args=(sub["submission_id"],))
            else:
                rid = review["review_id"]
                with st.container(horizontal=True, vertical_alignment="center"):
                    common.verdict_badge(review["label"])
                    st.caption("Scored {} with {}, key {}".format(
                        common.when(review["detected_at"]), review["model_id"], review["key_id"] or "?"))
                with st.container(horizontal=True):
                    st.metric("Tokens", review["tokens_scored"], border=True)
                    st.metric("Green", "{}%".format(review["green_pct"]), border=True,
                              help="Chance level is 50%.")
                    st.metric("z", review["z_score"], border=True)
                current_key = cfg.public_watermark(common.load_config()).get("key_id")
                if review["key_id"] and current_key and review["key_id"] != current_key:
                    st.warning("Scored with another key ({}); the current key is {}. Score it again "
                               "to use the current one.".format(review["key_id"], current_key),
                               icon=":material/key:")
                    st.button("Score again", key="score_again", on_click=request_scoring,
                              args=(sub["submission_id"],))

                st.segmented_control("Decision", ["accepted", "flagged", "needs_review"],
                                     format_func=common.decision_text, key="decision_" + rid,
                                     default=review["decision"] if review["decision"] != "pending" else None)
                st.text_area("Note to the student", value=review["note"], key="note_" + rid, height=90,
                             placeholder="Explain your decision in a sentence or two.")
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.button("Save decision", key="save_" + rid, on_click=save_decision, args=(rid,))
                    if review["returned"] == "1":
                        st.badge("Returned {}".format(common.when(review["returned_at"])), color="green",
                                 icon=":material/done_all:")
                    elif review["decision"] != "pending":
                        st.button("Return to student", type="primary", icon=":material/assignment_return:",
                                  key="return_" + rid, on_click=common.open_dialog, args=("return_work",),
                                  kwargs={"review_id": rid, "teacher": teacher})
                    else:
                        st.caption("Save a decision to return the work.")

            older = submissions.versions(assignment_id, username)[:-1]
            if older:
                with st.expander("Earlier versions ({})".format(len(older)), icon=":material/history:"):
                    for version in reversed(older):
                        st.markdown("**Version {}** · {} · {} words".format(
                            version["version"], common.when(version["submitted_at"]), version["words"]))
                        if version["version_note"]:
                            st.caption(version["version_note"])
                        with st.popover("Show text", key="old_" + version["submission_id"]):
                            st.markdown(common.plain(submissions.read_text(version)))

common.render_dialogs({"return_work": dialogs.return_work})
