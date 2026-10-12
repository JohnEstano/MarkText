"""Checking that the classroom's files agree with each other.

check() reads every data file and reports what does not fit. It changes
nothing: it opens the files read-only instead of through store.read_rows,
which would create a missing file or extend an old header.

What it looks for:
- a data file that cannot be read, or that has other columns than MarkText
  writes (someone edited it in a spreadsheet);
- a submission whose text file is missing, whose text no longer matches the
  SHA-256 recorded at hand-in, or whose JSON sidecar is missing or names
  another submission;
- a review whose submission is not in the index;
- roster rows, assignments and submissions that point at a class, an
  assignment or an account that does not exist;
- files under data/submissions that no index row mentions (left by a crash,
  or copied in by hand);
- temporary (.tmp) and lock (.lock) files older than a minute, left by a
  program that stopped in the middle of a write.

Each finding has a severity: "error" (something is lost or wrong),
"warning" (worth a look) or "info".
"""

import csv
import json
import time

import history
import locks
from classroom import assignments, audit, classes, paths, reviews, store, submissions

FINDING_COLUMNS = ["severity", "file", "problem", "detail"]
SEVERITIES = ("error", "warning", "info")


def _csv(path, columns, add):
    """Rows of a CSV file read without changing it, or None after a finding."""
    name = store.shown_path(path)
    if not path.exists():
        add("info", name, "not created yet", "It is created the first time it is needed.")
        return []
    try:
        with open(path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            if header != list(columns) and header != list(columns)[:len(header)]:
                add("error", name, "unexpected columns",
                    "It has {} but MarkText writes {}.".format(header, list(columns)))
                return None
            return [dict(zip(header, row)) for row in reader]
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        add("error", name, "cannot be read", str(exc))
        return None


def _json(path, key, add):
    name = store.shown_path(path)
    if not path.exists():
        add("info", name, "not created yet", "It is created the first time it is needed.")
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get(key), dict):
            add("error", name, "unexpected content", "It should hold an object with \"{}\".".format(key))
            return None
        return data[key]
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        add("error", name, "cannot be read", str(exc))
        return None


def check():
    """Every finding, most serious first."""
    findings = []

    def add(severity, file, problem, detail=""):
        findings.append({"severity": severity, "file": file, "problem": problem, "detail": detail})

    users = _json(paths.users_path(), "users", add)
    known_classes = _json(paths.classes_path(), "classes", add)
    roster = _csv(paths.rosters_path(), classes.ROSTER_COLUMNS, add)
    tasks = _csv(paths.assignments_path(), assignments.COLUMNS, add)
    index = _csv(paths.submissions_path(), submissions.COLUMNS, add)
    reviewed = _csv(paths.reviews_path(), reviews.COLUMNS, add)
    _csv(paths.audit_path(), audit.COLUMNS, add)

    usernames = set(users or {})
    class_ids = set(known_classes or {})
    task_ids = {t["assignment_id"] for t in tasks or []}

    if users is not None and known_classes is not None:
        for cid, record in (known_classes or {}).items():
            if record.get("teacher") not in usernames:
                add("warning", "data/classes.json", "teacher account missing",
                    "Class {} belongs to {}, who has no account.".format(cid, record.get("teacher")))
    for row in roster or []:
        if row.get("class_id") not in class_ids:
            add("warning", "data/rosters.csv", "unknown class",
                "{} is listed in {}, which does not exist.".format(row.get("username"), row.get("class_id")))
        if row.get("status") != "invited" and row.get("username") not in usernames:
            add("warning", "data/rosters.csv", "unknown account",
                "{} in {} has no account.".format(row.get("username"), row.get("class_id")))
    for task in tasks or []:
        if task.get("class_id") not in class_ids:
            add("warning", "data/assignments.csv", "unknown class",
                "Assignment {} belongs to {}, which does not exist.".format(task["assignment_id"],
                                                                            task.get("class_id")))

    referenced = set()
    for sub in index or []:
        sid = sub.get("submission_id", "?")
        text_path = paths.resolve(sub.get("text_path", ""))
        referenced.add(text_path.resolve())
        referenced.add(text_path.with_suffix(".json").resolve())
        where = "data/" + sub.get("text_path", "")
        if sub.get("assignment_id") not in task_ids:
            add("warning", "data/submissions.csv", "unknown assignment",
                "{} belongs to {}, which does not exist.".format(sid, sub.get("assignment_id")))
        try:
            if not submissions.intact(sub):
                add("error", where, "text changed after hand-in",
                    "Its SHA-256 no longer matches the one recorded for {}.".format(sid))
        except submissions.MissingText:
            add("error", where, "text file missing", "Recorded for {} but not on disk.".format(sid))
            continue
        except ValueError as exc:
            add("error", where, "cannot be read", str(exc))
            continue
        side = submissions.sidecar(sub)
        if side is None:
            add("warning", store.shown_path(text_path.with_suffix(".json")), "sidecar missing",
                "How {} was produced is no longer on record.".format(sid))
        elif side.get("submission_id") != sid:
            add("error", store.shown_path(text_path.with_suffix(".json")), "sidecar mismatch",
                "It describes {}, not {}.".format(side.get("submission_id"), sid))

    known_subs = {s.get("submission_id") for s in index or []}
    for review in reviewed or []:
        if review.get("submission_id") not in known_subs:
            add("warning", "data/reviews.csv", "unknown submission",
                "Review {} scores {}, which is not in the index.".format(review.get("review_id"),
                                                                        review.get("submission_id")))

    folder = paths.submissions_dir()
    if index is not None and folder.exists():
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix in (".txt", ".json") and path.resolve() not in referenced:
                add("warning", store.shown_path(path), "not in the index",
                    "A file no submission row mentions (an interrupted hand-in, or copied in).")

    now = time.time()
    for root in (paths.DATA_DIR, history.HISTORY_PATH.parent):
        if root.exists():
            for path in root.rglob("*"):
                if path.suffix in (".tmp", ".lock") and path.is_file() \
                        and now - path.stat().st_mtime > locks.STALE:
                    add("warning", store.shown_path(path), "left over from an interrupted write",
                        "Safe to delete when no MarkText program is running.")

    if not findings or all(f["severity"] == "info" for f in findings):
        add("info", "data/", "all files agree", "{} submissions, {} reviews, {} accounts checked.".format(
            len(index or []), len(reviewed or []), len(usernames)))
    findings.sort(key=lambda f: SEVERITIES.index(f["severity"]))
    return findings


def summary(findings):
    return {s: sum(f["severity"] == s for f in findings) for s in SEVERITIES}


def run(by=None):
    """check(), recorded in the activity log."""
    findings = check()
    counts = summary(findings)
    audit.record(by, "integrity_checked", "data/",
                 "{} errors, {} warnings".format(counts["error"], counts["warning"]))
    return findings


def export(findings, by=None):
    target = store.unique_path(paths.reports_dir(), "integrity_{}".format(store.stamp()), ".csv")
    path = store.write_new_csv(target, FINDING_COLUMNS, findings)
    audit.record(by, "exported", paths.data_relative(path), "integrity findings")
    return path
