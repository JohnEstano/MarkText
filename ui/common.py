"""What every page shares: the model, the signed-in person, badges, dialogs,
flash messages and navigation between pages.

Streamlit reruns a page script on every interaction. Anything that must
survive a rerun is kept in st.session_state (one per browser tab); the
model is kept in st.cache_resource (one per server process).
"""

import collections
import copy
import functools
import logging
import re
import threading
import time

import streamlit as st

import config as cfg
import verdict
from classroom import accounts, paths, reports, reviews, store, submissions

log = logging.getLogger("marktext")

# absolute, so the app also starts from another working folder
STATIC_DIR = paths.BASE_DIR / "static"
MARK = str(STATIC_DIR / "mark.svg")

# ------------------------------------------------------------------ state
DEFAULTS = {
    "user": None,               # public account record once signed in
    "dialog": None,             # {"name": ..., **context} while a dialog is open
    "flash": [],                # (message, icon) toasts to show on the next run
    "goto": None,               # page to switch to on the next run
    "page_seen": None,          # url path of the page shown last run
    "config_notes": [],         # what the config loader reported this session
    "notes_dismissed": [],
    "weak_password": False,     # signed in with a password that should be changed
    "last_seen": None,          # time of the last interaction, for the idle sign-out
    "review_drafts": {},        # review id -> unsaved decision and note
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
    """The validated config. What the loader reports (a config created, a key
    generated, the public key in use) is added to this session's notes, so a
    note from the first run of the session is still there on later runs.
    ValueError propagates to app.py."""
    notes = []
    config = cfg.load_config(notes=notes)
    store.KEEP_BACKUPS = config["classroom"]["keep_backups"]
    kept = st.session_state.setdefault("config_notes", [])
    dismissed = st.session_state.get("notes_dismissed", [])
    for note in notes:
        if note not in kept and note not in dismissed:
            kept.append(note)
    return config


def dismiss_notes():
    state = st.session_state
    state["notes_dismissed"] = state.get("notes_dismissed", []) + state.get("config_notes", [])
    state["config_notes"] = []


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
    """(engine, lock), loading the model on first use. A config edited since
    the model loaded (a new key, other thresholds) is adopted first, so a
    score always uses the key the pages name; a new model id or device
    loads a new engine."""
    eng, lock = get_engine()
    config = cfg.load_config()
    if config != eng.config:
        with lock:
            adopted = config == eng.config or eng.reconfigure(config)
        if not adopted:
            get_engine.clear()
            eng, lock = get_engine()
    return eng, lock


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
    st.session_state["last_seen"] = time.time()


def idle_minutes(config):
    return int(config.get("classroom", {}).get("idle_minutes", 30))


def check_idle(config):
    """Sign out a tab that has been idle for longer than the configured
    minutes (0 = never), then count this interaction. A classroom laptop
    left open must not stay signed in as the teacher."""
    state = st.session_state
    limit = idle_minutes(config)
    now = time.time()
    if state.get("user") and limit and state.get("last_seen") and now - state["last_seen"] > limit * 60:
        sign_out()
        init_state()
        flash("You were signed out after {} minutes without activity.".format(limit), ":material/timer:")
    state["last_seen"] = now


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
PROTECTED = ("teacher_classes", "teacher_review", "teacher_records", "lab_generate", "lab_detect",
             "lab_history", "lab_experiment", "account", "about", "student_assignment",
             "student_submissions")


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
                 page("app_pages/teacher_review.py", "Review", ":material/fact_check:"),
                 page("app_pages/teacher_records.py", "Records", ":material/folder_managed:")],
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


def unique_labels(options, format_func=str, detail=None):
    """option -> label, no two alike. A select box sends back the label that
    was picked and Streamlit maps it to the last option with that label, so
    of two students both called "Alice Santos" the first could never be
    opened. Labels shared by several options get detail(option) added, then
    a number when that is still not enough."""
    labels = {o: str(format_func(o)) for o in options}
    if detail is not None:
        shared = collections.Counter(labels.values())
        for o in options:
            if shared[labels[o]] > 1:
                labels[o] = "{} · {}".format(labels[o], detail(o))
    taken = set(labels.values())
    used = set()
    for o in options:
        label = labels[o]
        if label in used:
            n = 2
            while "{} ({})".format(label, n) in taken:
                n += 1
            label = "{} ({})".format(label, n)
            taken.add(label)
        used.add(label)
        labels[o] = label
    return labels


def choose(label, options, state_key, format_func=str, detail=None, **kwargs):
    """A selectbox whose choice lives in st.session_state[state_key], which
    other pages may set (a widget's own key is dropped when its page is not
    shown). Labels are made unique (unique_labels, with `detail`). Returns
    the chosen option; `options` must not be empty."""
    state = st.session_state
    widget_key = "_pick_" + state_key
    labels = unique_labels(options, format_func, detail)
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
    st.selectbox(label, options, format_func=lambda o: labels.get(o, str(o)), key=widget_key,
                 on_change=sync, **kwargs)
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


def safely(action):
    """Wrap a button callback: a ValueError (a broken rule, or a data file
    that is open in another program) becomes a message on the next run
    instead of an exception on the page."""
    @functools.wraps(action)
    def run(*args, **kwargs):
        try:
            return action(*args, **kwargs)
        except ValueError as exc:
            flash(str(exc), ":material/error:")
    return run


def problem(exc):
    """What app.py shows when a page stops on a ValueError or an OSError (a
    data file that is damaged, missing or locked). The traceback goes to
    the server's log, not to the browser."""
    log.exception("page stopped")
    st.error(md(str(exc)) if isinstance(exc, ValueError) else
             "A file could not be read or written: {}".format(md(exc)), icon=":material/error:")
    st.caption("Nothing was changed. Close the file if another program has it open, or restore "
               "it from data/backups, then reload the page.")


def show_flash():
    for message, icon in st.session_state.get("flash", []):
        st.toast(md(message), icon=icon)       # messages quote names, titles and codes
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


def _escape(text):
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text or "")


_INLINE_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>!$~|])")


def md(text):
    """User-written text inside one line of Markdown (a name, a title, a
    note, a message): shown literally, never as a link, an image, bold,
    HTML or a formula. A student's display name reaches the teacher's
    pages, so "![x](http://...)" must stay text."""
    text = _INLINE_SPECIAL.sub(r"\\\1", str(text or ""))
    text = re.sub(r"^([#+\-])", r"\\\1", text)          # would start a heading or a list
    text = re.sub(r"^(\d+)\.", r"\1\\.", text)          # "1." would start a numbered list
    return " ".join(text.split())


def plain(text):
    """Show user-written text literally in st.markdown (no accidental bold,
    links or formulas) while keeping its line breaks."""
    return "  \n".join(_escape(text).split("\n"))


def highlighted(text, start, end, colour="orange"):
    """plain(text) with the characters start..end on a coloured background
    (the strongest passage the scorer found). Each line of the passage is
    marked on its own, because a background cannot span a line break."""
    text = text or ""
    start, end = max(0, int(start)), min(len(text), int(end))
    if start >= end:
        return plain(text)
    marked = [":{}-background[{}]".format(colour, _escape(line)) if line.strip() else _escape(line)
              for line in text[start:end].split("\n")]
    body = _escape(text[:start]) + "\n".join(marked) + _escape(text[end:])
    return "  \n".join(body.split("\n"))


def passage_decided(review, config):
    """True when a review's "likely" came from a passage, not from the
    whole text: the whole-text z is under the threshold."""
    if not review or review.get("label") != verdict.LABEL_LIKELY:
        return False
    if review.get("passage_z") in ("", None) or review.get("passage_start") in ("", None):
        return False
    try:
        return float(review["z_score"]) < float(config["detection_threshold"])
    except (TypeError, ValueError):
        return False


def scoring_notes(repeated, passage_z, passage_p, decisive):
    """Captions that explain a score beyond its z: repeats counted once,
    and the strongest passage with its corrected p-value."""
    notes = []
    if repeated and int(float(repeated)) > 0:
        count = int(float(repeated))
        notes.append("{} repeated phrase{} counted once: a repeat is not new evidence.".format(
            count, "" if count == 1 else "s"))
    if passage_z not in ("", None):
        notes.append("Strongest passage (highlighted): z = {:.2f} over {} scored tokens, p = {} after "
                     "correcting for every passage tried.{}".format(
                         float(passage_z), verdict.PASSAGE_WINDOW, passage_p,
                         " The verdict comes from this passage." if decisive else ""))
    return notes


def when(timestamp):
    """'2026-09-29 14:05:12' -> 'Sep 29, 14:05'. An unreadable value shows as it is."""
    moment = store.parse_time(timestamp)
    if moment is None:
        return timestamp or ""
    return moment.strftime("%b %d, %H:%M").replace(" 0", " ")


def day(iso_date):
    """'2026-10-15' -> 'Oct 15, 2026'. An unreadable value shows as it is."""
    date = store.parse_date(iso_date)
    if date is None:
        return iso_date or ""
    return date.strftime("%b %d, %Y").replace(" 0", " ")


def submission_text(sub):
    """The text of a submission, or None after a warning on the page when its
    file is missing or cannot be read."""
    try:
        return submissions.read_text(sub)
    except ValueError as exc:
        st.warning(md(str(exc)), icon=":material/warning:")
        return None


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
            st.markdown("**{}**".format(md(user["display_name"])))
            st.caption("{} · {}".format(md(user["username"]), user["role"].capitalize()))
            st.button("Sign out", icon=":material/logout:", key="sign_out", on_click=sign_out,
                      type="tertiary")
        if MODEL["loaded"]:
            st.caption("Model {} on {}".format(MODEL["model_id"], MODEL["device"]))
        else:
            st.caption("The model loads the first time it is needed.")


def display_name(username):
    user = accounts.get_user(username)
    return user["display_name"] if user else username
