import datetime

import pytest

from classroom import assignments, classes


def test_create_validates_owner_title_and_due_date(people):
    cls = classes.create_class("Intro", "prof")
    with pytest.raises(ValueError, match="teacher"):
        assignments.create_assignment(cls["class_id"], "Essay", created_by="alice")
    with pytest.raises(ValueError, match="title"):
        assignments.create_assignment(cls["class_id"], "  ", created_by="prof")
    with pytest.raises(ValueError, match="2026-10-15"):
        assignments.create_assignment(cls["class_id"], "Essay", due_at="15/10/2026", created_by="prof")
    a = assignments.create_assignment(cls["class_id"], "  Essay  one ", "Write\n200 words.",
                                      datetime.date(2026, 10, 15), "prof")
    assert a["title"] == "Essay one" and a["due_at"] == "2026-10-15" and a["status"] == "open"
    assert assignments.get_assignment(a["assignment_id"])["instructions"] == "Write\n200 words."


def test_update_close_and_reopen(course):
    a = course["assignment"]
    with pytest.raises(ValueError, match="Not editable"):
        assignments.update_assignment(a["assignment_id"], by="prof", created_by="alice")
    with pytest.raises(ValueError, match="teacher"):
        assignments.close_assignment(a["assignment_id"], by="alice")
    assert assignments.close_assignment(a["assignment_id"], by="prof").exists()
    assert assignments.get_assignment(a["assignment_id"])["status"] == "closed"
    assert assignments.open_for_student("alice") == []
    assignments.reopen_assignment(a["assignment_id"], by="prof")
    assert [x["assignment_id"] for x in assignments.open_for_student("alice")] == [a["assignment_id"]]


def test_student_sees_only_their_classes_soonest_first(course, people):
    cls = course["class"]
    later = assignments.create_assignment(cls["class_id"], "Later", due_at="2026-12-01", created_by="prof")
    undated = assignments.create_assignment(cls["class_id"], "Whenever", created_by="prof")
    other = classes.create_class("Other", "prof")
    assignments.create_assignment(other["class_id"], "Not yours", created_by="prof")
    titles = [a["title"] for a in assignments.open_for_student("alice")]
    assert titles == ["Why people keep diaries", "Later", "Whenever"]
    assert assignments.open_for_student("ben") == []
    assert later and undated


def test_overdue():
    a = {"due_at": "2026-10-15"}
    assert assignments.is_overdue(a, datetime.date(2026, 10, 16))
    assert not assignments.is_overdue(a, datetime.date(2026, 10, 15))
    assert not assignments.is_overdue({"due_at": ""})


def test_overdue_reads_dates_saved_by_excel_and_ignores_garbage():
    today = datetime.date(2026, 10, 20)
    assert assignments.is_overdue({"due_at": "10/15/2026"}, today)
    assert not assignments.is_overdue({"due_at": "next week"}, today)
    assert not assignments.is_overdue({"due_at": ""}, today)


def test_points_and_lateness(course):
    aid = course["assignment"]["assignment_id"]                   # due 2026-10-15
    assert assignments.max_points(course["assignment"]) is None
    assignments.update_assignment(aid, by="prof", points=20)
    task = assignments.get_assignment(aid)
    assert assignments.max_points(task) == 20
    for bad in (0, 1001, 2.5, "ten"):
        with pytest.raises(ValueError):
            assignments.update_assignment(aid, by="prof", points=bad)
    assert not assignments.is_late(task, "2026-10-15 23:59:00")       # the whole due day counts
    assert assignments.is_late(task, "2026-10-16 00:00:01")
    assert not assignments.is_late(dict(task, due_at=""), "2030-01-01 00:00:00")
