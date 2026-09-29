"""MarkText Classroom: the Streamlit entry point.

    streamlit run app.py

A teacher runs a class: students hand in writing, and the teacher scores
each submission against MarkText's watermark and records a decision. This
file only sets the page up, signs people in and chooses the pages their
role may see. The pages live in app_pages/, the rules in classroom/, the
model in engine.py.

Streamlit reruns this script on every interaction. Per-person state lives in
st.session_state (one per browser tab); the model lives in
st.cache_resource (one per server process) and loads the first time a page
needs it, so signing in never waits for it.
"""

import streamlit as st

from classroom import paths
from ui import common, lab

st.set_page_config(page_title="MarkText Classroom", page_icon="static/mark.svg", layout="wide",
                   initial_sidebar_state="expanded")
common.init_state()
lab.init_state()

try:
    config = common.load_config()
except ValueError as exc:
    st.error("The configuration file has a problem, so MarkText cannot start.\n\n{}".format(exc),
             icon=":material/error:")
    st.stop()
paths.ensure_dirs()
lab.ensure_dirs()
st.logo("static/mark.svg", size="large")

user = common.current_user()
nav = st.navigation(common.pages_for(user), position="sidebar" if user else "hidden")
common.follow_goto()
common.on_page_change(nav)
if user:
    common.sidebar_footer(user)
    if st.session_state.get("weak_password"):
        st.warning("Your password is easy to guess, or it was published as a demo password. "
                   "Change it on the Account page.", icon=":material/lock_reset:")
common.show_flash()
try:
    nav.run()
except (ValueError, OSError) as exc:
    # a damaged, missing or locked data file: one message, not a traceback
    common.problem(exc)
