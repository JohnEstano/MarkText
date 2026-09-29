import csv
import datetime
import threading

import pytest
from fakes import FakeEngine

from classroom import accounts, classes, detection, paths, reports, reviews, submissions, seed_demo


@pytest.fixture
def five_states(course):
    """alice returned, ben not submitted, carl awaiting detection,
    dan awaiting decision, eve decided."""
    for u in ("carl", "dan", "eve"):
        accounts.register(u, "studentpass", "student")
    cls, task = course["class"], course["assignment"]
    for u in ("ben", "carl", "dan", "eve"):
        classes.join_class(cls["join_code"], u)
    eng, lock = FakeEngine(), threading.Lock()
    aid = task["assignment_id"]
    for u in ("alice", "dan", "eve"):
        sub = submissions.submit(aid, u, "an essay by {} ".format(u) + "word " * 120)
        detection.detect_submission(eng, lock, sub, "prof")
    submissions.submit(aid, "carl", "carl essay " + "word " * 120)
    by_user = {r["username"]: r for r in reviews.list_reviews(assignment_id=aid)}
    reviews.decide(by_user["eve"]["review_id"], "accepted", "Thanks", "prof")
    reviews.decide(by_user["alice"]["review_id"], "flagged", "Talk to me", "prof")
    reviews.return_to_student(by_user["alice"]["review_id"], by="prof")
    return course


def test_assignment_frame_has_every_student_in_the_right_state(five_states):
    frame = reports.assignment_frame(five_states["assignment"]["assignment_id"])
    states = dict(zip(frame["username"], frame["state"]))
    assert states == {"alice": "returned", "ben": "not submitted", "carl": "awaiting detection",
                      "dan": "awaiting decision", "eve": "decided"}
    alice = frame[frame["username"] == "alice"].iloc[0]
    assert alice["display_name"] == "Alice Santos" and bool(alice["returned"])
    assert alice["z_score"] == -0.5 and alice["decision"] == "flagged"
    assert reports.state_counts(frame) == {s: 1 for s in reports.STATES}


def test_class_summary_counts(five_states):
    s = reports.class_summary(five_states["class"]["class_id"]).iloc[0]
    assert (s["students"], s["submitted"], s["detected"], s["not_detected"]) == (5, 4, 3, 3)
    assert (s["accepted"], s["flagged"], s["returned"], s["mean_z"]) == (1, 1, 1, -0.5)


def test_exports_are_new_files_that_read_back(five_states):
    aid = five_states["assignment"]["assignment_id"]
    path = reports.export_assignment_report(aid)
    assert path.parent == paths.reports_dir()
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["username"] for r in rows] == ["alice", "ben", "carl", "dan", "eve"]
    assert list(rows[0]) == reports.REPORT_COLUMNS
    assert rows[1]["z_score"] == "" and rows[1]["state"] == "not submitted"
    assert reports.export_assignment_report(aid) != path
    summary = reports.export_class_summary(five_states["class"]["class_id"])
    assert summary.exists() and summary.name.startswith("class_")


def test_teacher_overview(five_states):
    o = reports.teacher_overview("prof")
    assert (o["classes"], o["students"], o["open_assignments"]) == (1, 5, 1)
    assert (o["awaiting_detection"], o["awaiting_decision"]) == (1, 1)
    assert o["queue"][0]["title"] == "Why people keep diaries"
    assert [f["student"] for f in o["recent_flags"]] == ["Alice Santos"]     # flagged decision


def test_student_overview_hides_the_detector(five_states):
    alice = reports.student_overview("alice")[0]
    assert alice["my_state"] == "returned" and alice["decision"] == "flagged"
    assert alice["note"] == "Talk to me"
    assert "z_score" not in alice and "label" not in alice
    eve = reports.student_overview("eve")[0]
    assert eve["my_state"] == "submitted" and eve["decision"] == "" and eve["note"] == ""
    assert reports.student_overview("ben")[0]["my_state"] == "not submitted"


def test_seed_demo_with_a_model(data_dir):
    summary = seed_demo.seed(engine=FakeEngine(), lock=threading.Lock())
    assert summary["teacher"] == "prof" and summary["drafted"] and summary["scored"] == 5
    assert accounts.authenticate("prof", seed_demo.DEMO_PASSWORD)
    frame = reports.assignment_frame(summary["assignment_id"])
    labels = dict(zip(frame["username"], frame["label"]))
    assert labels["dan"] == "LIKELY MARKTEXT"
    assert {labels[u] for u in seed_demo.WRITERS} == {"NOT DETECTED"}
    assert set(frame["state"]) == {"awaiting decision"}


def test_seed_demo_without_a_model_and_for_an_existing_teacher(data_dir):
    accounts.register("nash", "teacherpass", "teacher")
    summary = seed_demo.seed(teacher="nash")
    assert summary["teacher"] == "nash" and not summary["drafted"] and summary["scored"] == 0
    frame = reports.assignment_frame(summary["assignment_id"])
    assert reports.state_counts(frame)["awaiting detection"] == 4
    assert reports.state_counts(frame)["not submitted"] == 1
    assert not accounts.exists("prof")
    with pytest.raises(ValueError, match="not a teacher"):
        seed_demo.seed(teacher="alice")


def test_archive_moves_the_data_folder(data_dir):
    accounts.register("nash", "teacherpass", "teacher")
    moved = seed_demo.archive_data()
    assert moved.name.startswith("data.archived_") and (moved / "users.json").exists()
    assert not accounts.exists("nash") and paths.DATA_DIR.exists()


def test_overview_counts_each_student_once_per_assignment(course):
    eng, lock = FakeEngine(), threading.Lock()
    aid = course["assignment"]["assignment_id"]
    for text in ("wm " * 150, "wm " * 160):
        sub = submissions.submit(aid, "alice", text)
        detection.detect_submission(eng, lock, sub, "prof")
    o = reports.teacher_overview("prof")
    assert o["flagged"] == 1 and len(o["recent_flags"]) == 1
    assert o["recent_flags"][0]["version"] == 2 and o["scored"] == 1
    assert (o["handed_in"], o["handed_in_week"]) == (2, 2)
    assert len(o["handed_in_daily"]) == 14 and o["handed_in_daily"][-1] == 2
    row = o["class_rows"][0]
    assert (row["students"], row["open"], row["to_decide"]) == (1, 1, 1)
    assert row["join_code"] == classes.format_code(course["class"]["join_code"])


def test_recent_daily_counts_and_due_soon():
    now = datetime.datetime(2026, 9, 29, 12, 0, 0)
    assert reports.recent("2026-09-25 08:00:00", now=now)
    assert not reports.recent("2026-09-20 08:00:00", now=now)
    assert not reports.recent("", now=now) and not reports.recent("2026-10-01 08:00:00", now=now)
    counts = reports.daily_counts(["2026-09-29 01:00:00", "2026-09-28 23:00:00",
                                   "2026-09-10 10:00:00", "junk"], days=3, now=now)
    assert counts == [0, 1, 1]
    today = datetime.date(2026, 9, 29)
    assert reports.due_soon("2026-10-02", today=today) and reports.due_soon("2026-09-29", today=today)
    assert not reports.due_soon("2026-10-20", today=today) and not reports.due_soon("", today=today)
