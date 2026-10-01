"""Dialogs shared by the teacher pages. Each is opened with
common.open_dialog(name, **context) and drawn by common.render_dialogs()
at the end of the page; each closes itself with common.finish_dialog()."""

import datetime

import streamlit as st

from classroom import assignments, classes, reviews, store
from ui import common


def _buttons(cancel_key, confirm_label, confirm_key, danger=False):
    with st.container(horizontal=True, horizontal_alignment="right"):
        cancel = st.form_submit_button("Cancel", key=cancel_key)
        confirm = st.form_submit_button(confirm_label, type="primary", key=confirm_key)
    return cancel, confirm


@st.dialog("New class", icon=":material/school:", on_dismiss=common.close_dialog)
def create_class(teacher):
    with st.form("new_class", border=False):
        name = st.text_input("Class name", placeholder="Intro to writing", key="new_class_name")
        term = st.text_input("Term (optional)", placeholder="First semester 2026", key="new_class_term")
        cancel, create = _buttons("new_class_cancel", "Create class", "new_class_create")
    if cancel:
        common.finish_dialog()
    if create:
        try:
            record = classes.create_class(name, teacher, term)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            st.session_state["open_class_id"] = record["class_id"]
            common.go("app_pages/teacher_classes.py")
            common.finish_dialog("Class created. Its join code is {}.".format(
                classes.format_code(record["join_code"])), ":material/school:")


@st.dialog("New assignment", icon=":material/assignment:", width="medium",
           on_dismiss=common.close_dialog)
def create_assignment(class_id, teacher):
    with st.form("new_assignment", border=False):
        title = st.text_input("Title", placeholder="Why people keep diaries", key="new_task_title")
        instructions = st.text_area("Instructions", height=160, key="new_task_instructions",
                                    placeholder="Write a short essay (about 200 words)...")
        with st.container(horizontal=True):
            due = st.date_input("Due date (optional)", value=None, min_value=datetime.date.today(),
                                key="new_task_due")
            points = st.number_input("Points (optional)", min_value=1, max_value=assignments.MAX_POINTS,
                                     value=None, step=1, key="new_task_points",
                                     placeholder="Empty if not graded")
        cancel, create = _buttons("new_task_cancel", "Create assignment", "new_task_create")
    if cancel:
        common.finish_dialog()
    if create:
        try:
            assignments.create_assignment(class_id, title, instructions, due or "", teacher,
                                          points="" if points is None else points)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            common.finish_dialog("Assignment created. Students in the class can see it now.",
                                 ":material/assignment:")


@st.dialog("Edit assignment", icon=":material/edit:", width="medium", on_dismiss=common.close_dialog)
def edit_assignment(assignment_id, teacher):
    task = assignments.get_assignment(assignment_id)
    with st.form("edit_assignment", border=False):
        title = st.text_input("Title", value=task["title"], key="edit_task_title")
        instructions = st.text_area("Instructions", value=task["instructions"], height=160,
                                    key="edit_task_instructions")
        with st.container(horizontal=True):
            due = st.date_input("Due date (optional)", value=store.parse_date(task["due_at"]),
                                key="edit_task_due")
            points = st.number_input("Points (optional)", min_value=1, max_value=assignments.MAX_POINTS,
                                     value=assignments.max_points(task), step=1, key="edit_task_points",
                                     placeholder="Empty if not graded")
        cancel, save = _buttons("edit_task_cancel", "Save", "edit_task_save")
    if cancel:
        common.finish_dialog()
    if save:
        try:
            assignments.update_assignment(assignment_id, by=teacher, title=title, instructions=instructions,
                                          due_at=due or "", points="" if points is None else points)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            common.finish_dialog("Assignment saved. Students see the change right away.",
                                 ":material/edit:")


@st.dialog("Rename class", icon=":material/edit:", on_dismiss=common.close_dialog)
def rename_class(class_id, teacher):
    record = classes.get_class(class_id)
    with st.form("rename_class", border=False):
        name = st.text_input("Class name", value=record["name"], key="rename_class_name")
        term = st.text_input("Term (optional)", value=record["term"], key="rename_class_term")
        cancel, save = _buttons("rename_cancel", "Save", "rename_save")
    if cancel:
        common.finish_dialog()
    if save:
        try:
            classes.rename_class(class_id, name, term, by=teacher)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            common.finish_dialog("Class renamed.", ":material/edit:")


@st.dialog("Return every decided submission?", icon=":material/assignment_return:",
           on_dismiss=common.close_dialog)
def return_all(review_ids, teacher):
    listed = [reviews.get_review(r) for r in review_ids]
    names = [common.display_name(r["username"]) for r in listed]
    st.write("These students will see your decision and your note: {}.".format(
        ", ".join("**{}**".format(common.md(n)) for n in names)))
    unsaved = [common.display_name(r["username"]) for r in listed if common.unsaved_draft(r)]
    if unsaved:
        st.warning("Not saved yet for {}: they get the decision you last saved. Cancel and save "
                   "first to send the change.".format(", ".join("**{}**".format(common.md(n)) for n in unsaved)),
                   icon=":material/edit_note:")
    with st.form("return_all", border=False):
        cancel, confirm = _buttons("return_all_cancel", "Return {}".format(len(review_ids)),
                                   "return_all_confirm")
    if cancel:
        common.finish_dialog()
    if confirm:
        done, failed = 0, []
        for review_id in review_ids:
            try:
                reviews.return_to_student(review_id, by=teacher)
                done += 1
            except ValueError as exc:
                failed.append(str(exc))
        if failed:
            common.flash("Returned {}; not returned: {}".format(done, "; ".join(failed)), ":material/error:")
        common.finish_dialog("Returned {} submission{}.".format(done, "" if done == 1 else "s"),
                             ":material/assignment_return:")


@st.dialog("New join code?", icon=":material/key:", on_dismiss=common.close_dialog)
def rotate_code(class_id, teacher):
    st.write("The current code stops working. Students already in the class stay in it.")
    with st.form("rotate_code", border=False):
        cancel, confirm = _buttons("rotate_cancel", "Make a new code", "rotate_confirm")
    if cancel:
        common.finish_dialog()
    if confirm:
        try:
            code = classes.rotate_join_code(class_id, by=teacher)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            common.finish_dialog("The new join code is {}.".format(classes.format_code(code)),
                                 ":material/key:")


@st.dialog("Archive this class?", icon=":material/archive:", on_dismiss=common.close_dialog)
def archive_class(class_id, teacher):
    st.write("The class disappears from your list and its code stops working. Nothing is deleted; "
             "you can restore it from the archived list.")
    with st.form("archive_class", border=False):
        cancel, confirm = _buttons("archive_cancel", "Archive class", "archive_confirm")
    if cancel:
        common.finish_dialog()
    if confirm:
        try:
            classes.set_archived(class_id, True, by=teacher)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            st.session_state["open_class_id"] = None
            common.finish_dialog("Class archived.", ":material/archive:")


@st.dialog("Remove this student?", icon=":material/person_remove:", on_dismiss=common.close_dialog)
def remove_student(class_id, username, teacher):
    st.write("**{}** leaves the class. Their submissions and your reviews stay on file, and the "
             "roster keeps a row marked removed. You can add them back from the Removed list on "
             "the roster.".format(common.md(common.display_name(username))))
    with st.form("remove_student", border=False):
        cancel, confirm = _buttons("remove_cancel", "Remove student", "remove_confirm")
    if cancel:
        common.finish_dialog()
    if confirm:
        try:
            classes.remove_student(class_id, username, by=teacher)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            common.finish_dialog("{} was removed from the class.".format(common.display_name(username)),
                                 ":material/person_remove:")


def _forget_reset():
    st.session_state.pop("reset_result", None)
    common.close_dialog()


@st.dialog("Reset the password?", icon=":material/lock_reset:", on_dismiss=_forget_reset)
def reset_password(class_id, username, teacher):
    name = common.md(common.display_name(username))
    done = st.session_state.get("reset_result")
    if done and done["username"] == username:
        st.write("Give **{}** this temporary password. At the next sign-in they are asked to choose "
                 "their own. It is not shown again.".format(name))
        st.code(done["password"], language=None)
        if st.button("Done", type="primary", key="reset_done"):
            _forget_reset()
            st.rerun()
        return
    st.write("**{}** gets a temporary password; the current one stops working.".format(name))
    with st.form("reset_password", border=False):
        cancel, confirm = _buttons("reset_cancel", "Reset password", "reset_confirm")
    if cancel:
        common.finish_dialog()
    if confirm:
        try:
            temporary = classes.reset_student_password(class_id, username, by=teacher)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            st.session_state["reset_result"] = {"username": username, "password": temporary}
            st.rerun()


@st.dialog("Return to the student?", icon=":material/assignment_return:",
           on_dismiss=common.close_dialog)
def return_work(review_id, teacher):
    """Shows exactly what the student will get. Changes not saved yet (the
    Review page keeps them per review) are what is returned, saved first:
    read here, when the dialog opens, so a note typed just before the click
    is included."""
    review = reviews.get_review(review_id)
    draft = common.unsaved_draft(review)
    graded = assignments.max_points(assignments.get_assignment(review["assignment_id"]) or {})
    if draft:
        decision, note, points = draft["decision"], draft["note"], draft["points"]
    else:
        decision, note = review["decision"], review["note"]
        points = float(review["points"]) if review.get("points") else None
    name = common.md(common.display_name(review["username"]))
    if not decision or decision == "pending":
        st.write("Choose a decision for **{}** before returning the work.".format(name))
        if st.button("Close", key="return_cancel"):
            common.finish_dialog()
        return
    st.write("**{}** will see this. The detector's numbers stay on your side.".format(name))
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            common.decision_badge(decision)
            if graded and points is not None:
                st.badge("{:g} / {} points".format(float(points), graded), color="blue", icon=":material/grade:")
        if note:
            st.markdown(common.plain(note))
        else:
            st.caption("No note.")
    if draft:
        st.caption(":material/edit_note: Not saved yet: returning saves it first.")
    shown = reviews.shown_to_student(review)
    if shown:
        st.caption("This replaces what they see now: {}, returned {}.".format(
            common.decision_text(shown["decision"]), common.when(shown["returned_at"])))
    with st.form("return_work", border=False):
        cancel, confirm = _buttons("return_cancel", "Save and return" if draft else "Return", "return_confirm")
    if cancel:
        common.finish_dialog()
    if confirm:
        try:
            if draft:
                reviews.decide(review_id, decision, note, teacher,
                               points=("" if points is None else points) if graded else None)
            reviews.return_to_student(review_id, by=teacher)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            st.session_state.get("review_drafts", {}).pop(review_id, None)
            common.finish_dialog("{} to {}.".format("Saved and returned" if draft else "Returned",
                                                    common.display_name(review["username"])),
                                 ":material/assignment_return:")
