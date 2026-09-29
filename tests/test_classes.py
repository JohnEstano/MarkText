import csv

import pytest

from classroom import accounts, classes, paths


def test_join_codes_are_readable_and_normalised():
    code = classes.new_join_code()
    assert len(code) == 6 and set(code) <= set(classes.CODE_ALPHABET)
    assert not set(code) & set("01OI")
    assert classes.format_code("ABC234") == "ABC-234"
    assert classes.normalise_code(" abc-234 ") == "ABC234"
    assert classes.new_join_code({"AAAAAA"}) != "AAAAAA"


def test_only_teachers_create_classes_and_codes_are_unique(people):
    with pytest.raises(ValueError, match="teacher"):
        classes.create_class("Hack", "alice")
    with pytest.raises(ValueError, match="name"):
        classes.create_class("   ", "prof")
    a = classes.create_class("Intro to writing", "prof", "Term 1")
    b = classes.create_class("Research methods", "prof")
    assert a["class_id"].startswith("cls_") and a["join_code"] != b["join_code"]
    assert [c["name"] for c in classes.list_classes("prof")] == ["Research methods", "Intro to writing"]


def test_join_with_code_is_case_insensitive_and_once(people):
    cls = classes.create_class("Intro", "prof")
    code = classes.format_code(cls["join_code"]).lower()
    assert classes.join_class(code, "Alice")["class_id"] == cls["class_id"]
    assert classes.is_member(cls["class_id"], "alice")
    with pytest.raises(ValueError, match="already"):
        classes.join_class(cls["join_code"], "alice")
    with pytest.raises(ValueError, match="No class"):
        classes.join_class("ZZZ-ZZZ", "ben")
    with pytest.raises(ValueError, match="Only students"):
        classes.join_class(cls["join_code"], "prof")
    assert classes.classes_for_student("alice")[0]["name"] == "Intro"
    assert classes.student_counts() == {cls["class_id"]: 1}


def test_rotating_the_code_keeps_members(people):
    cls = classes.create_class("Intro", "prof")
    classes.join_class(cls["join_code"], "alice")
    with pytest.raises(ValueError, match="teacher"):
        classes.rotate_join_code(cls["class_id"], by="alice")
    new = classes.rotate_join_code(cls["class_id"], by="prof")
    assert new != cls["join_code"]
    with pytest.raises(ValueError):
        classes.join_class(cls["join_code"], "ben")       # the old code is dead
    classes.join_class(new, "ben")
    assert classes.is_member(cls["class_id"], "alice") and classes.is_member(cls["class_id"], "ben")


def test_remove_keeps_the_row_and_blocks_rejoining(people):
    cls = classes.create_class("Intro", "prof")
    classes.join_class(cls["join_code"], "alice")
    saved = classes.remove_student(cls["class_id"], "alice", by="prof")
    assert saved.exists()
    row = classes.membership(cls["class_id"], "alice")
    assert row["status"] == "removed" and row["removed_at"]
    assert not classes.is_member(cls["class_id"], "alice")
    with pytest.raises(ValueError, match="removed"):
        classes.join_class(cls["join_code"], "alice")
    with pytest.raises(ValueError):
        classes.remove_student(cls["class_id"], "alice", by="prof")   # nothing active left


def test_import_enrols_invites_and_skips(people):
    accounts.register("carl", "studentpass", "student")
    cls = classes.create_class("Intro", "prof")
    classes.join_class(cls["join_code"], "carl")
    rows = classes.parse_roster_csv(
        "Username,Email\nalice,a@x.test\nBEN,\ncarl,\nprof,\nnew.student,\nbad name,\nalice,\n".encode("utf-8"))
    result = classes.import_roster(cls["class_id"], rows, by="prof")
    assert result["enrolled"] == ["alice", "ben"]
    assert result["invited"] == ["new.student"]
    reasons = dict(result["skipped"])
    assert reasons == {"carl": "already in the class", "prof": "is a teacher account",
                       "bad name": "not a valid username", "alice": "listed twice"}
    assert classes.membership(cls["class_id"], "new.student")["status"] == "invited"
    # registering alone does not make a member (anyone could register that
    # name first); joining with the class code accepts the invitation
    accounts.register("new.student", "studentpass", "student")
    assert not classes.is_member(cls["class_id"], "new.student")
    classes.join_class(cls["join_code"], "new.student")
    row = classes.membership(cls["class_id"], "new.student")
    assert row["status"] == "active" and row["added_via"] == "import"


def test_roster_file_needs_a_username_column():
    with pytest.raises(ValueError, match="username"):
        classes.parse_roster_csv(b"name\nalice\n")
    with pytest.raises(ValueError, match="UTF-8"):
        classes.parse_roster_csv(b"\xff\xfeu\x00")
    assert classes.parse_roster_csv("﻿username\nalice\n".encode("utf-8")) == [{"username": "alice"}]


def test_export_roster_writes_a_new_file_with_names(people):
    cls = classes.create_class("Intro", "prof")
    classes.join_class(cls["join_code"], "alice")
    classes.import_roster(cls["class_id"], [{"username": "ghost"}])
    path = classes.export_roster(cls["class_id"])
    assert path.parent == paths.reports_dir() and path.name.startswith("roster_" + cls["class_id"])
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [(r["username"], r["display_name"], r["status"]) for r in rows] == [
        ("alice", "Alice Santos", "active"), ("ghost", "", "invited")]
    assert classes.export_roster(cls["class_id"]) != path          # never overwrites


def test_archived_classes_are_hidden_and_closed_to_joining(people):
    cls = classes.create_class("Old", "prof")
    classes.set_archived(cls["class_id"], True, by="prof")
    assert classes.list_classes("prof") == []
    assert classes.list_classes("prof", include_archived=True)[0]["archived"] is True
    with pytest.raises(ValueError):
        classes.join_class(cls["join_code"], "alice")
