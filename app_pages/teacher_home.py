"""Teacher home: what needs attention across every class.

Layout (from the dashboard mockup Nash liked): a header with the date and one
action; a row of four figures, each with its change this week; then rows
that pair a narrow list with a wide chart or table, at equal heights.
"""

import datetime

import streamlit as st

from classroom import accounts, classes, reports, seed_demo
from ui import charts, common, dialogs

user = common.require_role("teacher")
state = st.session_state
config = common.load_config()


def load_demo(password):
    with st.status("Building the demo class...", expanded=True) as status:
        st.write("Loading the model (about 20 s the first time)...")
        engine, lock = common.engine()
        try:
            summary = seed_demo.seed(user["username"], engine, lock, on_step=st.write,
                                     password=password)
        except ValueError as exc:
            status.update(label="The demo class could not be built", state="error")
            st.error(common.md(str(exc)), icon=":material/error:")
            return
        status.update(label="Demo class ready", state="complete")
    if summary["accounts_created"]:
        common.flash("Demo class ready. The students sign in with the password you chose.",
                     ":material/school:")
    else:
        common.flash("Demo class ready. The demo students already had accounts; their passwords "
                     "did not change.", ":material/school:")
    common.open_review(summary["class_id"], summary["assignment_id"])
    st.rerun()


@st.dialog("Load the demo class", icon=":material/science:", on_dismiss=common.close_dialog)
def demo_dialog():
    st.write("Adds five student accounts (alice, ben, chloe, dan and eva), a class with one "
             "assignment, four essays written by people and one drafted with the assistant, then "
             "scores them. Takes about a minute.")
    with st.form("demo", border=False):
        password = st.text_input("Password for the demo students", key="demo_password",
                                 value=state.setdefault("_demo_suggestion", seed_demo.new_password()))
        st.caption("Shown so you can write it down: you sign in as a demo student with it. It is not "
                   "stored anywhere in plain text.")
        with st.container(horizontal=True, horizontal_alignment="right"):
            cancel = st.form_submit_button("Cancel", key="demo_cancel")
            build = st.form_submit_button("Build the demo class", type="primary", key="demo_build")
    if cancel:
        common.finish_dialog()
    if build:
        try:
            accounts.validate_password(password)
        except ValueError as exc:
            st.error(common.md(str(exc)), icon=":material/error:")
        else:
            state["demo_request"] = password
            state.pop("_demo_suggestion", None)
            common.finish_dialog()


overview = reports.teacher_overview(user["username"])
today = datetime.date.today()

# ----------------------------------------------------------------- header
with st.container(horizontal=True, vertical_alignment="bottom"):
    with st.container():
        st.title("Hello, {}".format(common.md(common.first_name(user))), anchor=False)
        st.caption("Home · {}".format(today.strftime("%A, %B %d").replace(" 0", " ")))
    if overview["classes"]:
        st.button("New class", type="primary", icon=":material/add:", on_click=common.open_dialog,
                  args=("create_class",), kwargs={"teacher": user["username"]}, key="home_add_class")
common.password_warning()

if state.get("config_notes"):
    with st.container(border=True):
        for note in state["config_notes"]:
            st.warning(note, icon=":material/key:" if "key" in note else ":material/settings:")
        st.button("Dismiss", key="home_dismiss_notes", on_click=common.dismiss_notes, type="tertiary",
                  help="Hides these notes for this session. A note about the public key comes back "
                       "on the next visit while that key is in use.")

# ------------------------------------------------------------ no classes
if overview["classes"] == 0:
    archived = [c for c in classes.list_classes(user["username"], include_archived=True) if c.get("archived")]
    if archived:                     # not "no classes": they are there, put away
        common.empty_state("All your classes are archived",
                           "Restore one on the Classes page, or create a new class.", "archive",
                           links=[("app_pages/teacher_classes.py", "Open Classes")])
    else:
        common.empty_state("No classes yet",
                           "Create a class and share its code with your students, or load a demo "
                           "class with five students and scored essays.", "school")
    with st.container(horizontal=True, horizontal_alignment="center"):
        st.button("Create a class" if archived else "Create your first class", type="primary", icon=":material/add:",
                  on_click=common.open_dialog, args=("create_class",),
                  kwargs={"teacher": user["username"]}, key="home_new_class")
        st.button("Load the demo class", icon=":material/science:", key="home_demo",
                  on_click=common.open_dialog, args=("demo",),
                  help="Five demo students, one assignment and scored essays, for trying MarkText "
                       "out. Takes about a minute.")
    request = state.pop("demo_request", None)
    if request:
        load_demo(request)
    common.render_dialogs({"create_class": dialogs.create_class, "demo": demo_dialog})
    st.stop()

old = overview["old_scores"]
if old:
    with st.container(border=True):
        total = sum(o["count"] for o in old)
        st.warning("1 score was made before repeated words counted once, so its verdict may be out of "
                   "date. Score it again on the Review page; the decision and note are kept."
                   if total == 1 else
                   "{} scores were made before repeated words counted once, so their verdicts may be out "
                   "of date. Score them again on the Review page; decisions and notes are kept.".format(total),
                   icon=":material/update:")
        st.button("Open {}".format(common.md(old[0]["title"])), key="home_old_scores",
                  icon=":material/arrow_forward:", type="tertiary",
                  on_click=common.open_review, args=(old[0]["class_id"], old[0]["assignment_id"]))

# ------------------------------------------------------------ figures
# every figure has a second line, so the four cards line up
not_scored, scored = overview["awaiting_detection"], overview["scored"]
with st.container(horizontal=True):
    st.metric("Students", overview["students"], delta=overview["students_new"],
              delta_description="joined this week", border=True,
              help="Students active in at least one of your classes.")
    st.metric("Versions handed in", overview["handed_in"], delta=overview["handed_in_week"],
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
    def queue_item(item):
        with st.container(border=True):
            st.markdown("**{}**".format(common.md(item["title"])))
            due = " · due {}".format(common.day(item["due_at"])) if item["due_at"] else ""
            st.caption("{}{}".format(common.md(item["class_name"]), due))
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
    common.short_list(overview["queue"], queue_item)
with right.container(border=True, height="stretch"):
    st.subheader("Scores this term", icon=":material/scatter_plot:", anchor=False)
    if not overview["scores"]:
        st.caption("Scored submissions appear here: each dot is a student's current version.")
    else:
        st.altair_chart(charts.scores_chart(overview["scores"], float(config["detection_threshold"]),
                                            float(config["possible_threshold"])))
        st.caption("Each dot is a student's current version at its whole-text z. Above the upper line: "
                   "likely MarkText; between the lines: possible. A red dot below the line had one "
                   "passage that scored as likely. Fewer than {} tokens scored: inconclusive.".format(
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
                st.markdown("**{}**".format(common.md(flag["student"])))
                if flag["decision"] == "flagged":
                    common.decision_badge("flagged")
                else:
                    common.verdict_badge(flag["label"])
            st.caption("{} · version {} · {}{}".format(common.md(flag["assignment"]), flag["version"],
                                                       common.when(flag["detected_at"]),
                                                       " · old count" if flag["old_count"] else ""))
            st.button("View", key="home_flag_{}".format(flag["review_id"]), icon=":material/visibility:",
                      on_click=common.open_review,
                      args=(flag["class_id"], flag["assignment_id"], flag["username"]))
with right.container(border=True, height="stretch"):
    with st.container(horizontal=True, vertical_alignment="center"):
        st.subheader("Your classes", icon=":material/school:", anchor=False)
        st.page_link("app_pages/teacher_classes.py", label="Manage classes",
                     icon=":material/arrow_forward:")
    # a list, not a table: it fits a phone and each class opens with one click
    for row in overview["class_rows"]:
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            with st.container():
                st.markdown("**{}**{}".format(common.md(row["name"]),
                                              " · " + common.md(row["term"]) if row["term"] else ""))
                facts = ["{} student{}".format(row["students"], "" if row["students"] == 1 else "s"),
                         "{} open".format(row["open"]), "class code {}".format(row["join_code"])]
                if row["to_decide"]:
                    facts.insert(2, "{} to decide".format(row["to_decide"]))
                if row["not_scored"]:
                    facts.insert(2, "{} not scored".format(row["not_scored"]))
                st.caption(" · ".join(facts))
            st.button("Open", key="home_class_" + row["class_id"], on_click=common.open_class, args=(row["class_id"],))

common.render_dialogs({"create_class": dialogs.create_class})
