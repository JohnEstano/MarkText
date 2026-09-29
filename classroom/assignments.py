"""Assignments, one row each in data/assignments.csv.

A teacher creates an assignment in one of their classes. Students can submit
while it is open; closing it stops new submissions but keeps everything.
"""

import datetime

from classroom import accounts, classes, paths, store

COLUMNS = ["assignment_id", "class_id", "title", "instructions", "due_at",
           "created_by", "created_at", "status"]
STATUSES = ("open", "closed")
EDITABLE = ("title", "instructions", "due_at", "status")
MAX_TITLE = 120
MAX_INSTRUCTIONS = 5000


def _rows():
    return store.read_rows(paths.assignments_path(), COLUMNS)


def _check_due(due_at):
    """'' or an ISO date (YYYY-MM-DD)."""
    due_at = (due_at or "").strip() if isinstance(due_at, str) else due_at
    if not due_at:
        return ""
    due = store.parse_date(due_at)
    if due is None:
        raise ValueError("Due dates look like 2026-10-15.")
    return due.isoformat()


def _check_fields(fields):
    out = {}
    if "title" in fields:
        title = " ".join((fields["title"] or "").split())
        if not title:
            raise ValueError("Give the assignment a title.")
        if len(title) > MAX_TITLE:
            raise ValueError("Titles are limited to {} characters.".format(MAX_TITLE))
        out["title"] = title
    if "instructions" in fields:
        text = (fields["instructions"] or "").strip()
        if len(text) > MAX_INSTRUCTIONS:
            raise ValueError("Instructions are limited to {} characters.".format(MAX_INSTRUCTIONS))
        out["instructions"] = text
    if "due_at" in fields:
        out["due_at"] = _check_due(fields["due_at"])
    if "status" in fields:
        if fields["status"] not in STATUSES:
            raise ValueError("Status must be open or closed.")
        out["status"] = fields["status"]
    return out


def create_assignment(class_id, title, instructions="", due_at="", created_by=""):
    record = classes.get_class(class_id)
    if record is None:
        raise ValueError("There is no class {}.".format(class_id))
    if accounts.normalise_username(created_by) != record["teacher"]:
        raise ValueError("Only the class's teacher can add assignments.")
    fields = _check_fields({"title": title, "instructions": instructions, "due_at": due_at})
    row = {"assignment_id": store.new_id("asg"), "class_id": class_id,
           "created_by": record["teacher"], "created_at": store.now(), "status": "open", **fields}
    store.append_row(paths.assignments_path(), COLUMNS, row)
    return row


def get_assignment(assignment_id):
    for row in _rows():
        if row["assignment_id"] == assignment_id:
            return row
    return None


def list_assignments(class_id=None, status=None):
    """Newest first."""
    rows = [r for r in _rows()
            if (class_id is None or r["class_id"] == class_id)
            and (status is None or r["status"] == status)]
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)


def update_assignment(assignment_id, by=None, **fields):
    """Change title, instructions, due date or status. Returns the backup path."""
    bad = [k for k in fields if k not in EDITABLE]
    if bad:
        raise ValueError("Not editable: {}".format(", ".join(bad)))
    clean = _check_fields(fields)
    current = get_assignment(assignment_id)
    if current is None:
        raise ValueError("There is no assignment {}.".format(assignment_id))
    if by is not None and current["created_by"] != by:
        raise ValueError("Only the class's teacher can change this assignment.")
    return store.update_one(paths.assignments_path(), COLUMNS, "assignment_id", assignment_id,
                            lambda r: dict(r, **clean))


def close_assignment(assignment_id, by=None):
    return update_assignment(assignment_id, by=by, status="closed")


def reopen_assignment(assignment_id, by=None):
    return update_assignment(assignment_id, by=by, status="open")


def is_overdue(assignment, today=None):
    """True when the due date has passed. A due date that cannot be read
    (retyped in a spreadsheet) counts as no due date rather than a crash."""
    due = store.parse_date(assignment.get("due_at"))
    return due is not None and due < (today or datetime.date.today())


def open_for_student(username):
    """Open assignments in the student's classes, soonest due first
    (assignments without a due date last)."""
    ids = {c["class_id"] for c in classes.classes_for_student(username)}
    rows = [r for r in _rows() if r["class_id"] in ids and r["status"] == "open"]
    return sorted(rows, key=lambda r: (r["due_at"] == "", r["due_at"], r["created_at"]))


def for_student(username):
    """Every assignment (open or closed) in the student's classes, newest first."""
    ids = {c["class_id"] for c in classes.classes_for_student(username)}
    return [r for r in list_assignments() if r["class_id"] in ids]
