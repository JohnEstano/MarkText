from classroom import drafts, paths, store


def test_a_draft_is_kept_read_back_and_removed(data_dir):
    assert drafts.load("alice", "asg_1") is None
    saved = drafts.save("alice", "asg_1", "My essay so far.", "assistant",
                        generation={"seed": 42, "text": "The assistant's words."})
    path = drafts.path_for("alice", "asg_1")
    assert path == paths.drafts_dir() / "alice" / "asg_1.json"
    assert drafts.load("alice", "asg_1") == saved
    assert saved["source"] == "assistant" and saved["generation"]["seed"] == 42
    assert not [p for p in path.parent.iterdir() if p.suffix in (".tmp", ".lock")]   # atomic, tidy
    assert not list(paths.backups_dir().glob("asg_1*"))      # rewritten often: no backup copies
    drafts.save("alice", "asg_1", "   ")                     # an emptied editor removes the draft
    assert drafts.load("alice", "asg_1") is None and not path.exists()
    drafts.discard("alice", "asg_1")                         # nothing to delete: no error


def test_the_newest_draft_opens_first(data_dir, monkeypatch):
    times = iter(["2026-10-01 09:00:00", "2026-10-01 09:05:00"])
    monkeypatch.setattr(store, "now", lambda: next(times))
    drafts.save("alice", "asg_1", "older")
    drafts.save("alice", "asg_2", "newer")
    assert drafts.newest("alice", ["asg_1", "asg_2"]) == "asg_2"
    assert drafts.newest("alice", ["asg_1"]) == "asg_1"
    assert drafts.newest("ben", ["asg_1", "asg_2"]) is None


def test_a_damaged_draft_does_not_stop_the_student(data_dir):
    path = drafts.path_for("alice", "asg_1")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert drafts.load("alice", "asg_1") is None
    drafts.save("alice", "asg_1", "A fresh start.")          # replaced by the next save
    assert drafts.load("alice", "asg_1")["text"] == "A fresh start."
