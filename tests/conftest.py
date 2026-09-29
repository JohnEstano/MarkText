import pathlib
import sys

import pytest

# the modules under test live in the repo root, not in a package
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """The whole classroom plus the history log in a temporary folder, and a
    cheap password hash so tests stay fast."""
    import experiment
    import history
    from classroom import accounts, paths

    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "logs" / "detection_history.csv")
    monkeypatch.setattr(history, "EXPORT_DIR", tmp_path / "logs" / "exports")
    monkeypatch.setattr(experiment, "EXPORT_DIR", tmp_path / "logs" / "exports")
    monkeypatch.setattr(accounts, "ITERATIONS", 1000)
    paths.ensure_dirs()
    return tmp_path / "data"


@pytest.fixture
def people(data_dir):
    """One teacher (prof) and two students (alice, ben)."""
    from classroom import accounts
    accounts.register("prof", "teacherpass", "teacher", "Prof. Reyes")
    accounts.register("alice", "studentpass", "student", "Alice Santos")
    accounts.register("ben", "studentpass", "student", "Ben Okafor")
    return data_dir


@pytest.fixture
def course(people):
    """A class with alice enrolled and one open assignment."""
    from classroom import assignments, classes
    cls = classes.create_class("Intro to writing", "prof", "Term 1")
    classes.join_class(cls["join_code"], "alice")
    task = assignments.create_assignment(cls["class_id"], "Why people keep diaries",
                                         "About 200 words.", "2026-10-15", "prof")
    return {"class": cls, "assignment": task}
