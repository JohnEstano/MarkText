"""Detection history log for MarkText (was detector.py).

Every analysis appends one row to logs/detection_history.csv with the
csv module. This module never classifies: the verdict label comes from
Engine.detect(), so both front-ends and the log agree by construction.

Since 2026-09-23 every row has a unique run_id and records the context
it was scored under (mode, seed, parameters, device) so records can be
compared, annotated, updated or deleted one at a time. An older file in
the 7-column layout is migrated on first use; the original is kept.
"""

import csv
import datetime
import os
import pathlib
import shutil
import uuid

BASE_DIR = pathlib.Path(__file__).resolve().parent
HISTORY_PATH = BASE_DIR / "logs" / "detection_history.csv"
EXPORT_DIR = BASE_DIR / "logs" / "exports"

COLUMNS = [
    "run_id",
    "timestamp",
    "source",          # manual | file | batch | legacy
    "filename",
    "mode",            # normal | watermarked, when known
    "batch_id",
    "max_new_tokens",
    "seed",
    "gen_tokens",      # tokens the model produced, when known
    "tokens_scored",
    "green_tokens",
    "green_pct",
    "z_score",
    "p_value",
    "result",
    "bias",
    "greenlist_ratio",
    "seeding_scheme",
    "context_width",
    "device",
    "note",
]

# the layout used before run_id existed; recognised for migration
LEGACY_COLUMNS = ["timestamp", "filename", "tokens_scored", "green_tokens",
                  "green_fraction", "z_score", "result"]
LEGACY_LABELS = {"NO WATERMARK": "NOT DETECTED"}

# the only fields a user may change after the fact
EDITABLE = ("note", "filename")

SOURCES = ("manual", "file", "batch", "legacy")


def _stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _write_rows(rows, path=None):
    """Rewrite the whole file atomically: write a temp file next to it, then
    replace, so a crash or a lock mid-write cannot leave a half-written CSV."""
    path = pathlib.Path(path or HISTORY_PATH)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLUMNS})
    os.replace(tmp, path)


def _read_header():
    with open(HISTORY_PATH, "r", newline="", encoding="utf-8") as f:
        return next(csv.reader(f), [])


def ensure_history():
    """Create the file with a header, or migrate an old layout. Returns the
    path of the archived old file when a migration happened, else None."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not HISTORY_PATH.exists() or HISTORY_PATH.stat().st_size == 0:
        _write_rows([])
        return None
    header = _read_header()
    if header == COLUMNS:
        return None
    if header == LEGACY_COLUMNS:
        return _migrate_legacy()
    raise ValueError("Unexpected history header: {}".format(header))


def _migrate_legacy():
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    archive = EXPORT_DIR / "detection_history_v1_{}.csv".format(_stamp())
    shutil.copyfile(HISTORY_PATH, archive)
    with open(HISTORY_PATH, "r", newline="", encoding="utf-8") as f:
        old = list(csv.DictReader(f))
    rows = []
    for r in old:
        rows.append({
            "run_id": new_run_id(),
            "timestamp": r.get("timestamp", ""),
            "source": "legacy",
            "filename": r.get("filename", ""),
            "tokens_scored": r.get("tokens_scored", ""),
            "green_tokens": r.get("green_tokens", ""),
            "green_pct": r.get("green_fraction", ""),
            "z_score": r.get("z_score", ""),
            "result": LEGACY_LABELS.get(r.get("result", ""), r.get("result", "")),
        })
    _write_rows(rows)
    return archive


def new_run_id():
    return uuid.uuid4().hex[:8]


def append_history(stats, source="manual", filename="", extra=None):
    """Append one row and return its run_id. `stats` is Engine.detect()'s
    dict; `extra` may carry mode, batch_id, max_new_tokens, seed, gen_tokens,
    note. Raises OSError if the file cannot be written (for example while
    it is open in Excel); callers report that."""
    ensure_history()
    if source not in SOURCES:
        raise ValueError("source must be one of {}".format(SOURCES))
    extra = extra or {}
    wm = stats.get("watermark", {})
    row = {
        "run_id": new_run_id(),
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "filename": filename or "",
        "mode": extra.get("mode", ""),
        "batch_id": extra.get("batch_id", ""),
        "max_new_tokens": extra.get("max_new_tokens", ""),
        "seed": extra.get("seed", ""),
        "gen_tokens": extra.get("gen_tokens", ""),
        "tokens_scored": stats.get("num_tokens_scored", 0),
        "green_tokens": stats.get("num_green_tokens", 0),
        "green_pct": round(stats.get("green_fraction", 0.0) * 100, 2),
        "z_score": round(stats.get("z_score", 0.0), 2),
        "p_value": "{:.3e}".format(stats.get("p_value", 1.0)),
        "result": stats.get("label", ""),
        "bias": wm.get("bias", ""),
        "greenlist_ratio": wm.get("greenlist_ratio", ""),
        "seeding_scheme": wm.get("seeding_scheme", ""),
        "context_width": wm.get("context_width", ""),
        "device": stats.get("device", ""),
        "note": extra.get("note", ""),
    }
    with open(HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=COLUMNS).writerow(row)
    return row["run_id"]


def read_history():
    """All rows, newest first. Raises OSError, csv.Error or UnicodeDecodeError
    on a bad file rather than pretending the history is empty."""
    ensure_history()
    with open(HISTORY_PATH, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.reverse()
    return rows


def find_record(run_id):
    """The row with this run_id, or None."""
    for r in read_history():
        if r.get("run_id") == run_id:
            return r
    return None


def _rewrite_one(run_id, change):
    """Back up, then apply `change(row)` to exactly one row (or remove it
    when change returns None). Raises ValueError unless one row matches."""
    rows = read_history()
    rows.reverse()                                   # back to file order
    matches = [r for r in rows if r.get("run_id") == run_id]
    if len(matches) != 1:
        raise ValueError("{} record(s) match run_id {!r}; expected exactly one".format(
            len(matches), run_id))
    backup = backup_history()
    new_rows = []
    for r in rows:
        if r.get("run_id") == run_id:
            r = change(dict(r))
            if r is None:
                continue
        new_rows.append(r)
    try:
        _write_rows(new_rows)
    except OSError as exc:
        raise OSError("{} (the file is unchanged; a backup was written to {})".format(exc, backup)) from exc
    return backup


def update_record(run_id, **fields):
    """Change editable fields (note, filename) of one record. Returns the
    backup path. Measurements cannot be edited."""
    bad = [k for k in fields if k not in EDITABLE]
    if bad:
        raise ValueError("Not editable: {}".format(", ".join(bad)))

    def change(row):
        row.update({k: str(v) for k, v in fields.items()})
        return row
    return _rewrite_one(run_id, change)


def delete_record(run_id):
    """Remove one record by run_id. Returns the backup path."""
    return _rewrite_one(run_id, lambda row: None)


def backup_history():
    """Copy the current history file into logs/exports/ and return the path."""
    ensure_history()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    backup = EXPORT_DIR / "detection_history_backup_{}.csv".format(_stamp())
    shutil.copyfile(HISTORY_PATH, backup)
    return backup


def clear_history():
    """Back up the file, then truncate it to the header. Returns the backup path."""
    backup = backup_history()
    _write_rows([])
    return backup
