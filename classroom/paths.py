"""Where the classroom keeps its files.

Every path is derived from DATA_DIR at the moment it is asked for, so a test
can move the whole classroom into a temporary folder by patching one name.
Paths stored inside CSV files are relative to DATA_DIR ("submissions/...")
so the data folder can be moved or restored as a unit.
"""

import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def users_path():
    return DATA_DIR / "users.json"


def classes_path():
    return DATA_DIR / "classes.json"


def rosters_path():
    return DATA_DIR / "rosters.csv"


def assignments_path():
    return DATA_DIR / "assignments.csv"


def submissions_path():
    return DATA_DIR / "submissions.csv"


def submissions_dir():
    return DATA_DIR / "submissions"


def reviews_path():
    return DATA_DIR / "reviews.csv"


def audit_path():
    return DATA_DIR / "audit.csv"


def reports_dir():
    return DATA_DIR / "reports"


def backups_dir():
    return DATA_DIR / "backups"


def ensure_dirs():
    for folder in (DATA_DIR, submissions_dir(), reports_dir(), backups_dir()):
        folder.mkdir(parents=True, exist_ok=True)


def data_relative(path):
    """The form stored in CSV files: forward slashes, relative to DATA_DIR."""
    return pathlib.Path(path).resolve().relative_to(DATA_DIR.resolve()).as_posix()


def resolve(relative):
    """The absolute path for a value stored by data_relative()."""
    return DATA_DIR / pathlib.PurePosixPath(relative)
