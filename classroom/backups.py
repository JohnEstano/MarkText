"""Backup copies of the data files: listing them, and putting one back.

store.backup() copies a data file into data/backups/ before every rewrite
and keeps the newest KEEP_BACKUPS copies of each. restore() puts a copy
back in three steps:
1. the copy is checked: valid JSON with the right content, or a CSV with
   MarkText's columns. A damaged copy is refused, never restored;
2. the current file is backed up, so the restore itself can be undone;
3. the copy replaces the file atomically (temp file, then os.replace),
   under the file's lock.
Only the classroom's six data files can be restored, and every restore is
recorded in the activity log. Text files of submissions are never deleted,
so they need no backup.
"""

import csv
import datetime
import json
import shutil

import locks
from classroom import assignments, audit, classes, paths, reviews, store, submissions

# file name -> (where it lives, what it must contain: a JSON key or the CSV columns)
DATA_FILES = {
    "users.json": (paths.users_path, "users"),
    "classes.json": (paths.classes_path, "classes"),
    "rosters.csv": (paths.rosters_path, classes.ROSTER_COLUMNS),
    "assignments.csv": (paths.assignments_path, assignments.COLUMNS),
    "submissions.csv": (paths.submissions_path, submissions.COLUMNS),
    "reviews.csv": (paths.reviews_path, reviews.COLUMNS),
}


def _split(name):
    stem, _, suffix = name.rpartition(".")
    return stem, "." + suffix


def taken_at(copy_name):
    """'reviews_20260930_101500_123456.csv' -> '2026-09-30 10:15:00'."""
    stem = copy_name.rsplit(".", 1)[0]
    try:
        moment = datetime.datetime.strptime("_".join(stem.split("_")[-3:]), "%Y%m%d_%H%M%S_%f")
    except ValueError:
        return ""
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def listing():
    """Every backup copy of a data file, newest first."""
    rows = []
    for name in DATA_FILES:
        for copy in store.backups_of(*_split(name)):
            rows.append({"file": name, "backup": copy.name, "taken_at": taken_at(copy.name),
                         "size_kb": round(copy.stat().st_size / 1024, 1)})
    return sorted(rows, key=lambda r: (r["taken_at"], r["backup"]), reverse=True)


def _source(copy_name):
    for name in DATA_FILES:
        if copy_name in {p.name for p in store.backups_of(*_split(name))}:
            return name
    raise ValueError("{} is not a backup copy of a classroom data file.".format(copy_name))


def check_copy(copy_name):
    """Raise ValueError unless the copy holds what its data file must hold.
    Returns (data file name, number of records in the copy)."""
    name = _source(copy_name)
    path = paths.backups_dir() / copy_name
    _, content = DATA_FILES[name]
    try:
        if name.endswith(".json"):
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get(content), dict):
                raise ValueError("it does not hold \"{}\"".format(content))
            return name, len(data[content])
        with open(path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            if header != list(content)[:len(header)] or not header:
                raise ValueError("its columns are {}".format(header))
            return name, sum(1 for _ in reader)
    except (OSError, UnicodeDecodeError, ValueError, csv.Error) as exc:
        raise ValueError("The copy {} cannot be restored: {}.".format(copy_name, exc)) from exc


def restore(copy_name, by=None):
    """Put a backup copy back in place of its data file. Returns the backup
    of the file that was replaced (to undo the restore)."""
    name, records = check_copy(copy_name)
    target = DATA_FILES[name][0]()
    source = paths.backups_dir() / copy_name
    with store.lock_for(target):
        undo = store.backup(target)
        tmp = target.with_name(target.name + ".tmp")
        with store.file_errors(target, "restore"):
            try:
                shutil.copyfile(source, tmp)
                locks.replace(tmp, target)
            finally:
                if tmp.exists():
                    tmp.unlink()
    audit.record(by, "backup_restored", "data/" + name, "{} ({} records)".format(copy_name, records))
    return undo
