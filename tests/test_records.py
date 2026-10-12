"""The records behind the classroom: the activity log, the file check,
backups and restore, the class zip, and hand-ins by the teacher."""

import json
import os
import threading
import time
import zipfile

import pytest
from fakes import FakeEngine

from classroom import (archive, assignments, audit, backups, classes, detection, integrity, paths,
                       reviews, store, submissions)
from classroom import accounts


# ------------------------------------------------------------ activity log
def test_every_change_is_logged_in_order(course):
    aid = course["assignment"]["assignment_id"]
    sub = submissions.submit(aid, "alice", "an essay by alice " * 20)
    rev = detection.detect_submission(FakeEngine(), threading.Lock(), sub, "prof")
    reviews.decide(rev["review_id"], "accepted", "Fine", "prof")
    reviews.return_to_student(rev["review_id"], by="prof")
    accounts.authenticate("alice", "wrong password")
    accounts.authenticate("alice", "studentpass")
    actions = [(r["actor"], r["action"]) for r in reversed(audit.read())]
    assert actions[:3] == [("prof", "registered"), ("alice", "registered"), ("ben", "registered")]
    assert actions[3:] == [("prof", "class_created"), ("alice", "joined_class"),
                           ("prof", "assignment_created"), ("alice", "handed_in"), ("prof", "scored"),
                           ("prof", "decided"), ("prof", "returned"), ("alice", "sign_in_failed"),
                           ("alice", "sign_in")]
    assert audit.read(action="sign_in_failed")[0]["details"] == "wrong password"
    assert audit.read(actor="prof", action="decided")[0]["target"] == rev["review_id"]


def test_a_locked_log_never_blocks_the_action(course, excel_lock, caplog):
    excel_lock(paths.audit_path())
    row = submissions.submit(course["assignment"]["assignment_id"], "alice", "an essay " * 20)
    assert submissions.get_submission(row["submission_id"]) is not None
    assert "activity log not written" in caplog.text


def test_the_log_export_is_a_new_file(course):
    path = audit.export(audit.read(), by="prof")
    assert path.parent == paths.reports_dir() and path.read_text(encoding="utf-8").startswith("timestamp,")
    assert audit.read()[0]["action"] == "exported"


# ------------------------------------------------------------ file check
def _problems(findings):
    return {(f["severity"], f["problem"]) for f in findings}


def test_a_clean_classroom_passes_and_nothing_is_changed(course):
    submissions.submit(course["assignment"]["assignment_id"], "alice", "an essay " * 20)
    before = {p: p.read_bytes() for p in paths.DATA_DIR.rglob("*") if p.is_file()}
    findings = integrity.check()
    assert ("info", "all files agree") in _problems(findings)
    assert integrity.summary(findings)["error"] == 0
    after = {p: p.read_bytes() for p in paths.DATA_DIR.rglob("*") if p.is_file()}
    assert after == before


def test_the_file_check_finds_what_went_wrong(course):
    aid = course["assignment"]["assignment_id"]
    gone = submissions.submit(aid, "alice", "first essay " * 20)
    changed = submissions.submit(aid, "alice", "second essay " * 20)
    paths.resolve(gone["text_path"]).unlink()
    paths.resolve(changed["text_path"]).write_text("edited by hand", encoding="utf-8")
    stray = paths.submissions_dir() / "stray" / "v001.txt"
    stray.parent.mkdir(parents=True)
    stray.write_text("copied in", encoding="utf-8")
    reviews.record_detection(dict(gone, submission_id="sub_ghost"), {"label": "NOT DETECTED"},
                             "run1", "fake/model", "", "prof")
    tmp = paths.DATA_DIR / "rosters.csv.tmp"
    tmp.write_text("half", encoding="utf-8")
    old = time.time() - 3600
    os.utime(tmp, (old, old))
    problems = _problems(integrity.check())
    assert {("error", "text file missing"), ("error", "text changed after hand-in"),
            ("warning", "not in the index"), ("warning", "unknown submission"),
            ("warning", "left over from an interrupted write")} <= problems


def test_the_file_check_reports_foreign_columns(course):
    paths.assignments_path().write_text("title,due\nx,y\n", encoding="utf-8")
    assert ("error", "unexpected columns") in _problems(integrity.check())


def test_a_check_is_logged_and_can_be_exported(course):
    findings = integrity.run(by="prof")
    assert audit.read(action="integrity_checked")[0]["details"] == "0 errors, 0 warnings"
    path = integrity.export(findings, by="prof")
    assert path.name.startswith("integrity_") and "severity" in path.read_text(encoding="utf-8")


# ------------------------------------------------------------ backups
def test_a_backup_copy_can_be_put_back_and_the_restore_undone(course):
    first = classes.get_class(course["class"]["class_id"])
    classes.rename_class(first["class_id"], "Renamed class", "Term 2", by="prof")
    copies = [c for c in backups.listing() if c["file"] == "classes.json"]
    before_rename = copies[0]["backup"]                       # newest copy: just before the rename
    assert backups.check_copy(before_rename) == ("classes.json", 1)
    undo = backups.restore(before_rename, by="prof")
    assert classes.get_class(first["class_id"])["name"] == "Intro to writing"
    assert json.loads(undo.read_text(encoding="utf-8"))["classes"][first["class_id"]]["name"] == "Renamed class"
    assert audit.read(action="backup_restored")[0]["target"] == "data/classes.json"


def test_a_damaged_copy_is_never_restored(course):
    classes.rename_class(course["class"]["class_id"], "Renamed", "", by="prof")
    copy = [c for c in backups.listing() if c["file"] == "classes.json"][0]["backup"]
    (paths.backups_dir() / copy).write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be restored"):
        backups.restore(copy, by="prof")
    assert classes.get_class(course["class"]["class_id"])["name"] == "Renamed"
    with pytest.raises(ValueError, match="not a backup copy"):
        backups.check_copy("users.json")


# ------------------------------------------------------------ class zip
def test_a_class_exports_as_one_zip(course, people):
    aid = course["assignment"]["assignment_id"]
    text = "an essay by alice " * 20
    sub = submissions.submit(aid, "alice", text)
    detection.detect_submission(FakeEngine(), threading.Lock(), sub, "prof")
    before = {p: p.read_bytes() for p in paths.DATA_DIR.rglob("*") if p.is_file() and p.suffix != ".csv"
              or p.name in ("submissions.csv", "reviews.csv")}
    path = archive.export_class(course["class"]["class_id"], by="prof")
    assert path.parent == paths.reports_dir() and path.suffix == ".zip"
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        assert {"README.txt", "class.json", "roster.csv", "assignments.csv", "submissions.csv",
                "reviews.csv", "summary.csv"} <= names
        inside = "submissions/{}/alice/v001.txt".format(aid)
        assert z.read(inside).decode("utf-8") == text.strip()
        assert inside[:-4] + ".json" in names
        assert "Intro to writing" in z.read("README.txt").decode("utf-8")
    assert all(p.read_bytes() == b for p, b in before.items())
    assert not list(paths.reports_dir().glob("*.tmp"))


# ------------------------------------------------------------ teacher upload
def test_the_teacher_hands_in_files_named_after_students(course, people):
    aid = course["assignment"]["assignment_id"]
    assignments.close_assignment(aid, by="prof")                  # the teacher may still add work
    result = submissions.import_files(aid, [
        ("alice.txt", "An essay alice e-mailed.".encode("utf-8-sig")),
        ("ALICE.txt", b"again"),
        ("ben.txt", b"ben is not in this class"),
        ("notes.docx", b"PK..."),
        ("carol.txt", b"\xff\xfe\x00bad"),
    ], by="prof")
    assert result["handed_in"] == [("alice.txt", "alice", 1)]
    reasons = dict(result["skipped"])
    assert "second file" in reasons["ALICE.txt"] and "no student ben" in reasons["ben.txt"]
    assert reasons["notes.docx"] == "not a .txt file" and "no student carol" in reasons["carol.txt"]
    sub = submissions.current_submission(aid, "alice")
    assert (sub["source"], sub["upload_filename"]) == ("teacher", "alice.txt")
    assert submissions.read_text(sub) == "An essay alice e-mailed."
    assert audit.read(action="handed_in")[0]["actor"] == "prof"


def test_only_the_teacher_uses_the_teacher_source(course, people):
    aid = course["assignment"]["assignment_id"]
    with pytest.raises(ValueError, match="Only the teacher"):
        submissions.submit(aid, "alice", "text " * 10, "teacher")
    with pytest.raises(ValueError, match="class's teacher"):
        submissions.submit(aid, "alice", "text " * 10, "teacher", by_teacher="alice")
    assert store.KEEP_BACKUPS >= 3
