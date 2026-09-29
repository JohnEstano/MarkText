import json
import threading

from fakes import FakeEngine

import history
from classroom import assistant, classes, detection, reviews, submissions


def test_one_detection_writes_the_log_and_the_review(course):
    task = course["assignment"]
    sub = submissions.submit(task["assignment_id"], "alice", "a human essay " * 40)
    rev = detection.detect_submission(FakeEngine(), threading.Lock(), sub, "prof")
    rows = history.read_history()
    assert len(rows) == 1
    log = rows[0]
    assert log["source"] == "submission" and log["run_id"] == rev["run_id"]
    assert log["filename"] == "data/" + sub["text_path"]
    note = json.loads(log["note"])
    assert note == {"class_id": sub["class_id"], "assignment_id": task["assignment_id"],
                    "submission_id": sub["submission_id"], "username": "alice", "version": 1}
    assert (log["z_score"], log["tokens_scored"], log["result"]) == \
        (rev["z_score"], rev["tokens_scored"], rev["label"])
    assert rev["label"] == "NOT DETECTED" and rev["model_id"] == "fake/model"
    assert rev["key_id"] == "0a1b2c3d"


def test_assistant_draft_is_logged_with_its_provenance(course):
    eng, lock = FakeEngine(), threading.Lock()
    task = course["assignment"]
    info = assistant.draft(eng, lock, "Write about diaries", 120)
    sub = submissions.submit(task["assignment_id"], "alice", info["text"], "assistant",
                             generation=assistant.generation_record(info, "Write about diaries"))
    rev = detection.detect_submission(eng, lock, sub, "prof")
    assert rev["label"] == "LIKELY MARKTEXT"
    log = history.find_record(rev["run_id"])
    assert log["mode"] == "watermarked" and log["seed"] == "42" and log["gen_tokens"] == "120"


def test_text_too_short_to_score_is_inconclusive(course):
    sub = submissions.submit(course["assignment"]["assignment_id"], "alice", "Too short.")
    rev = detection.detect_submission(FakeEngine(), threading.Lock(), sub, "prof")
    assert rev["label"] == "INCONCLUSIVE (short text)" and rev["tokens_scored"] == "0"


def test_pending_and_detect_many_with_progress_and_cancel(course, people):
    task = course["assignment"]
    classes.join_class(course["class"]["join_code"], "ben")
    for who in ("alice", "ben"):
        submissions.submit(task["assignment_id"], who, "essay by " + who + " " * 1 + "word " * 30)
    todo = detection.pending(task["assignment_id"])
    assert [s["username"] for s in todo] == ["alice", "ben"]

    cancel, seen = threading.Event(), []

    def stop_after_first(done, total, review):
        seen.append((done, total, review["username"]))
        cancel.set()
    written = detection.detect_many(FakeEngine(), threading.Lock(), todo, "prof",
                                    on_progress=stop_after_first, cancel_event=cancel)
    assert len(written) == 1 and seen == [(1, 2, "alice")]
    assert [s["username"] for s in detection.pending(task["assignment_id"])] == ["ben"]
    # a student who leaves the class drops out of the queue
    classes.remove_student(course["class"]["class_id"], "ben")
    assert detection.pending(task["assignment_id"]) == []


def test_reviews_survive_clearing_the_lab_history(course):
    sub = submissions.submit(course["assignment"]["assignment_id"], "alice", "essay " * 30)
    rev = detection.detect_submission(FakeEngine(), threading.Lock(), sub, "prof")
    history.clear_history()
    assert history.read_history() == []
    kept = reviews.latest_review(sub["submission_id"])
    assert kept["z_score"] == rev["z_score"] and kept["run_id"] == rev["run_id"]
