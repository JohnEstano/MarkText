"""Student home: join a class with its code, see what is due and what came back."""

import streamlit as st

from classroom import accounts, classes, reports
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


st.title("Hello, {}".format(common.first_name(user)))

with st.container(border=True):
    st.markdown("**Join a class**")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input("Class code", placeholder="ABC-234", key="join_code",
                      help="Your teacher shares a six-character code.")
        st.button("Join", icon=":material/group_add:", on_click=join, key="join_submit")

my_classes = classes.classes_for_student(user["username"])
if not my_classes:
    common.empty_state("You are not in a class yet", "Ask your teacher for the class code and "
                       "type it above.", "school")
    st.stop()

work = reports.student_overview(user["username"])
todo = [w for w in work if w["status"] == "open" and w["my_state"] != "returned"]
returned = [w for w in work if w["my_state"] == "returned"]

common.metric_row([
    ("Classes", len(my_classes), None),
    ("To hand in", sum(w["my_state"] == "not submitted" and w["status"] == "open" for w in work), None),
    ("Handed in", sum(w["my_state"] == "submitted" for w in work), "Waiting for your teacher."),
    ("Returned", len(returned), None),
])

left, right = st.columns([3, 2], gap="large")
with left:
    with st.container(border=True):
        st.subheader("Assignments", icon=":material/assignment:")
        if not todo:
            st.caption("Nothing open right now.")
        for item in todo:
            with st.container(border=True, horizontal=True, vertical_alignment="center"):
                with st.container():
                    st.markdown("**{}**".format(item["title"]))
                    due = "due {}".format(common.day(item["due_at"])) if item["due_at"] else "no due date"
                    st.caption("{} · {}".format(item["class_name"], due))
                common.state_badge(item["my_state"])
                st.button("Open", key="open_" + item["assignment_id"], on_click=common.open_assignment,
                          args=(item["assignment_id"],),
                          type="primary" if item["my_state"] == "not submitted" else "secondary")
    if returned:
        with st.container(border=True):
            st.subheader("Returned to you", icon=":material/done_all:")
            for item in returned:
                with st.container(horizontal=True, vertical_alignment="center"):
                    with st.container():
                        st.markdown("**{}**".format(item["title"]))
                        st.caption("{} · returned {}".format(item["class_name"], common.when(item["returned_at"])))
                    common.decision_badge(item["decision"])
                    st.button("View", key="view_" + item["assignment_id"], type="tertiary",
                              on_click=common.open_assignment, args=(item["assignment_id"],))

with right:
    with st.container(border=True):
        st.subheader("Your classes", icon=":material/school:")
        names = accounts.display_names()
        for record in my_classes:
            st.markdown("**{}**".format(record["name"]))
            st.caption("{} · {}".format(record["term"] or "No term", names.get(record["teacher"],
                                                                                record["teacher"])))
