"""Dialogs shared by the teacher pages. Each is opened with
common.open_dialog(name, **context) and drawn by common.render_dialogs()
at the end of the page; each closes itself with common.finish_dialog()."""

import datetime

import streamlit as st

from classroom import assignments, classes, reviews
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
        due = st.date_input("Due date (optional)", value=None, min_value=datetime.date.today(),
                            key="new_task_due")
        cancel, create = _buttons("new_task_cancel", "Create assignment", "new_task_create")
    if cancel:
        common.finish_dialog()
    if create:
        try:
            assignments.create_assignment(class_id, title, instructions, due or "", teacher)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            common.finish_dialog("Assignment created. Students in the class can see it now.",
                                 ":material/assignment:")


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
             "roster keeps a row marked removed.".format(common.md(common.display_name(username))))
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


@st.dialog("Return to the student?", icon=":material/assignment_return:",
           on_dismiss=common.close_dialog)
def return_work(review_id, teacher):
    review = reviews.get_review(review_id)
    st.write("**{}** will see your decision, **{}**, and your note. The detector's numbers stay "
             "on your side.".format(common.md(common.display_name(review["username"])),
                                    common.decision_text(review["decision"])))
    shown = reviews.shown_to_student(review)
    if shown:
        st.caption("This replaces what they see now: {}, returned {}.".format(
            common.decision_text(shown["decision"]), common.when(shown["returned_at"])))
    with st.form("return_work", border=False):
        cancel, confirm = _buttons("return_cancel", "Return", "return_confirm")
    if cancel:
        common.finish_dialog()
    if confirm:
        try:
            reviews.return_to_student(review_id, by=teacher)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            common.finish_dialog("Returned to {}.".format(common.display_name(review["username"])),
                                 ":material/assignment_return:")
