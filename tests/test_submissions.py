import hashlib
import json

import pytest

from classroom import assignments, classes, paths, submissions

ESSAY = "People keep diaries to remember.\r\nThey write to think, too.  "


def test_first_submission_writes_text_sidecar_and_index(course):
    a = course["assignment"]
    row = submissions.submit(a["assignment_id"], "alice", ESSAY, version_note="first try")
    assert row["version"] == "1" and row["status"] == "current" and row["source"] == "editor"
    txt = paths.resolve(row["text_path"])
    assert row["text_path"] == "submissions/{}/{}/alice/v001.txt".format(
        course["class"]["class_id"], a["assignment_id"])
    stored = submissions.read_text(row)
    assert stored == "People keep diaries to remember.\nThey write to think, too."
    assert row["sha256"] == hashlib.sha256(stored.encode("utf-8")).hexdigest()
    assert row["words"] == "10"
    side = json.loads(txt.with_suffix(".json").read_text(encoding="utf-8"))
    assert side["submission_id"] == row["submission_id"] and "generation" not in side


def test_resubmitting_keeps_every_version(course):
    a = course["assignment"]
    v1 = submissions.submit(a["assignment_id"], "alice", "first version of the essay")
    v2 = submissions.submit(a["assignment_id"], "alice", "second version of the essay", "upload",
                            upload_filename="essay.txt", version_note="fixed typos")
    assert v2["version"] == "2" and v2["upload_filename"] == "essay.txt"
    versions = submissions.versions(a["assignment_id"], "alice")
    assert [(v["version"], v["status"]) for v in versions] == [("1", "superseded"), ("2", "current")]
    assert submissions.read_text(v1) == "first version of the essay"      # v001 untouched
    assert submissions.current_submission(a["assignment_id"], "alice")["submission_id"] == v2["submission_id"]
    assert list(paths.backups_dir().glob("submissions_*.csv"))          # the rewrite was backed up


def test_assistant_generation_is_recorded_without_the_key(course):
    a = course["assignment"]
    gen = {"prompt": "Write about diaries", "seed": 7, "mode": "watermarked", "model_id": "m",
           "key_id": "0a1b2c3d", "hashing_key": 123456789, "text": "..."}
    row = submissions.submit(a["assignment_id"], "alice", "drafted text here", "assistant",
                             generation=gen)
    side = submissions.sidecar(row)
    assert side["generation"] == {"prompt": "Write about diaries", "seed": 7, "mode": "watermarked",
                                  "model_id": "m", "key_id": "0a1b2c3d"}
    assert "123456789" not in json.dumps(side)


@pytest.mark.parametrize("who, text, match", [
    ("ben", "not in the class", "not in the class"),
    ("alice", "   \n ", "empty"),
    ("alice", "x" * (submissions.MAX_CHARS + 1), "limited"),
], ids=["not-a-member", "empty", "too-long"])
def test_submit_refuses(course, who, text, match):
    with pytest.raises(ValueError, match=match):
        submissions.submit(course["assignment"]["assignment_id"], who, text)


def test_closed_assignment_refuses_submissions(course):
    a = course["assignment"]
    assignments.close_assignment(a["assignment_id"])
    with pytest.raises(ValueError, match="closed"):
        submissions.submit(a["assignment_id"], "alice", "late essay")


def test_a_left_over_file_is_never_overwritten(course):
    a = course["assignment"]
    folder = submissions.submission_dir(course["class"]["class_id"], a["assignment_id"], "alice")
    folder.mkdir(parents=True)
    (folder / "v001.txt").write_text("orphan from a crash", encoding="utf-8")
    row = submissions.submit(a["assignment_id"], "alice", "real essay")
    assert row["text_path"].endswith("v002.txt")
    assert (folder / "v001.txt").read_text(encoding="utf-8") == "orphan from a crash"


def test_listing(course, people):
    a = course["assignment"]
    classes.join_class(course["class"]["join_code"], "ben")
    submissions.submit(a["assignment_id"], "alice", "alice essay")
    submissions.submit(a["assignment_id"], "ben", "ben essay")
    submissions.submit(a["assignment_id"], "ben", "ben essay again")
    assert len(submissions.list_submissions(a["assignment_id"])) == 2
    assert len(submissions.list_submissions(a["assignment_id"], current_only=False)) == 3
    assert [r["username"] for r in submissions.list_submissions(username="ben")] == ["ben"]
