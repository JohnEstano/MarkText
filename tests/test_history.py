import csv

import pytest

import history


@pytest.fixture
def hist(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "logs" / "h.csv")
    monkeypatch.setattr(history, "EXPORT_DIR", tmp_path / "logs" / "exports")
    return history


STATS = {"num_tokens_scored": 277, "num_green_tokens": 193,
         "green_fraction": 193 / 277, "z_score": 6.5492, "label": "LIKELY MARKTEXT"}


def test_ensure_creates_header_once(hist):
    hist.ensure_history()
    assert hist.HISTORY_PATH.read_text(encoding="utf-8").splitlines() == [",".join(hist.COLUMNS)]
    hist.append_history("a.txt", STATS)
    hist.ensure_history()                       # must not rewrite a non-empty file
    assert len(hist.read_history()) == 1


def test_append_and_read_round_trip(hist):
    hist.append_history("a.txt", STATS)
    hist.append_history("", STATS)             # empty name -> manual_input
    rows = hist.read_history()
    assert [r["filename"] for r in rows] == ["manual_input", "a.txt"]   # newest first
    assert rows[1]["green_fraction"] == "69.68"
    assert rows[1]["z_score"] == "6.55"
    assert rows[1]["result"] == "LIKELY MARKTEXT"
    assert rows[1]["tokens_scored"] == "277"


def test_csv_uses_crlf_and_no_blank_lines(hist):
    hist.append_history("a.txt", STATS)
    raw = hist.HISTORY_PATH.read_bytes()
    assert raw.count(b"\r\n") == 2 and b"\r\n\r\n" not in raw


def test_clear_writes_backup_then_truncates(hist):
    hist.append_history("a.txt", STATS)
    before = hist.HISTORY_PATH.read_bytes()
    backup = hist.clear_history()
    assert backup.read_bytes() == before
    assert hist.read_history() == []
    assert hist.HISTORY_PATH.read_text(encoding="utf-8").splitlines() == [",".join(hist.COLUMNS)]


def test_read_raises_on_bad_csv(hist):
    hist.HISTORY_PATH.parent.mkdir(parents=True)
    hist.HISTORY_PATH.write_bytes(b"\xff\xfe not text")
    with pytest.raises((csv.Error, OSError, UnicodeDecodeError)):
        hist.read_history()
