"""What every page shares: the model, the signed-in person, badges, dialogs,
flash messages and navigation between pages.

Streamlit reruns a page script on every interaction. Anything that must
survive a rerun is kept in st.session_state (one per browser tab); the
model is kept in st.cache_resource (one per server process).
"""

import copy
import datetime
import re
import threading

import streamlit as st

import config as cfg
import verdict
from classroom import accounts, paths, reports, reviews

# ------------------------------------------------------------------ state
DEFAULTS = {
    "user": None,               # public account record once signed in
    "dialog": None,             # {"name": ..., **context} while a dialog is open
    "flash": [],                # (message, icon) toasts to show on the next run
    "goto": None,               # page to switch to on the next run
    "page_seen": None,          # url path of the page shown last run
    "config_notes": [],
    "open_class_id": None,      # Classes page: the class that is open
    "open_assignment_id": None, # student Assignment page
    "review_class": None,       # Review page selectors
    "review_assignment": None,
    "review_pick": None,
    "run_detect": None,         # "all" or a submission id, handled at page top
    "assistant_draft": None,    # {"assignment_id", "text", "record"}
}


def init_state():
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, copy.deepcopy(value))


def load_config():
    """The validated config; its notes (created, key added, public key) are
    kept for the teacher's pages. ValueError propagates to app.py."""
    notes = []
    config = cfg.load_config(notes=notes)
    st.session_state["config_notes"] = notes
    return config


# ------------------------------------------------------------------ model
MODEL = {"loaded": False, "model_id": "", "device": ""}


def make_engine(config):
    """Build the real engine. Tests replace this function with a fake."""
    import engine              # late: importing torch and loading the model is slow
    return engine.Engine(config)


@st.cache_resource(show_spinner="Loading the language model (the first run downloads about 1 GB)...")
def get_engine():
    """One engine per server process, shared by every browser tab. The lock
    serialises calls, because the model is one object used by all sessions."""
    config = cfg.load_config()
    eng = make_engine(config)
    MODEL.update(loaded=True, model_id=config["model_id"], device=eng.device)
    return eng, threading.Lock()


def engine():
    """(engine, lock), loading the model on first use."""
    return get_engine()


# ------------------------------------------------------------------ people
def current_user():
    return st.session_state.get("user")


def require_role(role):
    """The signed-in user, or stop the page. Pages are only registered for
    their role, so this is a second line of defence."""
    user = current_user()
    if user is None or user["role"] != role:
        st.error("This page is for {}s.".format(role), icon=":material/lock:")
        st.stop()
    return user


def sign_in(user):
    st.session_state["user"] = user
    st.session_state["goto"] = None


def sign_out():
    """Forget everything this tab knew; the next run shows the sign-in page."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def first_name(user):
    name = user.get("display_name") or user["username"]
    return name.split()[0] if not name.lower().startswith(("prof", "dr", "mr", "ms", "mrs")) else name


# ------------------------------------------------------------------ pages
def page(path, title, icon, default=False):
    return st.Page(path, title=title, icon=icon, default=default)


# Addresses of the pages behind the sign-in (the two home pages live at "/").
PROTECTED = ("teacher_classes", "teacher_review", "lab_generate", "lab_detect", "lab_history",
             "lab_experiment", "account", "about", "student_assignment", "student_submissions")


def pages_for(user):
    if user is None:
        # Sign-in lasts for one browser tab, so a reload lands here signed out.
        # The sign-in form answers at every protected address too: after
        # signing in, the person is back on the page they reloaded.
        return [page("app_pages/login.py", "Sign in", ":material/login:", default=True)] + [
            st.Page("app_pages/login.py", title="Sign in", icon=":material/login:", url_path=name)
            for name in PROTECTED]
    account = [page("app_pages/account.py", "Account", ":material/person:"),
               page("app_pages/about.py", "About", ":material/info:")]
    if user["role"] == "teacher":
        return {
            "": [page("app_pages/teacher_home.py", "Home", ":material/home:", default=True),
                 page("app_pages/teacher_classes.py", "Classes", ":material/school:"),
                 page("app_pages/teacher_review.py", "Review", ":material/fact_check:")],
            "Lab": [page("app_pages/lab_generate.py", "Generate", ":material/edit_note:"),
                    page("app_pages/lab_detect.py", "Detect", ":material/manage_search:"),
                    page("app_pages/lab_history.py", "History", ":material/history:"),
                    page("app_pages/lab_experiment.py", "Experiment", ":material/science:")],
            "Account": account,
        }
    return {
        "": [page("app_pages/student_home.py", "Home", ":material/home:", default=True),
             page("app_pages/student_assignment.py", "Assignment", ":material/edit_document:"),
             page("app_pages/student_submissions.py", "My submissions", ":material/inventory_2:")],
        "Account": account,
    }


def go(path):
    """Ask for another page. Safe inside callbacks, where st.switch_page is
    not allowed: app.py switches at the start of the next run."""
    st.session_state["goto"] = path


def follow_goto():
    target = st.session_state.get("goto")
    if target:
        st.session_state["goto"] = None
        st.switch_page(target)


def open_review(class_id, assignment_id, username=None):
    state = st.session_state
    state["review_class"], state["review_assignment"] = class_id, assignment_id
    state["review_pick"] = username
    go("app_pages/teacher_review.py")


def open_assignment(assignment_id):
    st.session_state["open_assignment_id"] = assignment_id
    go("app_pages/student_assignment.py")


def choose(label, options, state_key, format_func=str, **kwargs):
    """A selectbox whose choice lives in st.session_state[state_key], which
    other pages may set (a widget's own key is dropped when its page is not
    shown). Returns the chosen option; `options` must not be empty."""
    state = st.session_state
    widget_key = "_pick_" + state_key
    current = state.get(state_key)
    if current not in options:
        current = options[0]
        state[state_key] = current
    if state.get(widget_key) != current:
        # set before the widget is drawn: the browser then shows this value
        # (deleting the key would leave the browser's old choice on screen)
        state[widget_key] = current

    def sync():
        state[state_key] = state[widget_key]
    st.selectbox(label, options, format_func=format_func, key=widget_key, on_change=sync, **kwargs)
    return current


def on_page_change(nav):
    """A dialog belongs to the page that opened it."""
    state = st.session_state
    if state.get("page_seen") != nav.url_path:
        state["dialog"] = None
        state["page_seen"] = nav.url_path


# ----------------------------------------------------------------- dialogs
# A dialog is opened by a flag in session state, never by `if st.button()`:
# the page calls render_dialogs() last, and the dialog stays open on every
# rerun until it closes itself. (A dialog body is a fragment; a transient
# button press would not survive a full rerun, which is also all that
# AppTest does.)
def open_dialog(name, **context):
    st.session_state["dialog"] = dict(context, name=name)


def close_dialog():
    st.session_state["dialog"] = None


def render_dialogs(registry):
    current = st.session_state.get("dialog")
    if current and current["name"] in registry:
        context = {k: v for k, v in current.items() if k != "name"}
        registry[current["name"]](**context)


def finish_dialog(message=None, icon=":material/check_circle:"):
    """Close the open dialog, queue a toast and rerun the whole page."""
    close_dialog()
    if message:
        flash(message, icon)
    st.rerun()


# ------------------------------------------------------------------ flash
def flash(message, icon=":material/check_circle:"):
    st.session_state.setdefault("flash", []).append((message, icon))


def show_flash():
    for message, icon in st.session_state.get("flash", []):
        st.toast(message, icon=icon)
    st.session_state["flash"] = []


# ------------------------------------------------------------------ badges
VERDICT_BADGE = {
    verdict.LABEL_LIKELY: ("Likely MarkText", "red", ":material/verified:"),
    verdict.LABEL_POSSIBLE: ("Possible watermark", "orange", ":material/help:"),
    verdict.LABEL_NOT_DETECTED: ("Not detected", "gray", ":material/remove:"),
    verdict.LABEL_INCONCLUSIVE: ("Inconclusive, too short", "gray", ":material/hourglass_empty:"),
}
DECISION_BADGE = {
    "pending": ("Pending", "gray", ":material/schedule:"),
    "accepted": ("Accepted", "green", ":material/check_circle:"),
    "flagged": ("Flagged", "red", ":material/flag:"),
    "needs_review": ("Needs review", "orange", ":material/rate_review:"),
}
STATE_BADGE = {
    "not submitted": ("Not submitted", "gray", ":material/radio_button_unchecked:"),
    "awaiting detection": ("Not scored", "blue", ":material/hourglass_empty:"),
    "awaiting decision": ("Scored", "orange", ":material/pending_actions:"),
    "decided": ("Decided", "violet", ":material/task_alt:"),
    "returned": ("Returned", "green", ":material/done_all:"),
    # student-side states
    "submitted": ("Handed in", "blue", ":material/assignment_turned_in:"),
}
# colours for the same states in tables (MultiselectColumn badges)
STATE_ORDER = list(reports.STATES)
STATE_COLOURS = ["gray", "blue", "orange", "violet", "green"]
VERDICT_ORDER = list(VERDICT_BADGE)
VERDICT_COLOURS = ["red", "orange", "gray", "gray"]


def verdict_text(label):
    return VERDICT_BADGE.get(label, (label or "Not scored", "gray", None))[0]


def decision_text(decision):
    return reviews.DECISION_LABELS.get(decision, decision or "")


def verdict_badge(label, where=st):
    text, colour, icon = VERDICT_BADGE.get(label, (label or "Not scored", "gray", None))
    where.badge(text, icon=icon, color=colour)


def decision_badge(decision, where=st):
    text, colour, icon = DECISION_BADGE.get(decision, (decision, "gray", None))
    where.badge(text, icon=icon, color=colour)


def state_badge(state, where=st):
    text, colour, icon = STATE_BADGE.get(state, (state, "gray", None))
    where.badge(text, icon=icon, color=colour)


# ------------------------------------------------------------------ layout
def empty_state(title, body, icon="inbox"):
    with st.container(border=True, horizontal_alignment="center"):
        st.space("small")
        st.markdown(":material/{}:".format(icon), text_alignment="center")
        st.markdown("**{}**".format(title), text_alignment="center")
        st.caption(body, text_alignment="center")
        st.space("small")


def metric_row(items):
    """[(label, value, help), ...] as bordered metrics that wrap on phones."""
    with st.container(horizontal=True):
        for label, value, help_text in items:
            st.metric(label, value, help=help_text, border=True)


_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|~<>$])")


def plain(text):
    """Show user-written text literally in st.markdown (no accidental bold,
    links or formulas) while keeping its line breaks."""
    escaped = _MARKDOWN_SPECIAL.sub(r"\\\1", text or "")
    return "  \n".join(escaped.split("\n"))


def when(timestamp):
    """'2026-09-29 14:05:12' -> 'Sep 29, 14:05'."""
    try:
        moment = datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return timestamp or ""
    return moment.strftime("%b %d, %H:%M").replace(" 0", " ")


def day(iso_date):
    """'2026-10-15' -> 'Oct 15, 2026'."""
    try:
        return datetime.date.fromisoformat(iso_date).strftime("%b %d, %Y").replace(" 0", " ")
    except (TypeError, ValueError):
        return iso_date or ""


# ------------------------------------------------------------------ files
def data_label(path):
    """How a file under data/ or logs/ is named on screen."""
    try:
        return "data/" + paths.data_relative(path)
    except ValueError:
        return str(path)


def sidebar_footer(user):
    with st.sidebar:
        st.space("small")
        with st.container(border=True):
            st.markdown("**{}**".format(user["display_name"]))
            st.caption("{} · {}".format(user["username"], user["role"].capitalize()))
            st.button("Sign out", icon=":material/logout:", key="sign_out", on_click=sign_out,
                      type="tertiary")
        if MODEL["loaded"]:
            st.caption("Model {} on {}".format(MODEL["model_id"], MODEL["device"]))
        else:
            st.caption("The model loads the first time it is needed.")


def display_name(username):
    user = accounts.get_user(username)
    return user["display_name"] if user else username
