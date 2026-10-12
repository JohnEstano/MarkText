"""File helpers shared by every classroom module.

The same rules history.py follows, in one place:
- JSON and CSV files are rewritten atomically: a backup copy first, then a
  temporary file next to the target, then os.replace. A crash mid-write
  leaves the old file whole.
- CSV files have a fixed column list, go through csv.DictWriter/DictReader,
  and are opened with newline="" and encoding="utf-8".
- A file with an unexpected header is never "fixed" silently: ValueError.
  A header that is an older, shorter version of the columns is extended
  (backup first), so a column can be added later without losing data.
- One lock per file serialises read-modify-write (locks.py): a thread lock
  between browser tabs, which Streamlit runs as threads of one process, and
  a lock file while writing, so the command-line tools and the desktop app,
  which are other processes, wait their turn too.
- Files are read as "utf-8-sig": a file saved back by Excel or Notepad may
  start with a byte-order mark, which would otherwise glue itself to the
  first column name. Files are written without one.
- A file that cannot be read or written (a CSV open in Excel is locked, a
  folder is read-only, the disk is full) raises FileProblem, a ValueError
  whose message names the file and what to do. Pages already show every
  ValueError as a message, so a busy file is never a crash.
"""

import contextlib
import copy
import csv
import datetime
import errno
import io
import json
import pathlib
import re
import shutil
import threading
import uuid

import locks
from classroom import paths

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
# path -> (file signature, columns or None, parsed content); see _cached
_CACHE = {}


class _Lock:
    """`with lock_for(path):` around a change; `with lock_for(path).reading():`
    around a read. Re-entrant, so an operation that holds it can call the
    helpers below, which take it again."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.file_lock = locks.lock_for(path)

    def reading(self):
        return self.file_lock.reading()

    def __enter__(self):
        try:
            self.file_lock.acquire()
        except locks.Busy as exc:
            raise FileProblem(self.path, "change", exc) from exc
        return self

    def __exit__(self, *exc):
        self.file_lock.release()


def lock_for(path):
    """The lock for one file (one object per file in this process)."""
    key = str(pathlib.Path(path).resolve()).lower()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, _Lock(path))


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def new_id(prefix):
    return "{}_{}".format(prefix, uuid.uuid4().hex[:8])


# ------------------------------------------------------------------- errors
def shown_path(path):
    """How a file is named in messages: data/..., logs/..., or its name."""
    path = pathlib.Path(path)
    for root, prefix in ((paths.DATA_DIR, "data/"), (paths.BASE_DIR, "")):
        try:
            return prefix + path.resolve().relative_to(pathlib.Path(root).resolve()).as_posix()
        except ValueError:
            continue
    return path.name


class FileProblem(ValueError):
    """A data file could not be read or written. A ValueError, so every form
    that shows a broken rule shows this too; the message says which file and
    what to do. Raised before anything was changed, or after the change was
    undone."""

    def __init__(self, path, doing, error):
        self.path, self.error = pathlib.Path(path), error
        if isinstance(error, PermissionError):
            hint = ("It is probably open in another program, such as Excel, which locks the "
                    "files it opens. Close it there and try again.")
        elif getattr(error, "errno", None) == errno.ENOSPC:
            hint = "The disk is full."
        elif isinstance(error, UnicodeDecodeError):
            hint = ("It is not UTF-8 text; a spreadsheet program may have saved it in another "
                    "encoding. Save it as \"CSV UTF-8\", or restore it from data/backups.")
        elif isinstance(error, FileNotFoundError):
            hint = "It is missing; it was moved or deleted outside MarkText."
        else:
            hint = str(error)
        super().__init__("MarkText could not {} {}. {}".format(doing, shown_path(path), hint))


@contextlib.contextmanager
def file_errors(path, doing):
    """Turn an OSError or UnicodeDecodeError raised inside into FileProblem."""
    try:
        yield
    except FileProblem:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise FileProblem(path, doing, exc) from exc


def check_writable(*files):
    """Open each existing file for appending and close it again, writing
    nothing. Used before work that writes several files, so a file that is
    open in Excel stops the work before the first write, not halfway."""
    for path in files:
        path = pathlib.Path(path)
        if path.exists():
            with file_errors(path, "write to"):
                with open(path, "a", encoding="utf-8"):
                    pass


# -------------------------------------------------------------------- dates
# Excel rewrites the dates it recognises when it saves a CSV: 2026-10-15
# becomes 10/15/2026 and a timestamp loses its seconds. These formats read
# both; month first is how Excel writes them under US settings, the Windows
# default here. A value in none of them stays text: shown as it is, never a
# crash.
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d")
TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M")


def parse_time(value):
    """A datetime from a stored timestamp, or None."""
    if isinstance(value, datetime.datetime):
        return value
    text = value.strip() if isinstance(value, str) else ""
    for fmt in TIME_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_date(value):
    """A datetime.date from a stored date (or timestamp), or None."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = value.strip() if isinstance(value, str) else ""
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    moment = parse_time(text)
    return moment.date() if moment else None


# ------------------------------------------------------------------ backups
KEEP_BACKUPS = 30       # newest copies kept per data file


def backup(path):
    """Copy a file into data/backups/ before it is rewritten. Microseconds in
    the name, so two rewrites in the same second keep both copies. Only the
    newest KEEP_BACKUPS copies of each file are kept (prune_backups)."""
    path = pathlib.Path(path)
    if not path.exists():
        return None
    moment = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = paths.backups_dir() / "{}_{}{}".format(path.stem, moment, path.suffix)
    with file_errors(target, "write the backup copy"):
        paths.backups_dir().mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    prune_backups(path.stem, path.suffix)
    return target


def backups_of(stem, suffix):
    """Backup copies of one data file, oldest first (the names sort by time)."""
    pattern = re.compile(r"{}_\d{{8}}_\d{{6}}_\d{{6}}{}".format(re.escape(stem), re.escape(suffix)))
    folder = paths.backups_dir()
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if pattern.fullmatch(p.name))


def prune_backups(stem, suffix, keep=None):
    """Delete all but the newest `keep` copies of one data file. Without a
    limit the folder grows with every decision, and old copies of
    users.json would keep old password hashes for ever."""
    keep = KEEP_BACKUPS if keep is None else keep
    for old in backups_of(stem, suffix)[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass                                  # a copy open elsewhere goes next time


def _replace(path, write):
    """Call write(tmp_path), then atomically move the temp file over path."""
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with file_errors(path, "save"):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            write(tmp)
            locks.replace(tmp, path)
        finally:
            if tmp.exists():                  # only after a failed write
                tmp.unlink()


def _signature(path):
    """What changes whenever the file does: os.replace makes a new file (new
    id), an append changes the size, any write changes the time."""
    st = path.stat()
    return st.st_ino, st.st_mtime_ns, st.st_size


def _cached(path, extra, load):
    """load(), or the result of the last load() while the file is unchanged.
    Pages read the same files many times per click (the home page reads the
    rosters once per assignment); parsing each unchanged file once is enough.
    Callers get a copy, so changing what they got cannot change the cache."""
    key = str(path.resolve()).lower()
    signature = _signature(path)
    hit = _CACHE.get(key)
    if hit is None or hit[0] != signature or hit[1] != extra:
        hit = (signature, extra, load())
        _CACHE[key] = hit
    return copy.deepcopy(hit[2])


# ---------------------------------------------------------------------- JSON
def read_json(path, default):
    """The file's object, or a copy of `default` when the file does not exist
    yet. A damaged file raises ValueError naming it; it is never replaced
    silently, because it holds accounts or classes."""
    path = pathlib.Path(path)
    with lock_for(path).reading():
        if not path.exists() or path.stat().st_size == 0:
            return copy.deepcopy(default)
        def load():
            with file_errors(path, "read"):
                with open(path, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
        try:
            data = _cached(path, None, load)
        except json.JSONDecodeError as exc:
            raise ValueError("{} is not valid JSON ({}). Restore it from a copy in "
                             "data/backups.".format(shown_path(path), exc)) from exc
        if not isinstance(data, dict):
            raise ValueError("{} should hold a JSON object.".format(shown_path(path)))
        return data


def write_json(path, data, keep_backup=True):
    """Rewrite a JSON file atomically. Returns the backup path (or None)."""
    path = pathlib.Path(path)
    with lock_for(path):
        saved = backup(path) if keep_backup else None

        def write(tmp):
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        _replace(path, write)
        return saved


def update_json(path, default, change, keep_backup=True):
    """Read, apply change(data) and write back, all under the file's lock.
    Returns whatever change() returns; a ValueError from change() leaves the
    file untouched."""
    with lock_for(path):
        data = read_json(path, default)
        result = change(data)
        write_json(path, data, keep_backup=keep_backup)
        return result


# ----------------------------------------------------------------------- CSV
def _write_csv(target, columns, rows, cell=None):
    cell = cell or _cell
    with open(target, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: cell(row.get(k, "")) for k in columns})


def _cell(value):
    return "" if value is None else value


FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def spreadsheet_cell(value):
    """A cell for a file that people open in a spreadsheet (reports and
    exports, never the data files): text that starts like a formula gets a
    leading apostrophe, so Excel shows it instead of running it. A student
    named "=HYPERLINK(...)" stays a name ("CSV injection", OWASP). Numbers,
    including negative ones, are left alone."""
    value = _cell(value)
    if not isinstance(value, str) or not value.startswith(FORMULA_START):
        return value
    try:
        float(value)
        return value
    except ValueError:
        return "'" + value


def ensure_csv(path, columns):
    """Create the file with its header, or check the header it has."""
    path = pathlib.Path(path)
    columns = list(columns)
    with lock_for(path).reading():
        if _header(path) == columns:
            return
    with lock_for(path):
        header = _header(path)
        if header == columns:
            return
        if header is None:
            _replace(path, lambda tmp: _write_csv(tmp, columns, []))
            return
        if header and header == columns[:len(header)]:
            # an older layout without the newest columns: extend it
            with file_errors(path, "read"):
                with open(path, "r", newline="", encoding="utf-8-sig") as f:
                    rows = list(csv.DictReader(f))
            backup(path)
            _replace(path, lambda tmp: _write_csv(tmp, columns, rows))
            return
        raise ValueError("{} has the columns {} but MarkText expects {}. The file was not "
                         "changed; restore it from data/backups.".format(shown_path(path), header,
                                                                        columns))


def _header(path):
    """The first row of a CSV file, or None when it does not exist or is empty."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    with file_errors(path, "read"):
        with open(path, "r", newline="", encoding="utf-8-sig") as f:
            return next(csv.reader(f), [])


def read_rows(path, columns):
    """All rows in file order, as dicts of strings."""
    path = pathlib.Path(path)
    with lock_for(path).reading():
        ensure_csv(path, columns)

        def load():
            with file_errors(path, "read"):
                with open(path, "r", newline="", encoding="utf-8-sig") as f:
                    return [dict(row) for row in csv.DictReader(f)]
        return _cached(path, tuple(columns), load)


def append_row(path, columns, row):
    """Add one row at the end. Appending never rewrites earlier rows."""
    path = pathlib.Path(path)
    with lock_for(path):
        ensure_csv(path, columns)
        with file_errors(path, "write to"):
            with open(path, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=list(columns)).writerow(
                    {k: _cell(row.get(k, "")) for k in columns})
    return row


def rewrite_rows(path, columns, rows):
    """Replace every row (backup first). Returns the backup path."""
    path = pathlib.Path(path)
    with lock_for(path):
        ensure_csv(path, columns)
        saved = backup(path)
        _replace(path, lambda tmp: _write_csv(tmp, columns, rows))
        return saved


def update_where(path, columns, match, change, describe="the given key"):
    """Apply change(row) to the single row for which match(row) is true
    (change returns the new row, or None to drop it). Raises ValueError
    unless exactly one row matches. Returns the backup path."""
    path = pathlib.Path(path)
    with lock_for(path):
        rows = read_rows(path, columns)
        hits = [r for r in rows if match(r)]
        if len(hits) != 1:
            raise ValueError("{} row(s) in {} match {}; expected exactly one.".format(
                len(hits), path.name, describe))
        new_rows = []
        for row in rows:
            if match(row):
                row = change(dict(row))
                if row is None:
                    continue
            new_rows.append(row)
        return rewrite_rows(path, columns, new_rows)


def update_one(path, columns, key, value, change):
    """update_where() for the row whose `key` column equals `value`."""
    return update_where(path, columns, lambda r: r.get(key) == value, change,
                        "{} = {!r}".format(key, value))


# ----------------------------------------------------------------- new files
def unique_path(folder, stem, suffix):
    """folder/stem+suffix, or stem_2, stem_3... if that name is taken."""
    folder = pathlib.Path(folder)
    candidate = folder / (stem + suffix)
    n = 2
    while candidate.exists():
        candidate = folder / "{}_{}{}".format(stem, n, suffix)
        n += 1
    return candidate


def write_new_text(path, text):
    """Create a text file that must not exist yet (mode "x" never overwrites).
    newline="" writes the text's own "\\n" line ends, so the file's bytes are
    exactly the UTF-8 of `text` and a hash of one is a hash of the other."""
    path = pathlib.Path(path)
    with file_errors(path, "create"):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "x", encoding="utf-8", newline="") as f:
            f.write(text)
    return path


def write_new_json(path, data):
    path = pathlib.Path(path)
    with file_errors(path, "create"):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "x", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def csv_text(columns, rows):
    """The same CSV that write_new_csv() would write, as a string (for a
    browser download of exactly what is saved on the server)."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(columns))
    writer.writeheader()
    for row in rows:
        writer.writerow({k: spreadsheet_cell(row.get(k, "")) for k in columns})
    return buffer.getvalue()


def write_new_csv(path, columns, rows):
    """A new CSV file (reports, exports), with spreadsheet-safe cells.
    Written to a temp name first, so a half-written report never appears
    under its final name."""
    path = pathlib.Path(path)
    if path.exists():
        raise FileProblem(path, "create", FileExistsError(errno.EEXIST, "it already exists"))
    _replace(path, lambda tmp: _write_csv(tmp, columns, rows, spreadsheet_cell))
    return path
