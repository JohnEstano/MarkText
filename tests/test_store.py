import csv
import datetime
import json

import pytest

from classroom import paths, store

COLS = ["id", "name", "text"]


def test_read_json_returns_a_copy_of_the_default(data_dir):
    default = {"version": 1, "items": {}}
    data = store.read_json(data_dir / "x.json", default)
    data["items"]["a"] = 1
    assert default == {"version": 1, "items": {}}


def test_write_json_round_trip_backup_and_no_temp_left(data_dir):
    path = data_dir / "x.json"
    assert store.write_json(path, {"a": 1}) is None            # nothing to back up yet
    saved = store.write_json(path, {"a": 2})
    assert json.loads(saved.read_text(encoding="utf-8")) == {"a": 1}
    assert store.read_json(path, {}) == {"a": 2}
    assert not list(data_dir.glob("*.tmp"))


def test_damaged_json_raises_and_is_left_alone(data_dir):
    path = data_dir / "x.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        store.read_json(path, {})
    assert path.read_text(encoding="utf-8") == "{broken"


def test_update_json_failure_leaves_the_file_untouched(data_dir):
    path = data_dir / "x.json"
    store.write_json(path, {"n": 1})

    def bad(data):
        data["n"] = 99
        raise ValueError("nope")
    with pytest.raises(ValueError):
        store.update_json(path, {}, bad)
    assert store.read_json(path, {}) == {"n": 1}


def test_csv_round_trip_with_awkward_text(data_dir):
    path = data_dir / "t.csv"
    text = 'Line one, with a comma\nline "two"'
    store.append_row(path, COLS, {"id": "1", "name": None, "text": text})
    rows = store.read_rows(path, COLS)
    assert rows == [{"id": "1", "name": "", "text": text}]
    assert path.read_bytes().startswith(b"id,name,text\r\n")


def test_foreign_header_raises_and_file_is_unchanged(data_dir):
    path = data_dir / "t.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expects"):
        store.read_rows(path, COLS)
    assert path.read_text(encoding="utf-8") == "a,b\n1,2\n"


def test_older_shorter_header_is_extended_with_a_backup(data_dir):
    path = data_dir / "t.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["id", "name"], ["1", "ann"]])
    rows = store.read_rows(path, COLS)
    assert rows == [{"id": "1", "name": "ann", "text": ""}]
    assert list(paths.backups_dir().glob("t_*.csv"))


def test_rewrite_rows_keeps_a_copy_of_the_old_file(data_dir):
    path = data_dir / "t.csv"
    store.append_row(path, COLS, {"id": "1", "name": "a", "text": "x"})
    before = path.read_bytes()
    saved = store.rewrite_rows(path, COLS, [])
    assert saved.read_bytes() == before
    assert store.read_rows(path, COLS) == []


def test_update_one_needs_exactly_one_match(data_dir):
    path = data_dir / "t.csv"
    for i, name in (("1", "a"), ("2", "b"), ("2", "c")):
        store.append_row(path, COLS, {"id": i, "name": name, "text": ""})
    with pytest.raises(ValueError, match="0 row"):
        store.update_one(path, COLS, "id", "9", lambda r: r)
    with pytest.raises(ValueError, match="2 row"):
        store.update_one(path, COLS, "id", "2", lambda r: r)
    store.update_one(path, COLS, "id", "1", lambda r: dict(r, name="z"))
    assert store.read_rows(path, COLS)[0]["name"] == "z"
    store.update_one(path, COLS, "name", "b", lambda r: None)      # drop one row
    assert [r["name"] for r in store.read_rows(path, COLS)] == ["z", "c"]


def test_backups_in_the_same_second_do_not_overwrite(data_dir):
    path = data_dir / "x.json"
    store.write_json(path, {"v": 1})
    a = store.write_json(path, {"v": 2})
    b = store.write_json(path, {"v": 3})
    assert a != b and a.exists() and b.exists()


def test_lock_is_shared_per_file(data_dir):
    assert store.lock_for(data_dir / "x.json") is store.lock_for(data_dir / "sub" / ".." / "x.json")
    assert store.lock_for(data_dir / "x.json") is not store.lock_for(data_dir / "y.json")


def test_paths_are_stored_relative_to_the_data_folder(data_dir):
    target = paths.submissions_dir() / "c" / "v001.txt"
    rel = paths.data_relative(target)
    assert rel == "submissions/c/v001.txt"
    assert paths.resolve(rel) == target


def test_a_byte_order_mark_from_excel_is_ignored(data_dir):
    path = data_dir / "t.csv"
    path.write_bytes("\ufeffa,b\r\n1,x\r\n".encode("utf-8"))
    assert store.read_rows(path, ["a", "b"]) == [{"a": "1", "b": "x"}]
    store.append_row(path, ["a", "b"], {"a": "2", "b": "y"})
    assert [r["a"] for r in store.read_rows(path, ["a", "b"])] == ["1", "2"]
    j = data_dir / "t.json"
    j.write_bytes("\ufeff{\"k\": 1}".encode("utf-8"))
    assert store.read_json(j, {}) == {"k": 1}


def test_a_locked_file_raises_a_message_that_names_it(data_dir, excel_lock):
    path = data_dir / "t.csv"
    store.append_row(path, ["a"], {"a": "1"})
    excel_lock(path)
    with pytest.raises(store.FileProblem, match="data/t.csv.*Excel"):
        store.append_row(path, ["a"], {"a": "2"})
    with pytest.raises(ValueError, match="Close it"):          # a ValueError for the pages
        store.rewrite_rows(path, ["a"], [{"a": "3"}])
    assert store.read_rows(path, ["a"]) == [{"a": "1"}]       # reading still works, nothing changed
    assert not path.with_name("t.csv.tmp").exists()


def test_check_writable_writes_nothing(data_dir, excel_lock):
    path = data_dir / "t.csv"
    store.append_row(path, ["a"], {"a": "1"})
    before = path.read_bytes()
    store.check_writable(path, data_dir / "missing.csv")
    assert path.read_bytes() == before and not (data_dir / "missing.csv").exists()
    excel_lock(path)
    with pytest.raises(store.FileProblem):
        store.check_writable(path)


@pytest.mark.parametrize("text, expected", [
    ("2026-10-15", datetime.date(2026, 10, 15)),
    ("10/15/2026", datetime.date(2026, 10, 15)),               # how Excel saves it back
    ("2026/10/15", datetime.date(2026, 10, 15)),
    ("2026-09-29 14:05:12", datetime.date(2026, 9, 29)),
    ("tomorrow", None), ("", None), (None, None),
])
def test_dates_as_excel_writes_them(text, expected):
    assert store.parse_date(text) == expected


def test_timestamps_as_excel_writes_them():
    assert store.parse_time("9/29/2026 14:05") == datetime.datetime(2026, 9, 29, 14, 5)
    assert store.parse_time("2026-09-29 14:05:12") == datetime.datetime(2026, 9, 29, 14, 5, 12)
    assert store.parse_time("soon") is None
