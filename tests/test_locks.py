"""locks.py: a thread lock between browser tabs, a lock file between programs."""

import os
import subprocess
import sys
import textwrap
import time

import pytest

import locks
from classroom import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_a_write_holds_a_lock_file_only_while_it_runs(tmp_path):
    lock = locks.FileLock(tmp_path / "users.json")
    with lock:
        assert lock.lockfile.exists()
        with lock:                                    # re-entrant
            assert lock.lockfile.exists()
        assert lock.lockfile.exists()
    assert not lock.lockfile.exists()


def test_reading_takes_no_lock_file(tmp_path):
    lock = locks.FileLock(tmp_path / "users.json")
    with lock.reading():
        assert not lock.lockfile.exists()


def test_another_program_is_waited_for(tmp_path):
    target = tmp_path / "rosters.csv"
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent("""
        import sys, time
        sys.path.insert(0, {root!r})
        import locks
        with locks.lock_for({target!r}):
            print("held", flush=True)
            time.sleep(1.0)
        """).format(root=ROOT, target=str(target))], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    started = time.monotonic()
    with locks.FileLock(target):
        waited = time.monotonic() - started
    holder.wait(10)
    assert waited > 0.3                               # it waited for the other program


def test_an_abandoned_lock_file_is_taken_over(tmp_path):
    lock = locks.FileLock(tmp_path / "classes.json")
    lock.lockfile.write_text("12345 0\n", encoding="utf-8")
    old = time.time() - locks.STALE - 5
    os.utime(lock.lockfile, (old, old))
    with lock:
        pass
    assert not lock.lockfile.exists()


def test_a_lock_held_too_long_is_a_message_not_a_hang(tmp_path, monkeypatch):
    monkeypatch.setattr(locks, "TIMEOUT", 0.2)
    path = tmp_path / "data" / "reviews.csv"
    path.parent.mkdir()
    (path.parent / "reviews.csv.lock").write_text("999 0\n", encoding="utf-8")   # a live program
    with pytest.raises(locks.Busy, match="another MarkText program"):
        locks.FileLock(path).acquire()
    with pytest.raises(store.FileProblem, match="another MarkText program"):
        store.append_row(path, ["a"], {"a": "1"})
