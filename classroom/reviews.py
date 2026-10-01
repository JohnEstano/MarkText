"""The teacher's review of each submission, one row per detection in
data/reviews.csv.

A row is written when a submission is scored (classroom/detection.py) and
holds a snapshot of the measurement (tokens, green share, z, p, label) plus
which model and key produced it. The teacher then records a decision and a
note and returns it to the student. Measurements are never edited: only the
EDITABLE fields change, each time with a backup. Scoring a submission again
appends a new row that carries the decision over; the latest row wins.

Returning copies the decision and the note into returned_decision and
returned_note, and the student only ever sees that copy. A teacher who
changes a decision after returning it is editing a draft: the student keeps
seeing what was returned until the work is returned again (the way Google
Classroom treats a changed grade). Rows written before these two columns
existed have them empty and show the decision itself.
"""

import verdict
from classroom import assignments, audit, classes, paths, store

COLUMNS = ["review_id", "submission_id", "assignment_id", "class_id", "username", "version",
           "run_id", "model_id", "key_id", "device", "tokens_scored", "green_pct", "z_score",
           "p_value", "label", "detected_at", "detected_by", "decision", "note", "returned",
           "returned_at", "decided_by", "decided_at", "returned_decision", "returned_note",
           "repeated", "passage_z", "passage_p", "passage_start", "passage_end", "points",
           "returned_points"]
DECISIONS = ("pending", "accepted", "flagged", "needs_review")
DECISION_LABELS = {"pending": "Pending", "accepted": "Accepted", "flagged": "Flagged",
                   "needs_review": "Needs review"}
EDITABLE = ("decision", "note", "returned", "returned_at", "decided_by", "decided_at",
            "returned_decision", "returned_note", "points", "returned_points")
CARRIED_OVER = EDITABLE
MAX_NOTE = 1000


def _rows():
    return store.read_rows(paths.reviews_path(), COLUMNS)


def record_detection(submission, stats, run_id, model_id, key_id, detected_by):
    """Append the review row for one scoring of a submission and return it."""
    previous = latest_review(submission["submission_id"])
    passage = stats.get("passage")
    row = {
        "review_id": store.new_id("rev"),
        "submission_id": submission["submission_id"],
        "assignment_id": submission["assignment_id"],
        "class_id": submission["class_id"],
        "username": submission["username"],
        "version": submission["version"],
        "run_id": run_id,
        "model_id": model_id,
        "key_id": key_id or "",
        "device": stats.get("device", ""),
        "tokens_scored": stats.get("num_tokens_scored", 0),
        "green_pct": round(stats.get("green_fraction", 0.0) * 100, 2),
        "z_score": round(stats.get("z_score", 0.0), 2),
        "p_value": "{:.3e}".format(stats.get("p_value", 1.0)),
        "label": stats.get("label", ""),
        "detected_at": store.now(),
        "detected_by": detected_by,
        "decision": "pending", "note": "", "returned": "0", "returned_at": "",
        "decided_by": "", "decided_at": "", "returned_decision": "", "returned_note": "",
        # the strongest passage (scorer.py), with its characters in the text
        "repeated": stats.get("repeated", ""),
        "passage_z": round(passage["z"], 2) if passage else "",
        "passage_p": "{:.3e}".format(passage["p"]) if passage else "",
        "passage_start": passage.get("start", "") if passage else "",
        "passage_end": passage.get("end", "") if passage else "",
        "points": "", "returned_points": "",
    }
    if previous:
        row.update({k: previous.get(k, "") for k in CARRIED_OVER})
    store.append_row(paths.reviews_path(), COLUMNS, row)
    return {k: str(v) for k, v in row.items()}


def latest_by_submission(assignment_id=None):
    """submission_id -> its latest review row (file order: the last one wins)."""
    latest = {}
    for row in _rows():
        if assignment_id is None or row["assignment_id"] == assignment_id:
            latest[row["submission_id"]] = row
    return latest


def latest_review(submission_id):
    found = None
    for row in _rows():
        if row["submission_id"] == submission_id:
            found = row
    return found


def get_review(review_id):
    for row in _rows():
        if row["review_id"] == review_id:
            return row
    return None


def scorings(submission_id):
    """Every review row of one submission, oldest first: one per scoring."""
    return [row for row in _rows() if row["submission_id"] == submission_id]


def counted_every_repeat(review):
    """True for a score made before repeats counted once (2026-09-30). The
    old counting included every repeated token, which pushes z up on human
    text, so its verdict may be out of date; scoring the text again gives
    the current verdict and keeps the decision (CARRIED_OVER). Such rows
    have no `repeated` value. A text too short to score has none either,
    but it stays inconclusive however repeats are counted."""
    if review is None:
        return False
    return (str(review.get("repeated", "")).strip() == ""
            and review.get("label", "") not in ("", verdict.LABEL_INCONCLUSIVE))


def list_reviews(assignment_id=None, class_id=None, username=None, latest_only=True):
    """Newest detection first."""
    rows = list(latest_by_submission().values()) if latest_only else _rows()
    rows = [r for r in rows
            if (assignment_id is None or r["assignment_id"] == assignment_id)
            and (class_id is None or r["class_id"] == class_id)
            and (username is None or r["username"] == username)]
    return sorted(rows, key=lambda r: r["detected_at"], reverse=True)


def _check_teacher(review, by):
    if by is None:
        return
    record = classes.get_class(review["class_id"])
    if record is None or record["teacher"] != by:
        raise ValueError("Only the class's teacher can review this submission.")


def update_review(review_id, by=None, **fields):
    """Change the teacher's fields of one review. Returns the backup path."""
    bad = [k for k in fields if k not in EDITABLE]
    if bad:
        raise ValueError("Not editable: {}".format(", ".join(bad)))
    review = get_review(review_id)
    if review is None:
        raise ValueError("There is no review {}.".format(review_id))
    _check_teacher(review, by)
    return store.update_one(paths.reviews_path(), COLUMNS, "review_id", review_id,
                            lambda r: dict(r, **{k: str(v) for k, v in fields.items()}))


def _check_points(review_id, points):
    """'' or a number from 0 to the assignment's points (halves allowed)."""
    if points in (None, ""):
        return ""
    review = get_review(review_id)
    task = assignments.get_assignment(review["assignment_id"]) if review else None
    top = assignments.max_points(task) if task else None
    if top is None:
        raise ValueError("This assignment has no points; set them on the Classes page first.")
    try:
        value = float(points)
    except (TypeError, ValueError) as exc:
        raise ValueError("Points are a number.") from exc
    if not 0 <= value <= top or value * 2 != int(value * 2):
        raise ValueError("Points are from 0 to {}, in steps of 0.5.".format(top))
    return "{:g}".format(value)


def decide(review_id, decision, note="", decided_by="", points=None):
    """Record the teacher's decision, note and (for a graded assignment)
    points. points=None leaves the points as they are."""
    if decision not in DECISIONS or decision == "pending":
        raise ValueError("Choose accepted, flagged or needs review.")
    note = (note or "").strip()
    if len(note) > MAX_NOTE:
        raise ValueError("Notes are limited to {} characters.".format(MAX_NOTE))
    fields = {"decision": decision, "note": note, "decided_by": decided_by, "decided_at": store.now()}
    if points is not None:
        fields["points"] = _check_points(review_id, points)
    saved = update_review(review_id, by=decided_by or None, **fields)
    audit.record(decided_by, "decided", review_id, decision)
    return saved


def return_to_student(review_id, by=None):
    """Show the student the decision and the note as they are now."""
    review = get_review(review_id)
    if review is None:
        raise ValueError("There is no review {}.".format(review_id))
    if review["decision"] == "pending":
        raise ValueError("Record a decision before returning the work.")
    saved = update_review(review_id, by=by, returned="1", returned_at=store.now(),
                          returned_decision=review["decision"], returned_note=review["note"],
                          returned_points=review.get("points", ""))
    audit.record(by, "returned", review_id, review["decision"])
    return saved


def is_returned(review):
    return review is not None and review.get("returned") == "1"


def shown_to_student(review):
    """What the student sees: {"decision", "note", "returned_at"} as last
    returned, or None when nothing has been returned."""
    if not is_returned(review):
        return None
    if review.get("returned_decision"):
        return {"decision": review["returned_decision"], "note": review.get("returned_note", ""),
                "points": review.get("returned_points", ""), "returned_at": review["returned_at"]}
    # a row returned before the snapshot columns existed
    return {"decision": review["decision"], "note": review["note"], "points": review.get("points", ""),
            "returned_at": review["returned_at"]}


def changed_since_return(review):
    """True when the teacher changed the decision or the note after returning
    the work, so the student still sees the older version."""
    if not is_returned(review) or not review.get("returned_decision"):
        return False
    return ((review["decision"], review["note"], review.get("points", ""))
            != (review["returned_decision"], review.get("returned_note", ""),
                review.get("returned_points", "")))
