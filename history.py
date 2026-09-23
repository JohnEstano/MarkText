"""Detection history log for MarkText (was detector.py).

Every analysis appends one row to logs/detection_history.csv with the
csv module. This module never classifies: the verdict label comes from
Engine.detect(), so both front-ends and the log agree by construction.
"""

import csv
import datetime
import pathlib
import shutil

BASE_DIR = pathlib.Path(__file__).resolve().parent
HISTORY_PATH = BASE_DIR / "logs" / "detection_history.csv"
EXPORT_DIR = BASE_DIR / "logs" / "exports"

COLUMNS = [
    "timestamp",
    "filename",
    "tokens_scored",
    "green_tokens",
    "green_fraction",
    "z_score",
    "result",
]


def ensure_history():
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not HISTORY_PATH.exists() or HISTORY_PATH.stat().st_size == 0:
        with open(HISTORY_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=COLUMNS).writeheader()


def append_history(filename, stats):
    """Append one row. Raises OSError if the file cannot be written
    (for example while it is open in Excel); callers report that."""
    ensure_history()
    row = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filename": filename or "manual_input",
        "tokens_scored": stats.get("num_tokens_scored", 0),
        "green_tokens": stats.get("num_green_tokens", 0),
        "green_fraction": round(stats.get("green_fraction", 0.0) * 100, 2),
        "z_score": round(stats.get("z_score", 0.0), 2),
        "result": stats.get("label", ""),
    }
    with open(HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=COLUMNS).writerow(row)


def read_history():
    """All rows, newest first. Raises OSError, csv.Error or UnicodeDecodeError
    on a bad file rather than pretending the history is empty."""
    ensure_history()
    with open(HISTORY_PATH, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.reverse()
    return rows


def backup_history():
    """Copy the current history file into logs/exports/ and return the path."""
    ensure_history()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = EXPORT_DIR / "detection_history_backup_{}.csv".format(stamp)
    shutil.copyfile(HISTORY_PATH, backup)
    return backup


def clear_history():
    """Back up the file, then truncate it to the header. Returns the backup path."""
    backup = backup_history()
    with open(HISTORY_PATH, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=COLUMNS).writeheader()
    return backup
