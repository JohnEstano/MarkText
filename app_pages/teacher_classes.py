"""Teacher: classes, their rosters and their assignments.

File handling on this page: the roster import reads an uploaded CSV and
writes data/rosters.csv (one backed-up rewrite); the exports write new CSV
files under data/reports/ and download the same bytes; removing a student
or closing an assignment is a backed-up rewrite of one row.
"""

import pandas as pd
import streamlit as st

from classroom import archive, assignments, classes, reports, reviews, store, submissions
from ui import common, dialogs

user = common.require_role("teacher")
teacher = user["username"]
state = st.session_state

mine = classes.list_classes(teacher)
archived = [c for c in classes.list_classes(teacher, include_archived=True) if c.get("archived")]
by_id = {c["class_id"]: c for c in mine}
if state["open_class_id"] not in by_id:
    state["open_class_id"] = None


def open_class(class_id):
    state["open_class_id"] = class_id


@common.safely
def restore(class_id):
    classes.set_archived(class_id, False, by=teacher)
    common.flash("Class restored.", ":material/unarchive:")


def import_roster(class_id):
    uploaded = state.get("roster_upload_" + class_id)
    if uploaded is None:
        common.flash("Choose a CSV file first.", ":material/error:")
        return
    try:
        result = classes.import_roster(class_id, classes.parse_roster_csv(uploaded.getvalue()), by=teacher)
    except ValueError as exc:
        common.flash(str(exc), ":material/error:")
        return
    state["import_report"] = {"class_id": class_id, "file": uploaded.name, **result}
    common.flash("{} enrolled, {} invited, {} skipped.".format(
        len(result["enrolled"]), len(result["invited"]), len(result["skipped"])), ":material/group_add:")


@common.safely
def export_roster(class_id):
    path = classes.export_roster(class_id, by=teacher)
    common.flash("Roster saved to {}.".format(common.data_label(path)), ":material/download:")


@common.safely
def export_summary(class_id):
    path = reports.export_class_summary(class_id, by=teacher)
    common.flash("Summary saved to {}.".format(common.data_label(path)), ":material/download:")


@common.safely
def set_status(assignment_id, status):
    assignments.update_assignment(assignment_id, by=teacher, status=status)
    common.flash("Assignment {}.".format("closed" if status == "closed" else "reopened"),
                 ":material/lock:" if status == "closed" else ":material/lock_open:")


# ----------------------------------------------------------- all classes
current = by_id.get(state["open_class_id"])
if current is None:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.title("Classes", anchor=False)
        st.button("New class", type="primary", icon=":material/add:", on_click=common.open_dialog,
                  args=("create_class",), kwargs={"teacher": teacher}, key="classes_new")
    if not mine:
        common.empty_state("No classes yet", "Create a class, then share its join code with your "
                           "students or import a roster.", "school")
    counts = classes.student_counts()
    open_tasks = {}
    for task in assignments.list_assignments(status="open"):
        open_tasks[task["class_id"]] = open_tasks.get(task["class_id"], 0) + 1
    for start in range(0, len(mine), 3):
        for column, record in zip(st.columns(3), mine[start:start + 3]):
            with column.container(border=True):
                st.subheader(common.md(record["name"]), anchor=False)
                st.caption(common.md(record["term"]) or "No term set")
                st.caption("Join code")
                st.code(classes.format_code(record["join_code"]), language=None)
                st.markdown(":material/group: {} students  ·  :material/assignment: {} open".format(
                    counts.get(record["class_id"], 0), open_tasks.get(record["class_id"], 0)))
                st.button("Open", icon=":material/arrow_forward:", key="open_" + record["class_id"],
                          on_click=open_class, args=(record["class_id"],), width="stretch")
    if archived:
        with st.expander("Archived classes ({})".format(len(archived)), icon=":material/archive:"):
            for record in archived:
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.markdown("**{}** · {}".format(common.md(record["name"]), common.md(record["term"]) or "no term"))
                    st.button("Restore", key="restore_" + record["class_id"], on_click=restore,
                              args=(record["class_id"],), icon=":material/unarchive:")
    common.render_dialogs({"create_class": dialogs.create_class})
    st.stop()

# ----------------------------------------------------------- one class
cid = current["class_id"]
st.button("All classes", icon=":material/arrow_back:", type="tertiary", on_click=open_class,
          args=(None,), key="classes_back")
with st.container(horizontal=True, vertical_alignment="bottom"):
    with st.container():
        st.title(common.md(current["name"]), anchor=False)
        st.caption(common.md(current["term"]) or "No term set")
    with st.container(width="content"):
        st.caption("Join code")
        st.code(classes.format_code(current["join_code"]), language=None)
    st.button("Rename", icon=":material/edit:", key="class_rename", on_click=common.open_dialog,
              args=("rename_class",), kwargs={"class_id": cid, "teacher": teacher})
    st.button("New code", icon=":material/key:", key="class_rotate", on_click=common.open_dialog,
              args=("rotate_code",), kwargs={"class_id": cid, "teacher": teacher})
    st.button("Archive", icon=":material/archive:", key="class_archive", on_click=common.open_dialog,
              args=("archive_class",), kwargs={"class_id": cid, "teacher": teacher})
    # built only when clicked (a callable): the zip reads every text of the class
    st.download_button("Export class", icon=":material/folder_zip:", key="class_zip_" + cid,
                       data=lambda: archive.export_class(cid, by=teacher).read_bytes(),
                       file_name="class_{}.zip".format(cid), mime="application/zip",
                       help="Roster, assignments, every version handed in, reviews and the summary "
                            "in one zip; a copy stays under data/reports/.")

roster_tab, tasks_tab, summary_tab = st.tabs([":material/group: Roster", ":material/assignment: Assignments",
                                              ":material/table_chart: Summary"])

with roster_tab:
    rows = classes.export_rows(cid)
    present = [r for r in rows if r["status"] != "removed"]
    removed = [r for r in rows if r["status"] == "removed"]
    with st.container(horizontal=True, vertical_alignment="center"):
        st.subheader("{} students".format(sum(r["status"] == "active" for r in rows)), anchor=False)
        with st.popover("Import roster", icon=":material/upload_file:"):
            st.markdown("Upload a CSV file with a **username** column, one student per row. "
                        "Registered students are enrolled; other usernames are invited and join "
                        "when they register.")
            st.file_uploader("Roster CSV", type=["csv"], key="roster_upload_" + cid)
            st.button("Import", type="primary", key="roster_import_" + cid, on_click=import_roster,
                      args=(cid,))
        st.download_button("Export roster", icon=":material/download:",
                           data=store.csv_text(classes.EXPORT_COLUMNS, rows).encode("utf-8"),
                           file_name="roster_{}.csv".format(cid), mime="text/csv",
                           on_click=export_roster, args=(cid,), key="roster_export_" + cid)
    report = state.get("import_report")
    if report and report.get("class_id") == cid and report["skipped"]:
        with st.expander("Skipped in {} ({})".format(common.md(report["file"]), len(report["skipped"])),
                         icon=":material/info:", expanded=True):
            st.dataframe(pd.DataFrame(report["skipped"], columns=["username", "reason"]), hide_index=True)
    if not present:
        common.empty_state("Nobody here yet", "Students join with the code {}, or import a roster "
                           "file.".format(classes.format_code(current["join_code"])), "group_add")
    else:
        table = pd.DataFrame(present)[["display_name", "username", "status", "added_via", "joined_at"]]
        table["status"] = table["status"].map(lambda s: [s])
        st.dataframe(table, hide_index=True, column_config={
            "display_name": st.column_config.TextColumn("Name"),
            "username": st.column_config.TextColumn("Username"),
            "status": st.column_config.MultiselectColumn("Status", options=["active", "invited"],
                                                         color=["green", "blue"]),
            "added_via": st.column_config.TextColumn("Added by", help="code: joined with the class "
                                                     "code; import: added from a roster file"),
            "joined_at": st.column_config.TextColumn("Joined")})
        with st.container(horizontal=True, vertical_alignment="bottom"):
            leaving = st.selectbox("Remove a student", [r["username"] for r in present], index=None,
                                   placeholder="Choose a student",
                                   format_func=lambda u: "{} ({})".format(common.display_name(u), u),
                                   key="remove_pick_" + cid)
            st.button("Remove", icon=":material/person_remove:", key="remove_" + cid,
                      disabled=leaving is None, on_click=common.open_dialog, args=("remove_student",),
                      kwargs={"class_id": cid, "username": leaving, "teacher": teacher})
            st.button("Reset password", icon=":material/lock_reset:", key="reset_" + cid,
                      disabled=leaving is None or not classes.is_member(cid, leaving or ""),
                      on_click=common.open_dialog, args=("reset_password",),
                      kwargs={"class_id": cid, "username": leaving, "teacher": teacher},
                      help="Gives the student a temporary password; they choose their own at the "
                           "next sign-in.")
        # one student's work across the class, every version
        active = [r["username"] for r in present if r["status"] == "active"]
        if active:
            with st.expander("One student's work", icon=":material/person_search:"):
                who = st.selectbox("Student", active, index=None, placeholder="Choose a student",
                                   format_func=lambda u: "{} ({})".format(common.display_name(u), u),
                                   key="history_pick_" + cid)
                if who:
                    titles = {t["assignment_id"]: t["title"] for t in assignments.list_assignments(cid)}
                    latest = reviews.latest_by_submission()
                    history = []
                    for sub in reversed(submissions.list_submissions(username=who, class_id=cid,
                                                                     current_only=False)):
                        review = latest.get(sub["submission_id"])
                        history.append({
                            "Assignment": titles.get(sub["assignment_id"], sub["assignment_id"]),
                            "Version": int(sub["version"]), "Handed in": common.when(sub["submitted_at"]),
                            "How": sub["source"], "Words": int(sub["words"]),
                            "Detector": common.verdict_text(review["label"]) if review else "Not scored",
                            "Decision": common.decision_text(review["decision"])
                            if review and review["decision"] != "pending" else "",
                            "Returned": bool(review and review["returned"] == "1"),
                            "Current": sub["status"] == "current"})
                    if history:
                        st.dataframe(pd.DataFrame(history), hide_index=True, column_config={
                            "Version": st.column_config.NumberColumn(format="%d", width="small"),
                            "Words": st.column_config.NumberColumn(format="%d", width="small")})
                    else:
                        st.caption("Nothing handed in yet.")
    if removed:
        with st.expander("Removed ({})".format(len(removed)), icon=":material/person_off:"):
            st.dataframe(pd.DataFrame(removed)[["display_name", "username", "removed_at"]],
                         hide_index=True)

with tasks_tab:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.subheader("Assignments", anchor=False)
        st.button("New assignment", type="primary", icon=":material/add:", key="task_new_" + cid,
                  on_click=common.open_dialog, args=("create_assignment",),
                  kwargs={"class_id": cid, "teacher": teacher})
    tasks = assignments.list_assignments(cid)
    if not tasks:
        common.empty_state("No assignments yet", "Create one; students in the class see it on their "
                           "home page right away.", "assignment")
    for task in tasks:
        counts = reports.state_counts(reports.assignment_frame(task["assignment_id"]))
        students = sum(counts.values())
        handed_in = students - counts["not submitted"]
        scored = counts["awaiting decision"] + counts["decided"] + counts["returned"]
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            with st.container():
                st.markdown("**{}**".format(common.md(task["title"])))
                due = "Due {}".format(common.day(task["due_at"])) if task["due_at"] else "No due date"
                if assignments.is_overdue(task) and task["status"] == "open":
                    due += " (past due)"
                st.caption("{} · created {}".format(due, common.when(task["created_at"])))
            st.badge("{}/{} handed in".format(handed_in, students), color="blue",
                     icon=":material/assignment_turned_in:")
            st.badge("{} scored".format(scored), color="orange", icon=":material/fact_check:")
            st.badge("{} returned".format(counts["returned"]), color="green", icon=":material/done_all:")
            if task.get("points"):
                st.badge("{} points".format(task["points"]), color="gray", icon=":material/grade:")
            if task["status"] == "open":
                st.badge("Open", color="green")
            else:
                st.badge("Closed", color="gray", icon=":material/lock:")
            st.button("Review", type="primary", key="review_" + task["assignment_id"],
                      on_click=common.open_review, args=(cid, task["assignment_id"]))
            st.button("Edit", key="edit_" + task["assignment_id"], icon=":material/edit:",
                      on_click=common.open_dialog, args=("edit_assignment",),
                      kwargs={"assignment_id": task["assignment_id"], "teacher": teacher})
            if task["status"] == "open":
                st.button("Close", key="close_" + task["assignment_id"], on_click=set_status,
                          args=(task["assignment_id"], "closed"),
                          help="Stops new submissions; nothing is deleted.")
            else:
                st.button("Reopen", key="reopen_" + task["assignment_id"], on_click=set_status,
                          args=(task["assignment_id"], "open"))

with summary_tab:
    summary = reports.class_summary(cid)
    with st.container(horizontal=True, vertical_alignment="center"):
        st.subheader("Summary", anchor=False)
        st.download_button("Export summary", icon=":material/download:",
                           data=store.csv_text(reports.SUMMARY_COLUMNS,
                                               reports.class_summary_rows(cid)).encode("utf-8"),
                           file_name="class_{}_summary.csv".format(cid), mime="text/csv",
                           on_click=export_summary, args=(cid,), key="summary_export_" + cid,
                           disabled=summary.empty)
    if summary.empty:
        st.caption("The summary fills in as assignments are created and scored.")
    else:
        st.dataframe(summary.drop(columns=["assignment_id"]), hide_index=True, column_config={
            "title": st.column_config.TextColumn("Assignment"),
            "due_at": st.column_config.TextColumn("Due"),
            "mean_z": st.column_config.NumberColumn("mean z", format="%.2f"),
            "not_detected": st.column_config.NumberColumn("not detected"),
            "needs_review": st.column_config.NumberColumn("needs review")})
        st.caption("likely / possible / not detected / inconclusive count the detector's verdicts; "
                   "accepted / flagged / needs review count your decisions.")

common.render_dialogs({"create_class": dialogs.create_class,
                       "create_assignment": dialogs.create_assignment,
                       "edit_assignment": dialogs.edit_assignment,
                       "reset_password": dialogs.reset_password,
                       "rename_class": dialogs.rename_class,
                       "rotate_code": dialogs.rotate_code,
                       "archive_class": dialogs.archive_class,
                       "remove_student": dialogs.remove_student})
