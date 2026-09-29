"""Scoring student submissions: where a student's text meets the detector.

detect_submission() writes two files, on purpose:
1. logs/detection_history.csv, through history.append_history with source
   "submission". It is the lab's audit log of every detection the engine
   has run; its note column holds the class, assignment, submission and
   student ids as JSON.
2. data/reviews.csv, through reviews.record_detection. It is the teacher's
   record: a snapshot of the numbers plus room for a decision.
The review keeps its own copy of the numbers because the lab's "Clear
history" empties the log (with a backup) and a review must outlive that.
Neither file lets a measurement change once written, so the copies cannot
drift apart; the history run_id links them.

The two rows are written together or not at all: both files are checked
for writing before the detector runs (a CSV open in Excel stops the work
there), and if the review row still cannot be written, the history row
just added is taken out again.

The engine is a parameter. A later version with several models or keys
passes another engine, and each review records which one scored the text
(model_id, key_id).
"""

import json

import history
import verdict
from classroom import audit, classes, paths, reviews, store, submissions


def history_note(submission):
    return json.dumps({"class_id": submission["class_id"],
                       "assignment_id": submission["assignment_id"],
                       "submission_id": submission["submission_id"],
                       "username": submission["username"],
                       "version": int(submission["version"])})


def _history_extra(submission):
    extra = {"note": history_note(submission)}
    side = submissions.sidecar(submission) or {}
    gen = side.get("generation")
    if gen:                                   # drafted with the assistant: known provenance
        extra.update(mode=gen.get("mode", ""), seed=gen.get("seed", ""),
                     max_new_tokens=gen.get("max_new_tokens", ""),
                     gen_tokens=gen.get("new_tokens", ""))
    return extra


def detect_submission(engine, lock, submission, detected_by):
    """Score one submission, log it, record the review, return the review.
    Raises MissingText when the text file is gone and FileProblem when a
    file cannot be written; in both cases nothing was written."""
    text = submissions.read_text(submission)
    store.check_writable(history.HISTORY_PATH, paths.reviews_path())
    with lock:
        stats = engine.detect(text)
    if stats is None:                         # too short to score at all
        stats = verdict.placeholder_stats(engine.config, engine.device)
    with store.file_errors(history.HISTORY_PATH, "write to"):
        run_id = history.append_history(stats, source="submission",
                                        filename="data/" + submission["text_path"],
                                        extra=_history_extra(submission))
    key_id = (stats.get("watermark") or {}).get("key_id") or ""
    try:
        review = reviews.record_detection(submission, stats, run_id,
                                          engine.config.get("model_id", ""), key_id, detected_by)
        audit.record(detected_by, "scored", submission["submission_id"],
                     "{}, z {:.2f}".format(stats.get("label", ""), stats.get("z_score", 0.0)))
        return review
    except ValueError:
        try:
            history.delete_record(run_id)     # keep the pair whole
        except (OSError, ValueError):
            pass                              # the log keeps a row; the detector did run
        raise


def pending(assignment_id):
    """Current submissions of students still in the class that have not been
    scored yet, oldest first (the order they were handed in)."""
    reviewed = reviews.latest_by_submission(assignment_id)
    rows = [s for s in submissions.list_submissions(assignment_id)
            if s["submission_id"] not in reviewed
            and classes.is_member(s["class_id"], s["username"])]
    return sorted(rows, key=lambda s: s["submitted_at"])


def drafted_with(submission):
    """The key id an assistant draft was made with (from its sidecar), or
    None for a text typed or uploaded by a person."""
    side = submissions.sidecar(submission) or {}
    return (side.get("generation") or {}).get("key_id")


def detect_many(engine, lock, items, detected_by, on_progress=None, cancel_event=None, pick=None):
    """Score several submissions; the same loop shape as experiment.run_batch.

    cancel_event is checked before each one; on_progress(done, total,
    submission, review) runs after each (review is None when it was
    skipped). A submission whose text is missing is skipped and listed. A
    file that cannot be written stops the run, because every later one would
    fail the same way; what was scored before stays scored.

    pick(submission) -> (engine, lock), when given, chooses the scorer for
    each submission (the classroom scores a draft with the key it was made
    with, which may be a retired one).

    Returns {"written": [reviews], "skipped": [(submission, reason)],
    "stopped": reason or None}."""
    result = {"written": [], "skipped": [], "stopped": None}
    total = len(items)
    for done, submission in enumerate(items, 1):
        if cancel_event is not None and cancel_event.is_set():
            break
        review = None
        use, use_lock = pick(submission) if pick else (engine, lock)
        try:
            review = detect_submission(use, use_lock, submission, detected_by)
        except submissions.MissingText as exc:
            result["skipped"].append((submission, str(exc)))
        except store.FileProblem as exc:
            result["stopped"] = str(exc)
            break
        else:
            result["written"].append(review)
        if on_progress:
            on_progress(done, total, submission, review)
    return result
