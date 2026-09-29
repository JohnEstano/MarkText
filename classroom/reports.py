"""Reports: who handed in what, what the detector found, what was decided.

Reads the roster, the submissions index and the reviews, joins them with
pandas (roster LEFT JOIN current submissions LEFT JOIN latest reviews, so a
student who handed nothing in still has a row), and writes new CSV files
under data/reports/. The source files are never edited here.
"""

import pandas as pd

import verdict
from classroom import accounts, assignments, classes, paths, reviews, store, submissions

STATES = ("not submitted", "awaiting detection", "awaiting decision", "decided", "returned")
REPORT_COLUMNS = ["username", "display_name", "state", "version", "submitted_at", "source",
                  "words", "tokens_scored", "green_pct", "z_score", "label", "decision", "note",
                  "returned", "returned_at"]
FRAME_COLUMNS = REPORT_COLUMNS + ["submission_id", "review_id"]
SUMMARY_COLUMNS = ["assignment_id", "title", "due_at", "status", "students", "submitted",
                   "detected", "likely", "possible", "not_detected", "inconclusive", "accepted",
                   "flagged", "needs_review", "returned", "mean_z"]
NUMERIC = ("version", "words", "tokens_scored", "green_pct", "z_score")


def _state(row):
    if not row["submission_id"]:
        return "not submitted"
    if not row["review_id"]:
        return "awaiting detection"
    if row["returned"] == "1":
        return "returned"
    if row["decision"] and row["decision"] != "pending":
        return "decided"
    return "awaiting decision"


def assignment_frame(assignment_id):
    """One row per active student of the assignment's class."""
    task = assignments.get_assignment(assignment_id)
    if task is None:
        raise ValueError("There is no assignment {}.".format(assignment_id))
    names = accounts.display_names()
    roster = pd.DataFrame(classes.roster(task["class_id"], "active"),
                          columns=classes.ROSTER_COLUMNS)[["username"]]
    roster["display_name"] = roster["username"].map(lambda u: names.get(u, u))

    subs = pd.DataFrame(submissions.list_submissions(assignment_id),
                        columns=submissions.COLUMNS)[
        ["username", "submission_id", "version", "submitted_at", "source", "words"]]
    revs = pd.DataFrame(list(reviews.latest_by_submission(assignment_id).values()),
                        columns=reviews.COLUMNS)[
        ["submission_id", "review_id", "tokens_scored", "green_pct", "z_score", "label",
         "decision", "note", "returned", "returned_at"]]

    df = roster.merge(subs, on="username", how="left").fillna("")
    df = df.merge(revs, on="submission_id", how="left").fillna("")
    df["state"] = df.apply(_state, axis=1) if len(df) else pd.Series(dtype=str)
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["returned"] = df["returned"] == "1"
    return df[FRAME_COLUMNS].sort_values("display_name", key=lambda s: s.str.lower()).reset_index(drop=True)


def state_counts(frame):
    return {s: int((frame["state"] == s).sum()) for s in STATES}


def _summary_row(task):
    f = assignment_frame(task["assignment_id"])
    detected = f[f["review_id"] != ""]
    return {
        "assignment_id": task["assignment_id"], "title": task["title"], "due_at": task["due_at"],
        "status": task["status"], "students": len(f),
        "submitted": int((f["state"] != "not submitted").sum()),
        "detected": len(detected),
        "likely": int((detected["label"] == verdict.LABEL_LIKELY).sum()),
        "possible": int((detected["label"] == verdict.LABEL_POSSIBLE).sum()),
        "not_detected": int((detected["label"] == verdict.LABEL_NOT_DETECTED).sum()),
        "inconclusive": int(detected["label"].str.startswith("INCONCLUSIVE").sum()),
        "accepted": int((f["decision"] == "accepted").sum()),
        "flagged": int((f["decision"] == "flagged").sum()),
        "needs_review": int((f["decision"] == "needs_review").sum()),
        "returned": int(f["returned"].sum()),
        "mean_z": round(float(detected["z_score"].mean()), 2) if len(detected) else None,
    }


def class_summary(class_id):
    """One row per assignment of the class, newest first."""
    rows = [_summary_row(t) for t in assignments.list_assignments(class_id)]
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def teacher_overview(username):
    """The numbers and lists for the teacher's home page."""
    my_classes = classes.list_classes(username)
    names = accounts.display_names()
    class_names = {c["class_id"]: c["name"] for c in my_classes}
    students, queue, flags = set(), [], []
    open_count = awaiting_detection = awaiting_decision = 0
    for c in my_classes:
        students |= {r["username"] for r in classes.roster(c["class_id"], "active")}
        for task in assignments.list_assignments(c["class_id"]):
            open_count += task["status"] == "open"
            counts = state_counts(assignment_frame(task["assignment_id"]))
            awaiting_detection += counts["awaiting detection"]
            awaiting_decision += counts["awaiting decision"]
            if counts["awaiting detection"] or counts["awaiting decision"]:
                queue.append({"class_id": c["class_id"], "class_name": c["name"],
                              "assignment_id": task["assignment_id"], "title": task["title"],
                              "due_at": task["due_at"],
                              "awaiting_detection": counts["awaiting detection"],
                              "awaiting_decision": counts["awaiting decision"]})
    titles = {t["assignment_id"]: t["title"] for t in assignments.list_assignments()}
    for r in reviews.list_reviews():
        if r["class_id"] in class_names and (r["label"] == verdict.LABEL_LIKELY
                                             or r["decision"] == "flagged"):
            flags.append({"student": names.get(r["username"], r["username"]),
                          "assignment": titles.get(r["assignment_id"], ""),
                          "class_name": class_names[r["class_id"]],
                          "label": r["label"], "z_score": r["z_score"],
                          "decision": r["decision"], "detected_at": r["detected_at"],
                          "assignment_id": r["assignment_id"], "class_id": r["class_id"],
                          "username": r["username"]})
    return {"classes": len(my_classes), "students": len(students), "open_assignments": open_count,
            "awaiting_detection": awaiting_detection, "awaiting_decision": awaiting_decision,
            "queue": queue, "recent_flags": flags[:5]}


def student_overview(username):
    """Each assignment in the student's classes with the student's own state.
    Detector numbers and labels are not part of it: a student sees only the
    teacher's decision and note, and only after the work is returned."""
    username = accounts.normalise_username(username)
    class_names = {c["class_id"]: c["name"] for c in classes.classes_for_student(username)}
    rows = []
    for task in assignments.for_student(username):
        sub = submissions.current_submission(task["assignment_id"], username)
        review = reviews.latest_review(sub["submission_id"]) if sub else None
        returned = bool(review and review["returned"] == "1")
        rows.append({
            "assignment_id": task["assignment_id"], "title": task["title"],
            "class_name": class_names.get(task["class_id"], ""), "due_at": task["due_at"],
            "status": task["status"],
            "my_state": "returned" if returned else ("submitted" if sub else "not submitted"),
            "version": int(sub["version"]) if sub else None,
            "submitted_at": sub["submitted_at"] if sub else "",
            "decision": review["decision"] if returned else "",
            "note": review["note"] if returned else "",
            "returned_at": review["returned_at"] if returned else "",
        })
    return rows


def _records(frame, columns):
    clean = frame[columns].astype(object).where(pd.notna(frame[columns]), "")
    return clean.to_dict("records")


def assignment_report_rows(assignment_id):
    return _records(assignment_frame(assignment_id), REPORT_COLUMNS)


def class_summary_rows(class_id):
    return _records(class_summary(class_id), SUMMARY_COLUMNS)


def export_assignment_report(assignment_id):
    """Write the assignment's table to a new CSV under data/reports/."""
    target = store.unique_path(paths.reports_dir(),
                               "assignment_{}_{}".format(assignment_id, store.stamp()), ".csv")
    return store.write_new_csv(target, REPORT_COLUMNS, assignment_report_rows(assignment_id))


def export_class_summary(class_id):
    target = store.unique_path(paths.reports_dir(),
                               "class_{}_summary_{}".format(class_id, store.stamp()), ".csv")
    return store.write_new_csv(target, SUMMARY_COLUMNS, class_summary_rows(class_id))
