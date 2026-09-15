"""Detection history logging for MarkText.

Every analysis appends one row to logs/detection_history.csv.
This demonstrates the UPDATE / APPEND pattern on a CSV file.
"""

import csv
import datetime
import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent
HISTORY_PATH = BASE_DIR / "logs" / "detection_history.csv"

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
    ensure_history()
    row = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filename": filename,
        "tokens_scored": stats.get("num_tokens_scored", 0),
        "green_tokens": stats.get("num_green_tokens", 0),
        "green_fraction": round(stats.get("green_fraction", 0.0) * 100, 2),
        "z_score": round(stats.get("z_score", 0.0), 2),
        "result": classify_z(stats.get("z_score", 0.0)),
    }
    with open(HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=COLUMNS).writerow(row)


def classify_z(z):
    if z >= 4.0:
        return "LIKELY MARKTEXT"
    if z >= 2.0:
        return "POSSIBLE WATERMARK"
    return "NO WATERMARK"


def read_history():
    ensure_history()
    rows = []
    try:
        with open(HISTORY_PATH, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    except (OSError, csv.Error):
        return []
    rows.reverse()
    return rows


def clear_history():
    ensure_history()
    with open(HISTORY_PATH, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=COLUMNS).writeheader()
