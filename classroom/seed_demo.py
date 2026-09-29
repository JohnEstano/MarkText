"""A demo class for presentations.

    python -m classroom.seed_demo              # with the model: assistant draft + detection
    python -m classroom.seed_demo --no-model   # quick: four essays, nothing scored
    python -m classroom.seed_demo --reset      # move data/ aside first (renamed, never deleted)
    python -m classroom.seed_demo --teacher nash   # give the class to an existing teacher

Creates the teacher prof and five students (password DEMO_PASSWORD), the
class "Intro to writing" with its roster imported from a list, one
assignment, four essays written by people (classroom/demo_texts/), and,
when a model is available, one essay drafted with the assistant. Then it
scores every submission, so the teacher opens a review page with real
results: the drafted essay flagged, the four human essays not.
"""

import argparse
import datetime
import pathlib
import threading

from classroom import accounts, assignments, assistant, classes, detection, paths, store, submissions

DEMO_PASSWORD = "marktext-demo"
TEACHER = ("prof", "Prof. Reyes")
STUDENTS = (("alice", "Alice Santos"), ("ben", "Ben Okafor"), ("chloe", "Chloe Tan"),
            ("dan", "Dan Villanueva"), ("eva", "Eva Lindqvist"))
WRITERS = ("alice", "ben", "chloe", "eva")
ASSISTED = "dan"
TEXT_DIR = pathlib.Path(__file__).resolve().parent / "demo_texts"
CLASS_NAME = "Intro to writing"
TERM = "Demo term"
TITLE = "Why people keep diaries"
INSTRUCTIONS = ("Write a short essay (about 200 words) on why people keep diaries. "
                "Use your own words. If you draft with the assistant, say so in the version note.")
PROMPT = "Write a short essay on why people keep diaries."


def archive_data():
    """Rename data/ to data.archived_<stamp>/ and start empty. Returns the new
    name of the old folder, or None when there was nothing to move."""
    if not paths.DATA_DIR.exists() or not any(paths.DATA_DIR.iterdir()):
        return None
    target = paths.DATA_DIR.with_name("data.archived_" + store.stamp())
    paths.DATA_DIR.rename(target)
    paths.ensure_dirs()
    (paths.DATA_DIR / ".gitkeep").touch()
    return target


def _account(username, display_name, role):
    user = accounts.get_user(username)
    if user is None:
        return accounts.register(username, DEMO_PASSWORD, role, display_name), True
    if user["role"] != role:
        raise ValueError("{} already exists as a {} account.".format(username, user["role"]))
    return user, False


def seed(teacher=None, engine=None, lock=None, detect=True, on_step=None):
    """Build the demo class. `teacher` is an existing teacher's username, or
    None to create prof. Without an engine there is no assistant draft and
    nothing is scored. Returns a summary dict."""
    step = on_step or (lambda message: None)
    paths.ensure_dirs()
    created = []
    if teacher is None:
        user, new = _account(*TEACHER, "teacher")
        teacher = user["username"]
        if new:
            created.append(teacher)
    elif (accounts.get_user(teacher) or {}).get("role") != "teacher":
        raise ValueError("{} is not a teacher account.".format(teacher))
    for username, name in STUDENTS:
        _, new = _account(username, name, "student")
        if new:
            created.append(username)
    step("Accounts ready")

    cls = classes.create_class(CLASS_NAME, teacher, TERM)
    roster = classes.import_roster(cls["class_id"], [{"username": u} for u, _ in STUDENTS], by=teacher)
    due = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
    task = assignments.create_assignment(cls["class_id"], TITLE, INSTRUCTIONS, due, teacher)
    step("Class created and roster imported")

    for username in WRITERS:
        with open(TEXT_DIR / (username + ".txt"), "r", encoding="utf-8") as f:
            submissions.submit(task["assignment_id"], username, f.read())
    step("Four essays handed in")

    drafted = False
    if engine is not None:
        lock = lock or threading.Lock()
        info = assistant.draft(engine, lock, PROMPT)
        submissions.submit(task["assignment_id"], ASSISTED, info["text"], "assistant",
                           version_note="Drafted with the assistant",
                           generation=assistant.generation_record(info, PROMPT))
        drafted = True
        step("One essay drafted with the assistant")

    scored = []
    if engine is not None and detect:
        scored = detection.detect_many(engine, lock, detection.pending(task["assignment_id"]), teacher)
        step("Every submission scored")
    return {"teacher": teacher, "accounts_created": created, "class_id": cls["class_id"],
            "class_name": cls["name"], "join_code": classes.format_code(cls["join_code"]),
            "assignment_id": task["assignment_id"], "enrolled": roster["enrolled"],
            "drafted": drafted, "scored": len(scored)}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m classroom.seed_demo", description=__doc__.split("\n")[0])
    parser.add_argument("--reset", action="store_true",
                        help="rename the current data/ folder aside first (never deleted)")
    parser.add_argument("--no-model", action="store_true",
                        help="skip the assistant draft and scoring (no model load)")
    parser.add_argument("--no-detect", action="store_true", help="draft, but do not score")
    parser.add_argument("--teacher", default=None, help="an existing teacher who will own the class")
    args = parser.parse_args(argv)

    if args.reset:
        moved = archive_data()
        print("Old data moved to {}".format(moved) if moved else "No data to move.")
    engine = lock = None
    if not args.no_model:
        import config as cfg
        from engine import Engine          # late: loading the model is slow
        print("Loading the model...")
        engine, lock = Engine(cfg.load_config(), progress_callback=print), threading.Lock()
    try:
        summary = seed(args.teacher, engine, lock, detect=not args.no_detect, on_step=print)
    except ValueError as exc:
        print(exc)
        return 1
    print("\nClass {} ({}), join code {}".format(summary["class_name"], summary["class_id"],
                                                  summary["join_code"]))
    print("Teacher: {}   Students: {}".format(summary["teacher"], ", ".join(u for u, _ in STUDENTS)))
    if summary["accounts_created"]:
        print("New accounts use the password: {}".format(DEMO_PASSWORD))
    print("Assistant draft: {}   Submissions scored: {}".format(
        "yes" if summary["drafted"] else "no", summary["scored"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
