"""Teacher home: what needs attention across every class.

Layout (from the dashboard mockup Nash liked): a header with the date and one
action; a row of four figures, each with its change this week; then rows
that pair a narrow list with a wide chart or table, at equal heights.
"""

import datetime

import pandas as pd
import streamlit as st

from classroom import reports, seed_demo
from ui import charts, common, dialogs

user = common.require_role("teacher")
state = st.session_state
config = common.load_config()


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


overview = reports.teacher_overview(user["username"])
today = datetime.date.today()

# ----------------------------------------------------------------- header
with st.container(horizontal=True, vertical_alignment="bottom"):
    with st.container():
        st.title("Hello, {}".format(common.first_name(user)), anchor=False)
        st.caption("Home · {}".format(today.strftime("%A, %B %d").replace(" 0", " ")))
    if overview["classes"]:
        st.button("New class", type="primary", icon=":material/add:", on_click=common.open_dialog,
                  args=("create_class",), kwargs={"teacher": user["username"]}, key="home_add_class")

for note in state.get("config_notes", []):
    if "public default" in note:
        st.warning(note, icon=":material/key:")

# ------------------------------------------------------------ no classes
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
    common.render_dialogs({"create_class": dialogs.create_class})
    st.stop()

# ------------------------------------------------------------ figures
# every figure has a second line, so the four cards line up
not_scored, scored = overview["awaiting_detection"], overview["scored"]
with st.container(horizontal=True):
    st.metric("Students", overview["students"], delta=overview["students_new"],
              delta_description="joined this week", border=True,
              help="Students active in at least one of your classes.")
    st.metric("Handed in", overview["handed_in"], delta=overview["handed_in_week"],
              delta_description="this week", border=True,
              help="Every version handed in, counting resubmissions.")
    st.metric("To decide", overview["awaiting_decision"],
              delta="{} not scored yet".format(not_scored) if not_scored else "all scored",
              delta_color="off", delta_arrow="off", border=True,
              help="Scored submissions without your decision.")
    st.metric("Flagged or likely", overview["flagged"],
              delta="of {} scored".format(scored) if scored else "none scored yet",
              delta_color="off", delta_arrow="off", border=True,
              help="Current versions scored as likely MarkText, or flagged by you.")

# ------------------------------------------------ attention and scores
left, right = st.columns([1, 2])
with left.container(border=True, height="stretch"):
    st.subheader("To review", icon=":material/pending_actions:", anchor=False)
    if not overview["queue"]:
        st.caption("Nothing waiting. New submissions appear here.")
    for item in overview["queue"]:
        with st.container(border=True):
            st.markdown("**{}**".format(item["title"]))
            due = " · due {}".format(common.day(item["due_at"])) if item["due_at"] else ""
            st.caption("{}{}".format(item["class_name"], due))
            with st.container(horizontal=True, vertical_alignment="center"):
                if item["awaiting_detection"]:
                    st.badge("{} not scored".format(item["awaiting_detection"]), color="blue",
                             icon=":material/hourglass_empty:")
                if item["awaiting_decision"]:
                    st.badge("{} to decide".format(item["awaiting_decision"]), color="orange",
                             icon=":material/pending_actions:")
                st.space("small")
                st.button("Open", key="home_open_{}".format(item["assignment_id"]),
                          on_click=common.open_review, args=(item["class_id"], item["assignment_id"]))
with right.container(border=True, height="stretch"):
    st.subheader("Scores this term", icon=":material/scatter_plot:", anchor=False)
    if not overview["scores"]:
        st.caption("Scored submissions appear here: each dot is a student's current version.")
    else:
        st.altair_chart(charts.scores_chart(overview["scores"], float(config["detection_threshold"]),
                                            float(config["possible_threshold"])))
        st.caption("Each dot is a student's current version. Above the upper line: likely MarkText; "
                   "between the lines: possible. Fewer than {} tokens scored: inconclusive.".format(
                       config["min_tokens_for_verdict"]))

# ------------------------------------------------- flags and classes
left, right = st.columns([1, 2])
with left.container(border=True, height="stretch"):
    st.subheader("Recent flags", icon=":material/flag:", anchor=False)
    if not overview["recent_flags"]:
        st.caption("No current version is flagged or scored as likely MarkText.")
    for flag in overview["recent_flags"]:
        with st.container(border=True):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown("**{}**".format(flag["student"]))
                if flag["decision"] == "flagged":
                    common.decision_badge("flagged")
                else:
                    common.verdict_badge(flag["label"])
            st.caption("{} · version {} · {}".format(flag["assignment"], flag["version"],
                                                     common.when(flag["detected_at"])))
            st.button("View", key="home_flag_{}".format(flag["review_id"]), icon=":material/visibility:",
                      on_click=common.open_review,
                      args=(flag["class_id"], flag["assignment_id"], flag["username"]))
with right.container(border=True, height="stretch"):
    with st.container(horizontal=True, vertical_alignment="center"):
        st.subheader("Your classes", icon=":material/school:", anchor=False)
        st.page_link("app_pages/teacher_classes.py", label="Manage classes",
                     icon=":material/arrow_forward:")
    table = pd.DataFrame(overview["class_rows"])[["name", "term", "students", "open", "to_decide",
                                                  "not_scored", "join_code"]]
    st.dataframe(table, hide_index=True, column_config={
        "name": st.column_config.TextColumn("Class"),
        "term": st.column_config.TextColumn("Term"),
        "students": st.column_config.NumberColumn("Students", format="%d"),
        "open": st.column_config.NumberColumn("Open", format="%d", help="Open assignments"),
        "to_decide": st.column_config.NumberColumn("To decide", format="%d"),
        "not_scored": st.column_config.NumberColumn("Not scored", format="%d"),
        "join_code": st.column_config.TextColumn("Join code")})

common.render_dialogs({"create_class": dialogs.create_class})
