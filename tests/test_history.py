import csv

import pytest

import history


@pytest.fixture
def hist(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "logs" / "h.csv")
    monkeypatch.setattr(history, "EXPORT_DIR", tmp_path / "logs" / "exports")
    return history


STATS = {"num_tokens_scored": 277, "num_green_tokens": 193,
         "green_fraction": 193 / 277, "z_score": 6.5492, "p_value": 2.9e-11,
         "label": "LIKELY MARKTEXT", "device": "cpu",
         "watermark": {"bias": 3.0, "greenlist_ratio": 0.5, "seeding_scheme": "selfhash",
                       "context_width": 5}}

LEGACY = ("timestamp,filename,tokens_scored,green_tokens,green_fraction,z_score,result\r\n"
          "2026-09-15 10:40:16,manual_input,277,193,69.68,6.55,LIKELY MARKTEXT\r\n"
          "2026-09-15 10:46:20,,325,173,53.23,1.16,NO WATERMARK\r\n")


def test_ensure_creates_header_once(hist):
    hist.ensure_history()
    assert hist.HISTORY_PATH.read_text(encoding="utf-8").splitlines() == [",".join(hist.COLUMNS)]
    hist.append_history(STATS, source="file", filename="a.txt")
    hist.ensure_history()                       # must not rewrite a non-empty file
    assert len(hist.read_history()) == 1


def test_append_returns_unique_ids_and_all_columns(hist):
    a = hist.append_history(STATS, source="file", filename="a.txt")
    b = hist.append_history(STATS, source="manual",
                            extra={"mode": "watermarked", "seed": 42, "batch_id": "b1",
                                   "max_new_tokens": 300, "gen_tokens": 281, "note": "hi"})
    assert a != b and len(a) == 8
    rows = hist.read_history()                  # newest first
    assert rows[0]["run_id"] == b and rows[1]["run_id"] == a
    r = rows[0]
    assert r["source"] == "manual" and r["filename"] == ""
    assert r["mode"] == "watermarked" and r["seed"] == "42" and r["batch_id"] == "b1"
    assert r["green_pct"] == "69.68" and r["z_score"] == "6.55" and r["p_value"] == "2.900e-11"
    assert r["bias"] == "3.0" and r["context_width"] == "5" and r["device"] == "cpu"
    assert r["note"] == "hi" and r["result"] == "LIKELY MARKTEXT"
    assert list(r.keys()) == hist.COLUMNS


def test_append_rejects_unknown_source(hist):
    with pytest.raises(ValueError):
        hist.append_history(STATS, source="robot")


def test_csv_uses_crlf_and_no_blank_lines(hist):
    hist.append_history(STATS, source="file", filename="a.txt")
    raw = hist.HISTORY_PATH.read_bytes()
    assert raw.count(b"\r\n") == 2 and b"\r\n\r\n" not in raw


def test_legacy_file_is_migrated_and_archived(hist):
    hist.HISTORY_PATH.parent.mkdir(parents=True)
    hist.HISTORY_PATH.write_bytes(LEGACY.encode("utf-8"))
    archive = hist.ensure_history()
    assert archive is not None and archive.read_bytes() == LEGACY.encode("utf-8")
    rows = hist.read_history()
    assert len(rows) == 2
    assert {r["source"] for r in rows} == {"legacy"}
    assert len({r["run_id"] for r in rows}) == 2
    old_row = rows[1]                            # the first legacy line
    assert old_row["green_pct"] == "69.68" and old_row["filename"] == "manual_input"
    assert rows[0]["result"] == "NOT DETECTED"   # NO WATERMARK normalised
    assert hist.ensure_history() is None         # second call: nothing to do


def test_unknown_header_raises(hist):
    hist.HISTORY_PATH.parent.mkdir(parents=True)
    hist.HISTORY_PATH.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        hist.ensure_history()


def test_update_note_and_filename_only(hist):
    rid = hist.append_history(STATS, source="file", filename="a.txt")
    hist.append_history(STATS, source="manual")
    backup = hist.update_record(rid, note="checked", filename="b.txt")
    assert backup.exists()
    r = hist.find_record(rid)
    assert r["note"] == "checked" and r["filename"] == "b.txt"
    assert r["z_score"] == "6.55"                # measurement untouched
    assert len(hist.read_history()) == 2
    with pytest.raises(ValueError):
        hist.update_record(rid, z_score="0")


def test_update_and_delete_require_exactly_one_match(hist):
    rid = hist.append_history(STATS, source="manual")
    with pytest.raises(ValueError):
        hist.update_record("nope", note="x")
    with pytest.raises(ValueError):
        hist.delete_record("nope")
    hist.delete_record(rid)
    assert hist.read_history() == [] and hist.find_record(rid) is None


def test_clear_writes_backup_then_truncates(hist):
    hist.append_history(STATS, source="manual")
    before = hist.HISTORY_PATH.read_bytes()
    backup = hist.clear_history()
    assert backup.read_bytes() == before
    assert hist.read_history() == []


def test_read_raises_on_bad_csv(hist):
    hist.HISTORY_PATH.parent.mkdir(parents=True)
    hist.HISTORY_PATH.write_bytes(b"\xff\xfe not text")
    with pytest.raises((csv.Error, OSError, UnicodeDecodeError)):
        hist.read_history()


def test_submission_is_a_known_source(hist):
    assert "submission" in hist.SOURCES
    rid = hist.append_history(STATS, source="submission", filename="data/submissions/x/v001.txt",
                              extra={"note": '{"submission_id": "sub_1"}'})
    assert hist.find_record(rid)["source"] == "submission"


def test_an_older_shorter_header_is_extended_with_a_backup(hist):
    older = hist.COLUMNS[:hist.COLUMNS.index("note") + 1]           # the 21-column layout
    hist.HISTORY_PATH.parent.mkdir(parents=True)
    with open(hist.HISTORY_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=older)
        w.writeheader()
        w.writerow({"run_id": "abc12345", "z_score": "1.5", "result": "NOT DETECTED"})
    backup = hist.ensure_history()
    assert backup is not None and backup.exists()
    rows = hist.read_history()
    assert list(rows[0].keys()) == hist.COLUMNS and rows[0]["run_id"] == "abc12345"
    assert rows[0]["passage_z"] == ""


def test_the_passage_and_repeats_are_logged(hist):
    passage = {"z": 5.123, "p": 2.4e-6, "start": 10, "end": 900}
    run_id = hist.append_history(dict(STATS, repeated=3, passage=passage))
    row = hist.find_record(run_id)
    assert (row["repeated"], row["passage_z"], row["passage_p"]) == ("3", "5.12", "2.400e-06")
