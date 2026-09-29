import pytest

from classroom import assignments, reviews, submissions

STATS = {"num_tokens_scored": 146, "num_green_tokens": 106, "green_fraction": 106 / 146,
         "z_score": 5.4612, "p_value": 2.818e-09, "label": "LIKELY MARKTEXT", "device": "cpu"}


def _review(course):
    sub = submissions.submit(course["assignment"]["assignment_id"], "alice", "some essay text")
    return sub, reviews.record_detection(sub, STATS, "run12345", "fake/model", "0a1b2c3d", "prof")


def test_record_detection_snapshots_the_numbers(course):
    sub, rev = _review(course)
    assert rev["review_id"].startswith("rev_") and rev["submission_id"] == sub["submission_id"]
    assert (rev["tokens_scored"], rev["green_pct"], rev["z_score"], rev["p_value"]) == \
        ("146", "72.6", "5.46", "2.818e-09")
    assert rev["decision"] == "pending" and rev["returned"] == "0"
    assert rev["run_id"] == "run12345" and rev["key_id"] == "0a1b2c3d"
    assert reviews.latest_review(sub["submission_id"]) == rev


def test_decide_and_return(course):
    _, rev = _review(course)
    with pytest.raises(ValueError, match="decision before"):
        reviews.return_to_student(rev["review_id"], by="prof")
    with pytest.raises(ValueError, match="Choose"):
        reviews.decide(rev["review_id"], "pending", decided_by="prof")
    with pytest.raises(ValueError, match="teacher"):
        reviews.decide(rev["review_id"], "flagged", decided_by="alice")
    assert reviews.decide(rev["review_id"], "flagged", "Drafted with the assistant?", "prof").exists()
    reviews.return_to_student(rev["review_id"], by="prof")
    after = reviews.get_review(rev["review_id"])
    assert after["decision"] == "flagged" and after["returned"] == "1" and after["decided_by"] == "prof"
    assert after["z_score"] == "5.46"                     # measurement untouched
    with pytest.raises(ValueError, match="Not editable"):
        reviews.update_review(rev["review_id"], z_score="0")


def test_scoring_again_keeps_the_decision(course):
    sub, rev = _review(course)
    reviews.decide(rev["review_id"], "accepted", "fine", "prof")
    again = reviews.record_detection(sub, dict(STATS, z_score=0.1, label="NOT DETECTED"),
                                     "run999", "fake/model", "0a1b2c3d", "prof")
    assert again["review_id"] != rev["review_id"]
    assert again["decision"] == "accepted" and again["note"] == "fine"
    assert reviews.latest_review(sub["submission_id"])["review_id"] == again["review_id"]
    assert len(reviews.list_reviews(latest_only=False)) == 2
    assert len(reviews.list_reviews()) == 1


def test_a_decision_changed_after_return_waits_for_the_next_return(course):
    _, rev = _review(course)
    rid = rev["review_id"]
    reviews.decide(rid, "accepted", "Well argued.", "prof")
    reviews.return_to_student(rid, by="prof")
    shown = reviews.shown_to_student(reviews.get_review(rid))
    assert (shown["decision"], shown["note"]) == ("accepted", "Well argued.")
    # the teacher changes their mind: the student keeps seeing what was returned
    reviews.decide(rid, "flagged", "Please come and see me.", "prof")
    after = reviews.get_review(rid)
    assert reviews.changed_since_return(after)
    assert reviews.shown_to_student(after)["decision"] == "accepted"
    reviews.return_to_student(rid, by="prof")
    again = reviews.get_review(rid)
    assert not reviews.changed_since_return(again)
    assert reviews.shown_to_student(again) == {"decision": "flagged", "note": "Please come and see me.",
                                               "points": "", "returned_at": again["returned_at"]}


def test_a_row_returned_before_the_snapshot_columns_shows_its_decision(course):
    _, rev = _review(course)
    reviews.decide(rev["review_id"], "accepted", "ok", "prof")
    reviews.update_review(rev["review_id"], returned="1", returned_at="2026-09-29 10:00:00")
    old = reviews.get_review(rev["review_id"])
    assert old["returned_decision"] == ""
    assert reviews.shown_to_student(old)["decision"] == "accepted"
    assert not reviews.changed_since_return(old)


def test_nothing_is_shown_before_a_return(course):
    _, rev = _review(course)
    reviews.decide(rev["review_id"], "flagged", "", "prof")
    assert reviews.shown_to_student(reviews.get_review(rev["review_id"])) is None
    assert reviews.shown_to_student(None) is None


def test_the_strongest_passage_is_kept_with_the_review(course):
    sub = submissions.submit(course["assignment"]["assignment_id"], "alice", "some essay text")
    passage = {"z": 5.01, "p": 1.2e-5, "start": 120, "end": 860, "decisive": True}
    rev = reviews.record_detection(sub, dict(STATS, repeated=2, passage=passage), "run1", "fake/model",
                                   "0a1b2c3d", "prof")
    assert (rev["passage_z"], rev["passage_p"], rev["passage_start"], rev["passage_end"]) == \
        ("5.01", "1.200e-05", "120", "860")
    assert rev["repeated"] == "2"
    plain = reviews.record_detection(sub, STATS, "run2", "fake/model", "0a1b2c3d", "prof")
    assert plain["passage_z"] == "" and plain["passage_start"] == ""


def test_points_are_checked_kept_and_returned(course):
    task = course["assignment"]
    sub, rev = _review(course)
    with pytest.raises(ValueError, match="no points"):
        reviews.decide(rev["review_id"], "accepted", "", "prof", points=5)
    assignments.update_assignment(task["assignment_id"], by="prof", points=10)
    with pytest.raises(ValueError, match="0 to 10"):
        reviews.decide(rev["review_id"], "accepted", "", "prof", points=11)
    with pytest.raises(ValueError, match="steps of 0.5"):
        reviews.decide(rev["review_id"], "accepted", "", "prof", points=7.25)
    reviews.decide(rev["review_id"], "accepted", "Good", "prof", points=8.5)
    reviews.return_to_student(rev["review_id"], by="prof")
    assert reviews.shown_to_student(reviews.get_review(rev["review_id"]))["points"] == "8.5"
    reviews.decide(rev["review_id"], "accepted", "Good", "prof", points=9)
    changed = reviews.get_review(rev["review_id"])
    assert reviews.changed_since_return(changed)                    # new points wait for a return
    assert reviews.shown_to_student(changed)["points"] == "8.5"
    reviews.decide(rev["review_id"], "accepted", "Good", "prof")   # points=None keeps them
    assert reviews.get_review(rev["review_id"])["points"] == "9"
