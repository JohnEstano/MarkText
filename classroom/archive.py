"""A whole class in one zip file: the teacher's record of a term, or a copy
to move to another computer.

export_class() writes data/reports/class_<id>_<stamp>.zip with:
    README.txt          what is inside
    class.json          the class record (name, term, teacher, join code)
    roster.csv          every roster row, with display names
    assignments.csv     the class's assignments
    submissions.csv     every version handed in, oldest first
    reviews.csv         every scoring and decision (latest per version last)
    summary.csv         one row per assignment, as on the Summary tab
    submissions/<assignment_id>/<username>/vNNN.txt and vNNN.json

The zip is written under a temporary name and renamed when complete, so a
half-written archive never appears. Nothing in data/ is changed.
"""

import json
import zipfile

import locks
from classroom import assignments, audit, classes, paths, reports, reviews, store, submissions

README = """MarkText class export
Class: {name} ({class_id}), term: {term}, teacher: {teacher}
Exported {when} by {by}.

class.json        the class record
roster.csv        students, with their status (active, invited, removed)
assignments.csv   the assignments
submissions.csv   every version handed in; text_path points into submissions/
reviews.csv       every scoring, with the teacher's decision and note
summary.csv       one row per assignment
submissions/      each version as vNNN.txt, with how it was made in vNNN.json

The CSV files are UTF-8. Text that starts like a spreadsheet formula has a
leading apostrophe, so Excel shows it instead of running it.
{missing}"""


def export_class(class_id, by=None):
    record = classes.get_class(class_id)
    if record is None:
        raise ValueError("There is no class {}.".format(class_id))
    subs = sorted(submissions.list_submissions(class_id=class_id, current_only=False),
                  key=lambda s: s["submitted_at"])
    missing = []
    target = store.unique_path(paths.reports_dir(), "class_{}_{}".format(class_id, store.stamp()), ".zip")
    tmp = target.with_name(target.name + ".tmp")
    with store.file_errors(target, "write"):
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr("class.json", json.dumps(record, indent=2, ensure_ascii=False))
                z.writestr("roster.csv", store.csv_text(classes.EXPORT_COLUMNS, classes.export_rows(class_id)))
                z.writestr("assignments.csv", store.csv_text(assignments.COLUMNS,
                                                             assignments.list_assignments(class_id)))
                z.writestr("submissions.csv", store.csv_text(submissions.COLUMNS, subs))
                z.writestr("reviews.csv", store.csv_text(
                    reviews.COLUMNS, reviews.list_reviews(class_id=class_id, latest_only=False)[::-1]))
                z.writestr("summary.csv", store.csv_text(reports.SUMMARY_COLUMNS,
                                                         reports.class_summary_rows(class_id)))
                for sub in subs:
                    text = paths.resolve(sub["text_path"])
                    inside = "submissions/{}/{}/{}".format(sub["assignment_id"], sub["username"], text.name)
                    for path, name in ((text, inside), (text.with_suffix(".json"), inside[:-4] + ".json")):
                        if path.exists():
                            z.write(path, name)
                        else:
                            missing.append(name)
                z.writestr("README.txt", README.format(
                    name=record["name"], class_id=class_id, term=record["term"] or "none",
                    teacher=record["teacher"], when=store.now(), by=by or "unknown",
                    missing="\nMissing on disk when exported:\n" + "\n".join(missing) if missing else ""))
            locks.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()
    audit.record(by, "exported", paths.data_relative(target),
                 "class {}: {} versions".format(class_id, len(subs)))
    return target
