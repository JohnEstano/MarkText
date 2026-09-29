"""Teacher home: what needs attention across every class."""

import streamlit as st

from classroom import classes, reports, seed_demo
from ui import common, dialogs

user = common.require_role("teacher")
state = st.session_state


def load_demo():
    with st.status("Building the demo class...", expanded=True) as status:
        st.write("Loading the model (about 20 s the first time)...")
        engine, lock = common.engine()
        try:
            summary = seed_demo.seed(user["username"], engine, lock, on_step=st.write)
        except ValueError as exc:
            status.update(label="The demo class could not be built", state="error")
            st.error(str(exc), icon=":material/error:")
            return
        status.update(label="Demo class ready", state="complete")
    common.flash("Demo class ready. Students sign in with the password {}.".format(
        seed_demo.DEMO_PASSWORD), ":material/school:")
    common.open_review(summary["class_id"], summary["assignment_id"])
    st.rerun()


st.title("Hello, {}".format(common.first_name(user)), anchor=False)
overview = reports.teacher_overview(user["username"])

for note in state.get("config_notes", []):
    if "public default" in note:
        st.warning(note, icon=":material/key:")

if overview["classes"] == 0:
    common.empty_state("No classes yet",
                       "Create a class and share its code with your students, or load a demo "
                       "class with five students and scored essays.", "school")
    with st.container(horizontal=True, horizontal_alignment="center"):
        st.button("Create your first class", type="primary", icon=":material/add:",
                  on_click=common.open_dialog, args=("create_class",),
                  kwargs={"teacher": user["username"]}, key="home_new_class")
        demo = st.button("Load the demo class", icon=":material/science:", key="home_demo",
                         help="Adds the students alice, ben, chloe, dan and eva, one assignment, "
                              "four essays written by people and one drafted with the assistant, "
                              "then scores them. Takes about a minute.")
    if demo:
        load_demo()
else:
    common.metric_row([
        ("Classes", overview["classes"], None),
        ("Students", overview["students"], "Students active in at least one of your classes."),
        ("Open assignments", overview["open_assignments"], None),
        ("Not scored yet", overview["awaiting_detection"],
         "Handed in, but not yet checked for the watermark."),
        ("Awaiting your decision", overview["awaiting_decision"],
         "Scored, but no decision recorded yet."),
    ])

    left, right = st.columns([3, 2], gap="large")
    with left:
        with st.container(border=True):
            st.subheader("Needs your attention", icon=":material/pending_actions:", anchor=False)
            if not overview["queue"]:
                st.caption("Nothing waiting. New submissions appear here.")
            for item in overview["queue"]:
                with st.container(border=True, horizontal=True, vertical_alignment="center"):
                    with st.container():
                        st.markdown("**{}**".format(item["title"]))
                        due = " · due {}".format(common.day(item["due_at"])) if item["due_at"] else ""
                        st.caption("{}{}".format(item["class_name"], due))
                    if item["awaiting_detection"]:
                        st.badge("{} not scored".format(item["awaiting_detection"]), color="blue",
                                 icon=":material/hourglass_empty:")
                    if item["awaiting_decision"]:
                        st.badge("{} to decide".format(item["awaiting_decision"]), color="orange",
                                 icon=":material/pending_actions:")
                    st.button("Open", key="home_open_{}".format(item["assignment_id"]),
                              on_click=common.open_review,
                              args=(item["class_id"], item["assignment_id"]))
    with right:
        with st.container(border=True):
            st.subheader("Recent flags", icon=":material/flag:", anchor=False)
            if not overview["recent_flags"]:
                st.caption("No submission has been flagged or scored as likely MarkText.")
            for flag in overview["recent_flags"]:
                with st.container(horizontal=True, vertical_alignment="center"):
                    with st.container():
                        st.markdown("**{}**".format(flag["student"]))
                        st.caption("{} · {}".format(flag["assignment"], common.when(flag["detected_at"])))
                    if flag["decision"] == "flagged":
                        common.decision_badge("flagged")
                    else:
                        common.verdict_badge(flag["label"])
                    st.button("View", key="home_flag_{}_{}".format(flag["assignment_id"], flag["username"]),
                              type="tertiary", on_click=common.open_review,
                              args=(flag["class_id"], flag["assignment_id"], flag["username"]))
        with st.container(horizontal=True):
            st.button("New class", icon=":material/add:", on_click=common.open_dialog,
                      args=("create_class",), kwargs={"teacher": user["username"]},
                      key="home_new_class_2")
            st.page_link("app_pages/teacher_classes.py", label="All classes", icon=":material/school:")

common.render_dialogs({"create_class": dialogs.create_class})
