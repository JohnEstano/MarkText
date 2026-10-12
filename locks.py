"""Locks for files that more than one thread or program may change.

Streamlit serves every browser tab from threads of one process, so a thread
lock keeps two tabs apart. The command-line tools (classroom.cli,
classroom.seed_demo, experiment.py) and the desktop app are separate
programs that write the same files, and a thread lock cannot see them. So a
write also holds a lock file next to the data file (users.json.lock). It is
created with O_CREAT | O_EXCL, which the operating system lets only one
program win, and removed when the write is done. A lock file older than
STALE seconds was left by a program that crashed; it is taken over.

Reading needs no lock file: every rewrite replaces the file in one atomic
step (os.replace), so a reader sees the old file or the new one, never half
of each. Readers take only the thread lock.
"""

import os
import pathlib
import threading
import time

STALE = 60          # seconds after which a lock file is considered abandoned
TIMEOUT = 15        # seconds to wait for another program to finish
RETRIES = 5         # tries for a replace or a delete that Windows refuses for a moment
RETRY_DELAY = 0.1   # seconds between them


def replace(src, dst):
    """os.replace, tried again for about half a second. On Windows a virus
    scanner or the search indexer may hold a file for a moment after it is
    written, and the replace then fails with PermissionError. A file that
    stays locked (open in Excel) still fails, a little later."""
    for attempt in range(RETRIES):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(RETRY_DELAY)


class Busy(OSError):
    """Another program held the file for longer than TIMEOUT."""


class FileLock:
    """A re-entrant lock for one file: a thread lock, plus a lock file while
    the outermost holder writes."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.lockfile = self.path.with_name(self.path.name + ".lock")
        self._thread_lock = threading.RLock()
        self._depth = 0

    def reading(self):
        """The thread lock only, as a context manager."""
        return self._thread_lock

    def acquire(self):
        self._thread_lock.acquire()
        if self._depth == 0:
            try:
                self._take_file()
            except BaseException:
                self._thread_lock.release()
                raise
        self._depth += 1
        return True

    def release(self):
        self._depth -= 1
        if self._depth == 0:
            self._drop_file()
        self._thread_lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()

    def _take_file(self):
        self.lockfile.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + TIMEOUT
        while True:
            try:
                fd = os.open(self.lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except (FileExistsError, PermissionError):
                # PermissionError: on Windows, a lock file that is being deleted
                if self._abandoned():
                    try:
                        self.lockfile.unlink()
                    except OSError:
                        pass
                if time.monotonic() > deadline:
                    raise Busy("{} is being changed by another MarkText program ({} exists). "
                               "Try again; if no other program is running, delete {}.".format(
                                   self.path.name, self.lockfile.name, self.lockfile)) from None
                time.sleep(0.05)
            else:
                with os.fdopen(fd, "w") as f:
                    f.write("{} {}\n".format(os.getpid(), time.time()))
                return

    def _abandoned(self):
        try:
            return time.time() - self.lockfile.stat().st_mtime > STALE
        except OSError:
            return False

    def _drop_file(self):
        for _ in range(RETRIES):
            try:
                self.lockfile.unlink()
                return
            except FileNotFoundError:
                return
            except PermissionError:           # held for a moment by a scanner
                time.sleep(RETRY_DELAY)
        # left behind: other programs take it over once it is STALE seconds old


_LOCKS = {}
_GUARD = threading.Lock()


def lock_for(path):
    """The one FileLock for this file in this process."""
    key = str(pathlib.Path(path).resolve()).lower()
    with _GUARD:
        return _LOCKS.setdefault(key, FileLock(path))
