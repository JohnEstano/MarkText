"""Student submissions: every version kept, nothing overwritten.

Each version is a text file plus a JSON sidecar:
    data/submissions/<class_id>/<assignment_id>/<username>/v001.txt
    data/submissions/<class_id>/<assignment_id>/<username>/v001.json
and one row in the index data/submissions.csv. Resubmitting writes v002
beside v001 and marks the older index row "superseded" (a backed-up
rewrite); the teacher reviews the "current" version and can open any older
one. The sidecar records how the text was produced (typed, uploaded, or
drafted with the assistant, with the seed and model), never the watermark key.

A hand-in writes three files; if the last write fails (the index open in
Excel), the two files it had just created are removed again, so a failed
hand-in leaves nothing behind and the next one gets the same version number.
The text file holds exactly the UTF-8 bytes whose sha256 is in the index.
"""

import hashlib
import json

from classroom import accounts, assignments, classes, paths, store

COLUMNS = ["submission_id", "assignment_id", "class_id", "username", "version",
           "submitted_at", "source", "upload_filename", "text_path", "sha256", "words",
           "version_note", "status"]
SOURCES = ("editor", "upload", "assistant")
STATUSES = ("current", "superseded")
MAX_CHARS = 50_000
MAX_NOTE = 200
# what an assistant draft may record about itself (never the hashing key)
GENERATION_KEYS = ("prompt", "seed", "mode", "model_id", "max_new_tokens", "new_tokens",
                   "device", "key_id", "cancelled")


class MissingText(ValueError):
    """A submission's text file is gone (moved or deleted outside MarkText).
    The index row stays; restoring the file brings the submission back."""

    def __init__(self, submission):
        self.submission = submission
        super().__init__("The text of version {} ({}) is missing: it was moved or deleted outside "
                         "MarkText. The record is kept; restore the file to see the text again.".format(
                             submission.get("version", "?"), "data/" + submission.get("text_path", "")))


def _rows():
    return store.read_rows(paths.submissions_path(), COLUMNS)


def submission_dir(class_id, assignment_id, username):
    return paths.submissions_dir() / class_id / assignment_id / username


def normalise_text(text):
    """One newline convention and no surrounding blank space, so the stored
    text, its hash and the detector all see the same characters."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def submit(assignment_id, username, text, source="editor", upload_filename="",
           version_note="", generation=None):
    """Store a new version and return its index row. ValueError when the
    assignment is closed, the student is not in the class, or the text is
    empty or too long."""
    username = accounts.normalise_username(username)
    assignment = assignments.get_assignment(assignment_id)
    if assignment is None:
        raise ValueError("There is no assignment {}.".format(assignment_id))
    if assignment["status"] != "open":
        raise ValueError("This assignment is closed; your teacher is no longer accepting "
                         "submissions.")
    if not classes.is_member(assignment["class_id"], username):
        raise ValueError("You are not in the class for this assignment.")
    if source not in SOURCES:
        raise ValueError("source must be one of {}".format(", ".join(SOURCES)))
    text = normalise_text(text)
    if not text:
        raise ValueError("The submission is empty.")
    if len(text) > MAX_CHARS:
        raise ValueError("Submissions are limited to {:,} characters.".format(MAX_CHARS))
    version_note = " ".join((version_note or "").split())[:MAX_NOTE]

    index = paths.submissions_path()
    with store.lock_for(index):
        rows = _rows()
        mine = [r for r in rows if r["assignment_id"] == assignment_id and r["username"] == username]
        version = 1 + max((int(r["version"]) for r in mine), default=0)
        folder = submission_dir(assignment["class_id"], assignment_id, username)
        while (folder / "v{:03d}.txt".format(version)).exists():
            version += 1                          # a file left by an interrupted submit
        stem = "v{:03d}".format(version)
        row = {
            "submission_id": store.new_id("sub"),
            "assignment_id": assignment_id,
            "class_id": assignment["class_id"],
            "username": username,
            "version": version,
            "submitted_at": store.now(),
            "source": source,
            "upload_filename": (upload_filename or "") if source == "upload" else "",
            "text_path": "",
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "words": len(text.split()),
            "version_note": version_note,
            "status": "current",
        }
        txt, side = folder / (stem + ".txt"), folder / (stem + ".json")
        row["text_path"] = paths.data_relative(txt)
        sidecar = dict(row)
        if source == "assistant" and generation:
            sidecar["generation"] = {k: generation.get(k) for k in GENERATION_KEYS if k in generation}
        created = []
        try:
            store.check_writable(index)         # a locked index stops us before any file exists
            created.append(store.write_new_text(txt, text))
            created.append(store.write_new_json(side, sidecar))
            if any(r["status"] == "current" for r in mine):
                mine_ids = {r["submission_id"] for r in mine}
                for r in rows:
                    if r["submission_id"] in mine_ids and r["status"] == "current":
                        r["status"] = "superseded"
                store.rewrite_rows(index, COLUMNS, rows + [row])
            else:
                store.append_row(index, COLUMNS, row)
        except ValueError:
            for path in created:                  # made by this call, never in the index
                path.unlink(missing_ok=True)
            raise
    return {k: str(v) for k, v in row.items()}


def get_submission(submission_id):
    for row in _rows():
        if row["submission_id"] == submission_id:
            return row
    return None


def read_text(submission):
    """The stored text of a submission (a row or a submission id). Raises
    MissingText when the file is gone, FileProblem when it cannot be read."""
    if isinstance(submission, str):
        submission = get_submission(submission)
    path = paths.resolve(submission["text_path"])
    if not path.exists():
        raise MissingText(submission)
    with store.file_errors(path, "read"):
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()


def sidecar(submission):
    """The JSON sidecar of a submission, or None if it is missing."""
    side = paths.resolve(submission["text_path"]).with_suffix(".json")
    try:
        with open(side, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def current_submission(assignment_id, username):
    username = accounts.normalise_username(username)
    for row in _rows():
        if (row["assignment_id"] == assignment_id and row["username"] == username
                and row["status"] == "current"):
            return row
    return None


def versions(assignment_id, username):
    """Every version by this student for this assignment, oldest first."""
    username = accounts.normalise_username(username)
    rows = [r for r in _rows() if r["assignment_id"] == assignment_id and r["username"] == username]
    return sorted(rows, key=lambda r: int(r["version"]))


def list_submissions(assignment_id=None, username=None, class_id=None, current_only=True):
    """Newest first."""
    rows = [r for r in _rows()
            if (assignment_id is None or r["assignment_id"] == assignment_id)
            and (username is None or r["username"] == username)
            and (class_id is None or r["class_id"] == class_id)
            and (not current_only or r["status"] == "current")]
    return sorted(rows, key=lambda r: r["submitted_at"], reverse=True)
