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
- One re-entrant lock per file serialises read-modify-write inside this
  process; Streamlit runs every browser session as a thread of one process.
"""

import copy
import csv
import datetime
import json
import os
import pathlib
import shutil
import threading
import uuid

from classroom import paths

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def lock_for(path):
    """The lock for one file. Re-entrant, so an operation that holds it can
    call the helpers below, which take it again."""
    key = str(pathlib.Path(path).resolve()).lower()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def new_id(prefix):
    return "{}_{}".format(prefix, uuid.uuid4().hex[:8])


def backup(path):
    """Copy a file into data/backups/ before it is rewritten. Microseconds in
    the name, so two rewrites in the same second keep both copies."""
    path = pathlib.Path(path)
    if not path.exists():
        return None
    paths.backups_dir().mkdir(parents=True, exist_ok=True)
    moment = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = paths.backups_dir() / "{}_{}{}".format(path.stem, moment, path.suffix)
    shutil.copyfile(path, target)
    return target


def _replace(path, write):
    """Call write(tmp_path), then atomically move the temp file over path."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        write(tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():                      # only after a failed write
            tmp.unlink()


# ---------------------------------------------------------------------- JSON
def read_json(path, default):
    """The file's object, or a copy of `default` when the file does not exist
    yet. A damaged file raises ValueError naming it; it is never replaced
    silently, because it holds accounts or classes."""
    path = pathlib.Path(path)
    with lock_for(path):
        if not path.exists() or path.stat().st_size == 0:
            return copy.deepcopy(default)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError("{} is not valid JSON ({}). Restore it from a copy in {}.".format(
                path.name, exc, paths.backups_dir())) from exc
        if not isinstance(data, dict):
            raise ValueError("{} should hold a JSON object.".format(path.name))
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
def _write_csv(target, columns, rows):
    with open(target, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _cell(row.get(k, "")) for k in columns})


def _cell(value):
    return "" if value is None else value


def ensure_csv(path, columns):
    """Create the file with its header, or check the header it has."""
    path = pathlib.Path(path)
    columns = list(columns)
    with lock_for(path):
        if not path.exists() or path.stat().st_size == 0:
            _replace(path, lambda tmp: _write_csv(tmp, columns, []))
            return
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, [])
        if header == columns:
            return
        if header and header == columns[:len(header)]:
            # an older layout without the newest columns: extend it
            with open(path, "r", newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            backup(path)
            _replace(path, lambda tmp: _write_csv(tmp, columns, rows))
            return
        raise ValueError("{} has the columns {} but MarkText expects {}. The file was not "
                         "changed.".format(path.name, header, columns))


def read_rows(path, columns):
    """All rows in file order, as dicts of strings."""
    path = pathlib.Path(path)
    with lock_for(path):
        ensure_csv(path, columns)
        with open(path, "r", newline="", encoding="utf-8") as f:
            return [dict(row) for row in csv.DictReader(f)]


def append_row(path, columns, row):
    """Add one row at the end. Appending never rewrites earlier rows."""
    path = pathlib.Path(path)
    with lock_for(path):
        ensure_csv(path, columns)
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
    """Create a text file that must not exist yet (mode "x" never overwrites)."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        f.write(text)
    return path


def write_new_json(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def csv_text(columns, rows):
    """The same CSV that write_new_csv() would write, as a string (for a
    browser download of exactly what is saved on the server)."""
    import io
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(columns))
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _cell(row.get(k, "")) for k in columns})
    return buffer.getvalue()


def write_new_csv(path, columns, rows):
    """A new CSV file (reports, exports). Written to a temp name first, so a
    half-written report never appears under its final name."""
    path = pathlib.Path(path)
    if path.exists():
        raise FileExistsError(path)
    _replace(path, lambda tmp: _write_csv(tmp, columns, rows))
    return path
