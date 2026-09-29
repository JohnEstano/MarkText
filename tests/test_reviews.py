import pytest

from classroom import reviews, submissions

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
