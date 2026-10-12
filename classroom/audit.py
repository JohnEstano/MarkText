"""The activity log: who did what, and when (data/audit.csv).

Every change made through the classroom is one appended row: signing in
(and failed attempts), registering, classes, rosters, assignments,
hand-ins, scoring, decisions, returns, exports, restores and integrity
checks. Nothing in MarkText rewrites or deletes this file, so it is the
history of all the other files; the teacher reads, filters and exports it
on the Records page.

Writing the log never stops the action it describes. If the file cannot be
written (open in Excel, say), the action still happens and the failure goes
to the server's log: refusing a student's hand-in over a missing log line
would be worse than the missing line.
"""

import logging

from classroom import paths, store

COLUMNS = ["timestamp", "actor", "action", "target", "details"]
ACTIONS = {
    "sign_in": "Signed in",
    "sign_in_failed": "Sign-in failed",
    "sign_in_paused": "Sign-in paused",
    "registered": "Registered",
    "password_changed": "Changed password",
    "password_reset": "Password reset",
    "renamed": "Changed display name",
    "class_created": "Created a class",
    "class_renamed": "Renamed a class",
    "join_code_changed": "New join code",
    "class_archived": "Archived a class",
    "class_restored": "Restored a class",
    "joined_class": "Joined a class",
    "roster_imported": "Imported a roster",
    "student_removed": "Removed a student",
    "student_added_back": "Added a student back",
    "assignment_created": "Created an assignment",
    "assignment_changed": "Changed an assignment",
    "handed_in": "Handed in",
    "scored": "Scored",
    "decided": "Decided",
    "returned": "Returned",
    "exported": "Exported",
    "backup_restored": "Restored a backup",
    "integrity_checked": "Checked the files",
    "key_rotated": "Replaced the watermark key",
}
log = logging.getLogger("marktext.audit")


def record(actor, action, target="", details=""):
    """Append one row and return it. Never raises for a file problem."""
    row = {"timestamp": store.now(), "actor": actor or "", "action": action,
           "target": target or "", "details": " ".join(str(details or "").split())}
    try:
        store.append_row(paths.audit_path(), COLUMNS, row)
    except ValueError as exc:
        log.warning("activity log not written: %s (%s)", exc, row)
    return row


def read(actor=None, action=None):
    """Rows, newest first, optionally for one person or one action."""
    rows = [r for r in store.read_rows(paths.audit_path(), COLUMNS)
            if (actor is None or r["actor"] == actor) and (action is None or r["action"] == action)]
    rows.reverse()
    return rows


def export(rows, by=None):
    """Write the given rows to a new CSV under data/reports/."""
    target = store.unique_path(paths.reports_dir(), "activity_{}".format(store.stamp()), ".csv")
    path = store.write_new_csv(target, COLUMNS, rows)
    record(by, "exported", paths.data_relative(path), "{} activity rows".format(len(rows)))
    return path
