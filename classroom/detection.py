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

The engine is a parameter. Callers with several models or keys pass the
engine for the submission (detect_many's pick), and each review records
which one scored the text (model_id, key_id); the history row names the
catalog model too.
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
        extra.update(mode=gen.get("mode", ""), model=gen.get("model", ""),
                     seed=gen.get("seed", ""), max_new_tokens=gen.get("max_new_tokens", ""),
                     gen_tokens=gen.get("new_tokens", ""))
    return extra


def trial_models(candidates, text):
    """Score `text` with every (model name, scorer, lock) candidate and
    return (winner name, winner stats, [(name, z, label)] for every model
    that scored). The winner is the highest z-score; ties go to the earlier
    candidate. Returns (None, None, []) when nothing scores (too short for
    every model). Scorers only need tokenizers, so trying every model is
    cheap: no weights load."""
    scored = []
    for name, scorer, lock in candidates:
        with lock:
            stats = scorer.detect(text)
        if stats is not None:
            scored.append((name, stats))
    if not scored:
        return None, None, []
    best = max(range(len(scored)), key=lambda i: (scored[i][1]["z_score"], -i))
    name, stats = scored[best]
    return name, stats, [(n, s["z_score"], s["label"]) for n, s in scored]


def winner_model(name, stats):
    """The model a logged row should name: the trial winner when its own
    scale says the key may be present (likely or possible), else "".
    Naming a model for a negative would claim what no evidence supports."""
    if stats is not None and stats.get("label") in (verdict.LABEL_LIKELY,
                                                    verdict.LABEL_POSSIBLE):
        return name or ""
    return ""


def detect_submission(engine, lock, submission, detected_by, candidates=None):
    """Score one submission, log it, record the review, return the review.
    A draft made with the assistant is scored with its own model and key;
    anything else is tried against every `candidates` entry
    [(model name, scorer, lock)] when given, else against `engine` alone.
    Raises MissingText when the text file is gone and FileProblem when a
    file cannot be written; in both cases nothing was written."""
    text = submissions.read_text(submission)
    store.check_writable(history.HISTORY_PATH, paths.reviews_path())
    side = submissions.sidecar(submission) or {}
    gen = side.get("generation")
    scorer, use_lock = engine, lock
    model, stats, tried = getattr(engine, "model_name", ""), None, False
    if not gen and candidates:
        model, stats, _scores = trial_models(candidates, text)
        tried = True
        if stats is not None:
            scorer = next(s for n, s, _l in candidates if n == model)
            use_lock = next(l for n, _s, l in candidates if n == model)
    if stats is None and not tried:
        with use_lock:
            stats = scorer.detect(text)
    if stats is None:                         # too short to score at all
        stats = verdict.placeholder_stats(scorer.config, scorer.device)
    with store.file_errors(history.HISTORY_PATH, "write to"):
        extra = _history_extra(submission)
        if tried:
            extra["model"] = winner_model(model, stats)
        else:
            extra.setdefault("model", model or "")
        run_id = history.append_history(stats, source="submission",
                                        filename="data/" + submission["text_path"],
                                        extra=extra, text=text)
    key_id = (stats.get("watermark") or {}).get("key_id") or ""
    try:
        review = reviews.record_detection(submission, stats, run_id,
                                          scorer.config.get("model_id", ""), key_id, detected_by)
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


def old_scores(assignment_id):
    """Current submissions of students still in the class whose latest score
    counted every repeat (reviews.counted_every_repeat), oldest first."""
    latest = reviews.latest_by_submission(assignment_id)
    rows = [s for s in submissions.list_submissions(assignment_id)
            if reviews.counted_every_repeat(latest.get(s["submission_id"]))
            and classes.is_member(s["class_id"], s["username"])]
    return sorted(rows, key=lambda s: s["submitted_at"])


def drafted_with(submission):
    """The key id an assistant draft was made with (from its sidecar), or
    None for a text typed or uploaded by a person."""
    side = submissions.sidecar(submission) or {}
    return (side.get("generation") or {}).get("key_id")


def detect_many(engine, lock, items, detected_by, on_progress=None, cancel_event=None, pick=None,
                candidates=None):
    """Score several submissions; the same loop shape as experiment.run_batch.

    cancel_event is checked before each one; on_progress(done, total,
    submission, review) runs after each (review is None when it was
    skipped). A submission whose text is missing is skipped and listed. A
    file that cannot be written stops the run, because every later one would
    fail the same way; what was scored before stays scored.

    pick(submission) -> (engine, lock), when given, chooses the scorer for
    each submission (the classroom scores a draft with the key it was made
    with, which may be a retired one). `candidates` [(model name, scorer,
    lock)] is tried for submissions with no known provenance, so a typed
    or uploaded text names the model whose key matched, if any.

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
            review = detect_submission(use, use_lock, submission, detected_by,
                                       candidates=candidates)
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
