import copy
import json
import threading

import pytest
from fakes import FakeEngine

import history
from classroom import assistant, classes, detection, paths, reviews, store, submissions


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


def test_old_scores_are_scored_again_and_keep_the_decision(course):
    aid = course["assignment"]["assignment_id"]
    sub = submissions.submit(aid, "alice", "a human essay " * 40)
    old_stats = {"num_tokens_scored": 150, "green_fraction": 0.62, "z_score": 4.14, "p_value": 1.7e-5,
                 "label": "LIKELY MARKTEXT", "device": "cpu"}      # no "repeated": the old counting
    old = reviews.record_detection(sub, old_stats, "run1", "fake/model", "0a1b2c3d", "prof")
    reviews.decide(old["review_id"], "flagged", "Looks drafted.", "prof")
    assert [s["submission_id"] for s in detection.old_scores(aid)] == [sub["submission_id"]]
    run = detection.detect_many(FakeEngine(), threading.Lock(), detection.old_scores(aid), "prof")
    new = run["written"][0]
    assert new["label"] == "NOT DETECTED" and new["repeated"] == "0"
    assert (new["decision"], new["note"]) == ("flagged", "Looks drafted.")      # carried over
    assert detection.old_scores(aid) == []


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

    def stop_after_first(done, total, submission, review):
        seen.append((done, total, submission["username"], review["username"]))
        cancel.set()
    run = detection.detect_many(FakeEngine(), threading.Lock(), todo, "prof",
                                on_progress=stop_after_first, cancel_event=cancel)
    assert len(run["written"]) == 1 and seen == [(1, 2, "alice", "alice")]
    assert run["skipped"] == [] and run["stopped"] is None
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


def _two_waiting(course, people):
    task = course["assignment"]
    classes.join_class(course["class"]["join_code"], "ben")
    for who in ("alice", "ben"):
        submissions.submit(task["assignment_id"], who, "an essay by a person " * 20)
    return detection.pending(task["assignment_id"])


def test_a_reviews_file_open_in_excel_stops_scoring_before_anything_is_written(
        course, people, excel_lock):
    todo = _two_waiting(course, people)
    excel_lock(paths.reviews_path())
    run = detection.detect_many(FakeEngine(), threading.Lock(), todo, "prof")
    assert run["written"] == [] and "data/reviews.csv" in run["stopped"]
    assert "Excel" in run["stopped"]
    assert history.read_history() == [] and reviews.list_reviews(latest_only=False) == []
    excel_lock.release(paths.reviews_path())
    run = detection.detect_many(FakeEngine(), threading.Lock(), todo, "prof")
    assert len(run["written"]) == 2 and len(history.read_history()) == 2


def test_a_review_that_cannot_be_written_takes_its_log_row_back_out(course, monkeypatch):
    sub = submissions.submit(course["assignment"]["assignment_id"], "alice", "an essay " * 30)

    def refuse(*args, **kwargs):
        raise store.FileProblem(paths.reviews_path(), "write to", PermissionError(13, "denied"))
    monkeypatch.setattr(reviews, "record_detection", refuse)
    with pytest.raises(store.FileProblem):
        detection.detect_submission(FakeEngine(), threading.Lock(), sub, "prof")
    assert history.read_history() == []


def test_a_missing_text_is_skipped_and_the_rest_are_scored(course, people):
    todo = _two_waiting(course, people)
    paths.resolve(todo[0]["text_path"]).unlink()
    seen = []
    run = detection.detect_many(FakeEngine(), threading.Lock(), todo, "prof",
                                on_progress=lambda d, t, s, r: seen.append((s["username"], r is None)))
    assert [s["username"] for s, _ in run["skipped"]] == ["alice"]
    assert "missing" in run["skipped"][0][1] and run["stopped"] is None
    assert [r["username"] for r in run["written"]] == ["ben"]
    assert seen == [("alice", True), ("ben", False)]


def test_a_draft_is_scored_with_the_key_it_was_made_with(course):
    old = FakeEngine()                                             # key id 0a1b2c3d
    info = assistant.draft(old, threading.Lock(), "Write about diaries", 150)
    sub = submissions.submit(course["assignment"]["assignment_id"], "alice", info["text"], "assistant",
                             generation=assistant.generation_record(info, "Write about diaries"))
    assert detection.drafted_with(sub) == "0a1b2c3d"
    new_config = copy.deepcopy(old.config)
    new_config["watermark"].update(hashing_key=777, key_id="ffff0000")
    new = FakeEngine(new_config)
    engines = {"0a1b2c3d": old, "ffff0000": new}
    run = detection.detect_many(new, threading.Lock(), [sub], "prof",
                                pick=lambda s: (engines[detection.drafted_with(s) or "ffff0000"],
                                                threading.Lock()))
    assert run["written"][0]["key_id"] == "0a1b2c3d"
