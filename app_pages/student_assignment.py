"""Student: read an assignment, write or upload the answer, hand it in.

Each hand-in writes a new version (TXT + JSON sidecar) under
data/submissions/ and a row in data/submissions.csv; earlier versions stay.
When the teacher returns the work, the decision and the note show here; the
detector's numbers stay on the teacher's side.
"""

import streamlit as st

from classroom import assignments, assistant, classes, reviews, submissions
from ui import common

user = common.require_role("student")
state = st.session_state
config = common.load_config()

st.title("Assignment", anchor=False)
tasks = assignments.for_student(user["username"])
if not tasks:
    common.empty_state("No assignments yet", "Assignments appear here once your teacher posts "
                       "them. Join a class from your home page first.", "assignment")
    st.stop()

titles = {t["assignment_id"]: t["title"] for t in tasks}
class_names = {c["class_id"]: c["name"] for c in classes.classes_for_student(user["username"])}
where = {t["assignment_id"]: class_names.get(t["class_id"], "") for t in tasks}
assignment_id = common.choose("Assignment", list(titles), "open_assignment_id", titles.get,
                              detail=where.get, label_visibility="collapsed")
task = assignments.get_assignment(assignment_id)
current = submissions.current_submission(assignment_id, user["username"])
# only what the teacher returned, as it was returned; never the detector's numbers
shown = reviews.shown_to_student(reviews.latest_review(current["submission_id"])) if current else None
returned = shown is not None
# The editor's text lives in a plain key (draft_<id>) as well as in the widget
# (editor_<id>): Streamlit drops a widget's value when its page is not shown,
# and a half-written essay must survive a visit to another page.
text_key = "draft_" + assignment_id
editor_key = "editor_" + assignment_id
source_key = "draft_source_" + assignment_id  # editor | upload | assistant
state.setdefault(text_key, "")
state.setdefault(source_key, "editor")
if editor_key not in state:
    state[editor_key] = state[text_key]


def set_text(text, source):
    state[text_key] = state[editor_key] = text
    state[source_key] = source


def sync_editor():
    state[text_key] = state[editor_key]
    if not state[text_key].strip():
        state[source_key] = "editor"


# ------------------------------------------------------------ callbacks
def on_upload():
    uploaded = state.get("upload_" + assignment_id)
    if uploaded is None:
        return
    try:
        text = uploaded.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        common.flash("{} is not a UTF-8 text file. Save it as UTF-8 and try again.".format(uploaded.name),
                     ":material/error:")
        return
    set_text(text, "upload")
    state["upload_name_" + assignment_id] = uploaded.name
    state["write_mode_" + assignment_id] = "Write here"


def use_draft():
    draft = state.get("assistant_draft") or {}
    if draft.get("assignment_id") == assignment_id:
        set_text(draft["text"], "assistant")
        state["assistant_record_" + assignment_id] = draft["record"]
        state["assistant_draft"] = None
        state["write_mode_" + assignment_id] = "Write here"


def discard_draft():
    state["assistant_draft"] = None


def hand_in():
    text = state.get(editor_key, state.get(text_key, ""))
    source = state.get(source_key, "editor")
    if source == "assistant" and not text.strip():
        source = "editor"
    try:
        row = submissions.submit(
            assignment_id, user["username"], text, source,
            upload_filename=state.get("upload_name_" + assignment_id, ""),
            version_note=state.get("version_note_" + assignment_id, ""),
            generation=state.get("assistant_record_" + assignment_id) if source == "assistant" else None)
    except ValueError as exc:
        common.flash(str(exc), ":material/error:")
        return
    common.flash("Version {} handed in.".format(row["version"]), ":material/assignment_turned_in:")
    set_text("", "editor")
    state["version_note_" + assignment_id] = ""
    state.pop("assistant_record_" + assignment_id, None)
    state.pop("upload_name_" + assignment_id, None)


# ------------------------------------------------------------ header
record = classes.get_class(task["class_id"]) or {}
with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="center"):
        with st.container():
            st.subheader(common.md(task["title"]), anchor=False)
            due = "Due {}".format(common.day(task["due_at"])) if task["due_at"] else "No due date"
            if assignments.is_overdue(task) and task["status"] == "open":
                due += " (past due)"
            st.caption("{} · {}".format(common.md(record.get("name", "")), due))
        if task["status"] == "open":
            st.badge("Open", color="green")
        else:
            st.badge("Closed", color="gray", icon=":material/lock:")
        common.state_badge("returned" if returned else ("submitted" if current else "not submitted"))
    if task["instructions"]:
        st.markdown(common.plain(task["instructions"]))

if returned:
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.subheader("Your teacher's decision", icon=":material/assignment_return:", anchor=False)
            common.decision_badge(shown["decision"])
        st.caption("On version {}, returned {}".format(current["version"], common.when(shown["returned_at"])))
        if shown["note"]:
            st.markdown(common.plain(shown["note"]))

if current:
    with st.expander("What you handed in: version {}, {}".format(
            current["version"], common.when(current["submitted_at"])), icon=":material/visibility:"):
        text = common.submission_text(current)
        if text is not None:
            st.markdown(common.plain(text))

if task["status"] != "open":
    st.info("This assignment is closed. Your teacher is no longer accepting work for it.",
            icon=":material/lock:")
    st.stop()

# ------------------------------------------------------------ writing
next_version = int(current["version"]) + 1 if current else 1
write_col, help_col = st.columns([3, 2], gap="large")
with write_col:
    with st.container(border=True):
        st.subheader("Your answer" if not current else "A new version", icon=":material/edit_document:", anchor=False)
        mode = st.segmented_control("How", ["Write here", "Upload a .txt file"], default="Write here",
                                    key="write_mode_" + assignment_id, label_visibility="collapsed",
                                    required=True)
        if mode == "Upload a .txt file":
            st.file_uploader("Text file", type=["txt"], key="upload_" + assignment_id, on_change=on_upload,
                             help="Plain text, UTF-8. The text opens in the editor so you can check it.")
        st.text_area("Answer", key=editor_key, height=320, label_visibility="collapsed",
                     placeholder="Write your answer here.", on_change=sync_editor)
        words = len(state.get(editor_key, "").split())
        origin = {"editor": "", "upload": " · from {}".format(common.md(state.get("upload_name_" + assignment_id, "a file"))),
                  "assistant": " · started from an assistant draft"}.get(state[source_key], "")
        st.caption("{} words{}".format(words, origin))
        st.text_input("Note for your teacher (optional)", key="version_note_" + assignment_id,
                      placeholder="What changed in this version?", max_chars=submissions.MAX_NOTE)
        st.button("Hand in version {}".format(next_version), type="primary",
                  icon=":material/assignment_turned_in:", on_click=hand_in, key="hand_in")

with help_col:
    # ---- the assistant: the whole block goes away when the switch is off
    if assistant.enabled(config):
        with st.container(border=True):
            st.subheader("Draft with the assistant", icon=":material/auto_awesome:", anchor=False)
            st.caption("The assistant writes a first draft for you. Its drafts are watermarked: "
                       "your teacher can tell that the text came from the assistant.")
            with st.form("assistant_" + assignment_id, border=False):
                prompt = st.text_area("What should it write?", value=task["title"], height=90,
                                      key="assistant_prompt_" + assignment_id)
                limit = assistant.max_tokens(config)
                lengths = sorted(v for v in {100, 150, 200, limit} if v <= limit)
                length = st.select_slider("Length (tokens)", options=lengths, value=min(200, limit),
                                          key="assistant_length_" + assignment_id)
                ask = st.form_submit_button("Write a draft", icon=":material/auto_awesome:",
                                            key="assistant_go")
            if ask:
                engine, lock = common.engine()
                try:
                    with st.spinner("Writing about {} words, roughly {:.0f} s...".format(
                            int(length * 0.75), length / 4.3)):
                        info = assistant.draft(engine, lock, prompt, length)
                except ValueError as exc:
                    st.error(common.md(str(exc)), icon=":material/error:")
                else:
                    state["assistant_draft"] = {"assignment_id": assignment_id, "text": info["text"],
                                                "record": assistant.generation_record(info, prompt)}
            draft = state.get("assistant_draft")
            if draft and draft.get("assignment_id") == assignment_id:
                with st.container(height=260, border=True):
                    st.markdown(common.plain(draft["text"]))
                with st.container(horizontal=True):
                    st.button("Use this draft", type="primary", on_click=use_draft, key="draft_use",
                              icon=":material/content_copy:")
                    st.button("Discard", on_click=discard_draft, key="draft_discard")
    older = submissions.versions(assignment_id, user["username"])
    if older:
        with st.container(border=True):
            st.subheader("Your versions", icon=":material/history:", anchor=False)
            for version in reversed(older):
                st.markdown("**Version {}** · {} · {} words".format(
                    version["version"], common.when(version["submitted_at"]), version["words"]))
                if version["version_note"]:
                    st.caption(common.md(version["version_note"]))
