"""A student's unsaved answer, kept on disk while they write.

The Assignment page keeps the editor's text in the browser tab's session,
which every sign-out clears: after the idle limit (typing in the text box is
not an interaction Streamlit sees), and on a reload. So every change the page
receives (the text box losing focus or Ctrl+Enter, an uploaded file, an
assistant draft taken over) is also written to
data/drafts/<username>/<assignment_id>.json, atomically. No backup copy is
kept: the file is rewritten often and replaced by the hand-in, which deletes
it. The page reads it back when the session has no text for that assignment.

Only the student's own session reads a draft, after they sign in again; the
teacher never sees it, and it is not part of exports or the class zip.
"""

import logging

from classroom import paths, store

log = logging.getLogger("marktext.drafts")


def path_for(username, assignment_id):
    return paths.drafts_dir() / username / "{}.json".format(assignment_id)


def save(username, assignment_id, text, source="editor", upload_name="", generation=None):
    """Keep the editor's state; an empty text deletes the draft instead.
    Returns the saved record, or None. Raises ValueError (FileProblem) when
    the file cannot be written."""
    if not (text or "").strip():
        discard(username, assignment_id)
        return None
    record = {"assignment_id": assignment_id, "text": text, "source": source or "editor",
              "upload_name": upload_name or "", "generation": generation, "saved_at": store.now()}
    store.write_json(path_for(username, assignment_id), record, keep_backup=False)
    return record


def load(username, assignment_id):
    """The saved draft, or None when there is none or it cannot be read (a
    damaged draft must not stop the student from writing a new one)."""
    path = path_for(username, assignment_id)
    if not path.exists():
        return None
    try:
        record = store.read_json(path, {})
    except ValueError as exc:
        log.warning("Draft not read: %s", exc)
        return None
    text = record.get("text")
    return record if isinstance(text, str) and text.strip() else None


def discard(username, assignment_id):
    """Delete the draft (after a hand-in). A file that cannot be deleted
    stays and is overwritten by the next draft; nothing else depends on it."""
    path = path_for(username, assignment_id)
    with store.lock_for(path):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Draft not deleted: %s (%s)", store.shown_path(path), exc)


def newest(username, assignment_ids):
    """Of the given assignments, the one whose draft was saved last, or None."""
    found = [(record["saved_at"], aid) for aid in assignment_ids
             for record in [load(username, aid)] if record]
    return max(found)[1] if found else None
