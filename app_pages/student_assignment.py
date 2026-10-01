"""Student: read an assignment, write or upload the answer, hand it in.

Each hand-in writes a new version (TXT + JSON sidecar) under
data/submissions/ and a row in data/submissions.csv; earlier versions stay.
Until then the answer is also kept in data/drafts/ (classroom/drafts.py), so
a sign-out or a reload does not lose it. When the teacher returns the work,
the decision and the note show here; the detector's numbers stay on the
teacher's side.
"""

import streamlit as st

from classroom import assignments, assistant, classes, drafts, reviews, submissions
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
if state.get("open_assignment_id") not in titles:
    # just signed in (again): open the answer that was not handed in yet
    state["open_assignment_id"] = drafts.newest(user["username"], list(titles))
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
restored_key = "draft_restored_" + assignment_id
if text_key not in state:
    # a new session (signed in again, or reloaded): bring back what was not handed in
    saved = drafts.load(user["username"], assignment_id)
    if saved:
        state[text_key], state[source_key] = saved["text"], saved["source"]
        if saved["upload_name"]:
            state["upload_name_" + assignment_id] = saved["upload_name"]
        if saved["generation"]:
            state["assistant_record_" + assignment_id] = saved["generation"]
        state[restored_key] = saved["saved_at"]
state.setdefault(text_key, "")
state.setdefault(source_key, "editor")
if editor_key not in state:
    state[editor_key] = state[text_key]


def set_text(text, source):
    state[text_key] = state[editor_key] = text
    state[source_key] = source


def keep_copy():
    """Write the answer to data/drafts/ (classroom/drafts.py). A failure is
    shown under the editor, never in the way of writing."""
    try:
        drafts.save(user["username"], assignment_id, state[text_key], state[source_key],
                    upload_name=state.get("upload_name_" + assignment_id, ""),
                    generation=state.get("assistant_record_" + assignment_id))
    except ValueError as exc:
        state["draft_problem_" + assignment_id] = str(exc)
    else:
        state.pop("draft_problem_" + assignment_id, None)
    state.pop(restored_key, None)


def sync_editor():
    state[text_key] = state[editor_key]
    if not state[text_key].strip():
        state[source_key] = "editor"
    keep_copy()


# ------------------------------------------------------------ callbacks
def take(text, source, upload_name="", record=None, below=False):
    """Put a file or an assistant draft into the editor, in place of the
    text there or (below=True) after it."""
    if below:
        text = state.get(editor_key, "").rstrip() + "\n\n" + text
    if upload_name:
        state["upload_name_" + assignment_id] = upload_name
    if record is not None:
        state["assistant_record_" + assignment_id] = record
        state["assistant_draft"] = None
    set_text(text, source)
    state["write_mode_" + assignment_id] = "Write here"
    keep_copy()


def offer(text, source, upload_name="", record=None):
    """take(), after asking first when the editor already holds other text:
    one click must never overwrite what the student wrote."""
    mine = state.get(editor_key, "").strip()
    if mine and mine != text.strip():
        common.open_dialog("replace_text", text=text, source=source, upload_name=upload_name,
                           record=record)
    else:
        take(text, source, upload_name, record)


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
    offer(text, "upload", upload_name=uploaded.name)


def use_draft():
    draft = state.get("assistant_draft") or {}
    if draft.get("assignment_id") == assignment_id:
        offer(draft["text"], "assistant", record=draft["record"])


@st.dialog("Replace your text?", icon=":material/swap_horiz:", on_dismiss=common.close_dialog)
def replace_text(text, source, upload_name="", record=None):
    # the buttons change the editor in their callbacks: a dialog's body runs
    # after the text box is drawn, when Streamlit no longer lets its value change
    what = "the assistant's draft" if source == "assistant" else common.md(upload_name) or "the file"
    st.write("Your answer has {} words. Replace them with {} ({} words), or add it below your "
             "text?".format(len(state.get(editor_key, "").split()), what, len(text.split())))
    with st.form("replace_text", border=False):
        with st.container(horizontal=True, horizontal_alignment="right"):
            cancel = st.form_submit_button("Cancel", key="replace_cancel")
            below = st.form_submit_button("Add below", key="replace_below", on_click=take,
                                          args=(text, source, upload_name, record, True))
            replace = st.form_submit_button("Replace", type="primary", key="replace_confirm",
                                            on_click=take, args=(text, source, upload_name, record))
    if cancel:
        common.finish_dialog()
    if below or replace:
        common.finish_dialog("Added below your text." if below else "Your text was replaced.",
                             ":material/edit_document:")


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
    drafts.discard(user["username"], assignment_id)
    state.pop(restored_key, None)
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
            if shown.get("points") and task.get("points"):
                st.badge("{:g} / {} points".format(float(shown["points"]), task["points"]), color="blue",
                         icon=":material/grade:")
        st.caption("On version {}, returned {}".format(current["version"], common.when(shown["returned_at"])))
        if shown["note"]:
            st.markdown(common.plain(shown["note"]))

if current:
    with st.expander("What you handed in: version {}, {}{}".format(
            current["version"], common.when(current["submitted_at"]),
            " (after the due date)" if assignments.is_late(task, current["submitted_at"]) else ""),
            icon=":material/visibility:"):
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
        if state.get(restored_key):
            st.caption(":material/history: Restored the answer you had not handed in yet (kept {}).".format(
                common.when(state[restored_key])))
        if state.get("draft_problem_" + assignment_id):
            st.caption(":material/warning: Your answer could not be kept on the server ({}). Hand it in "
                       "soon, or keep a copy yourself.".format(common.md(state["draft_problem_" + assignment_id])))
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
                lengths = sorted(v for v in set(assistant.LENGTHS) | {limit} if v <= limit)
                length = st.select_slider("Length (tokens)", options=lengths, value=min(250, limit),
                                          key="assistant_length_" + assignment_id,
                                          help="Shorter drafts give too little evidence for a verdict.")
                ask = st.form_submit_button("Write a draft", icon=":material/auto_awesome:",
                                            key="assistant_go")
            if ask and common.job_running("assistant_job"):
                st.info("The assistant is still writing your last draft.", icon=":material/hourglass_top:")
            elif ask:
                engine, lock = common.engine()
                words, seconds = int(length * 0.75), length / 4.3
                # one model for everyone: a draft already being written goes first
                waiting = lock.locked()
                label = ("Waiting for another draft to finish, then writing about {} words."
                         if waiting else "Writing about {} words, roughly {:.0f} s.").format(words, seconds)
                # in a thread of its own (common.start_job), so a click during the
                # minute does not lose the draft
                common.start_job("assistant_job", lambda: assistant.draft(engine, lock, prompt, length),
                                 label, seconds * (2 if waiting else 1),
                                 assignment_id=assignment_id, prompt=prompt)
            job = common.finished_job("assistant_job")
            if job and job["error"]:
                st.error(common.md(job["error"]), icon=":material/error:")
            elif job:
                state["assistant_draft"] = {"assignment_id": job["assignment_id"], "text": job["result"]["text"],
                                            "record": assistant.generation_record(job["result"], job["prompt"])}
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

common.render_dialogs({"replace_text": replace_text})
