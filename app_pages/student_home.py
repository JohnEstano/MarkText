"""Student home: what is due, what came back, and joining a class.

Same layout as the teacher's home: a header with the date and one action,
four figures, then a narrow list beside a wide one at equal heights.
"""

import datetime

import streamlit as st

from classroom import accounts, classes, reports, submissions
from ui import common

user = common.require_role("student")
state = st.session_state


def join():
    code = state.get("join_code", "")
    try:
        record = classes.join_class(code, user["username"])
    except ValueError as exc:
        common.flash(str(exc), ":material/error:")
    else:
        common.flash("You joined {}.".format(record["name"]), ":material/school:")
        state["join_code"] = ""


def join_form():
    st.text_input("Class code", placeholder="ABC-234", key="join_code",
                  help="Your teacher shares a six-character code.")
    st.button("Join class", type="primary", icon=":material/group_add:", on_click=join,
              key="join_submit", width="stretch")


my_classes = classes.classes_for_student(user["username"])
today = datetime.date.today()

# ----------------------------------------------------------------- header
with st.container(horizontal=True, vertical_alignment="bottom"):
    with st.container():
        st.title("Hello, {}".format(common.first_name(user)), anchor=False)
        names = ", ".join(c["name"] for c in my_classes)
        st.caption("Home · {}{}".format(today.strftime("%A, %B %d").replace(" 0", " "),
                                        " · " + names if names else ""))
    if my_classes:
        with st.popover("Join a class", icon=":material/group_add:"):
            join_form()

if not my_classes:
    common.empty_state("You are not in a class yet",
                       "Ask your teacher for the class code and type it below.", "school")
    _, middle, _ = st.columns([1, 1, 1])
    with middle:
        join_form()
    st.stop()

work = reports.student_overview(user["username"])
open_work = [w for w in work if w["status"] == "open"]
to_hand_in = [w for w in open_work if w["my_state"] == "not submitted"]
waiting = [w for w in work if w["my_state"] == "submitted"]
returned = [w for w in work if w["my_state"] == "returned"]
due_this_week = sum(reports.due_soon(w["due_at"]) for w in to_hand_in)
returned_this_week = sum(reports.recent(w["returned_at"]) for w in returned)

# ------------------------------------------------------------ figures
# every figure has a second line, so the four cards line up
handed_this_week = sum(reports.recent(v["submitted_at"]) for v in
                       submissions.list_submissions(username=user["username"], current_only=False))
with st.container(horizontal=True):
    st.metric("To hand in", len(to_hand_in),
              delta="{} due this week".format(due_this_week) if due_this_week else "none due this week",
              delta_color="off", delta_arrow="off", border=True)
    st.metric("Waiting for your teacher", len(waiting), delta=handed_this_week,
              delta_description="handed in this week", border=True,
              help="Handed in, not returned yet. Resubmissions count as new hand-ins.")
    st.metric("Returned", len(returned), delta=returned_this_week, delta_description="this week",
              border=True)
    st.metric("Classes", len(my_classes), delta="{} open assignments".format(len(open_work)),
              delta_color="off", delta_arrow="off", border=True)

# --------------------------------------------------- returned and work
left, right = st.columns([1, 2])
with left.container(border=True, height="stretch"):
    st.subheader("Returned to you", icon=":material/done_all:", anchor=False)
    if not returned:
        st.caption("Nothing returned yet. Your teacher's decisions appear here.")
    for item in returned:
        with st.container(horizontal=True, vertical_alignment="center"):
            with st.container():
                st.markdown("**{}**".format(item["title"]))
                st.caption("{} · returned {}".format(item["class_name"], common.when(item["returned_at"])))
            common.decision_badge(item["decision"])
            st.button("View", key="view_" + item["assignment_id"], type="tertiary",
                      on_click=common.open_assignment, args=(item["assignment_id"],))
with right.container(border=True, height="stretch"):
    st.subheader("Assignments", icon=":material/assignment:", anchor=False)
    if not open_work:
        st.caption("Nothing open right now.")
    for item in open_work:
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            with st.container():
                st.markdown("**{}**".format(item["title"]))
                due = "due {}".format(common.day(item["due_at"])) if item["due_at"] else "no due date"
                if reports.due_soon(item["due_at"]) and item["my_state"] == "not submitted":
                    due += " (this week)"
                st.caption("{} · {}".format(item["class_name"], due))
            common.state_badge(item["my_state"])
            st.button("Open", key="open_" + item["assignment_id"], on_click=common.open_assignment,
                      args=(item["assignment_id"],),
                      type="primary" if item["my_state"] == "not submitted" else "secondary")
    teachers = accounts.display_names()
    st.caption("Teachers: {}".format(", ".join(sorted({teachers.get(c["teacher"], c["teacher"])
                                                      for c in my_classes}))))
