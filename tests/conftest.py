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


def _file_key(file):
    try:
        return str(pathlib.Path(file).resolve()).lower()
    except TypeError:                    # a file descriptor, not a path
        return None


@pytest.fixture
def excel_lock(monkeypatch):
    """Make files behave as they do on Windows while Excel has them open:
    reading works, but opening one for writing or replacing it raises
    PermissionError. Call excel_lock(path) to lock, excel_lock.release(path)
    to close it again."""
    import builtins
    import os
    locked = set()
    real_open, real_replace = builtins.open, os.replace

    def fake_open(file, mode="r", *args, **kwargs):
        if any(m in mode for m in "wax+") and _file_key(file) in locked:
            raise PermissionError(13, "Permission denied", str(file))
        return real_open(file, mode, *args, **kwargs)

    def fake_replace(src, dst, *args, **kwargs):
        if _file_key(dst) in locked:
            raise PermissionError(13, "Access is denied", str(dst))
        return real_replace(src, dst, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(os, "replace", fake_replace)

    def lock(path):
        locked.add(_file_key(path))
    lock.release = lambda path: locked.discard(_file_key(path))
    return lock
