import json

import pytest

from classroom import accounts, audit, classes, cli, paths


def test_hash_format_and_verify():
    stored = accounts.hash_password("correct horse", iterations=1000)
    algorithm, iterations, salt, digest = stored.split("$")
    assert algorithm == "pbkdf2_sha256" and iterations == "1000"
    assert len(salt) == 32 and len(digest) == 64
    assert accounts.verify_password("correct horse", stored)
    assert not accounts.verify_password("wrong horse", stored)
    assert not accounts.verify_password("x", "garbage")
    assert accounts.hash_password("same", iterations=1000) != accounts.hash_password("same", iterations=1000)


def test_register_normalises_and_never_stores_the_password(data_dir):
    user = accounts.register("  Alice ", "s3cret-pass", "student", "Alice  Santos")
    assert user == {"username": "alice", "display_name": "Alice Santos", "role": "student",
                    "created_at": user["created_at"], "last_login": "", "must_change": False}
    raw = paths.users_path().read_text(encoding="utf-8")
    assert "s3cret-pass" not in raw
    assert json.loads(raw)["users"]["alice"]["password"].startswith("pbkdf2_sha256$1000$")


@pytest.mark.parametrize("username, password, role", [
    ("al", "longenough", "student"),          # too short
    ("al ice", "longenough", "student"),      # space
    ("-alice", "longenough", "student"),      # bad first character
    ("alice", "short", "student"),            # weak password
    ("alice", "longenough", "admin"),         # unknown role
])
def test_register_rejects_bad_input(data_dir, username, password, role):
    with pytest.raises(ValueError):
        accounts.register(username, password, role)
    assert not accounts.exists("alice")


def test_duplicate_username_is_refused(data_dir):
    accounts.register("alice", "longenough", "student")
    with pytest.raises(ValueError, match="taken"):
        accounts.register("ALICE", "otherpassword", "student")


def test_authenticate(data_dir):
    accounts.register("prof", "teacherpass", "teacher", "Prof. Reyes")
    assert accounts.authenticate("prof", "nope") is None
    assert accounts.authenticate("nobody", "teacherpass") is None
    user = accounts.authenticate("PROF", "teacherpass")
    assert user["role"] == "teacher" and "password" not in user
    first = accounts.get_user("prof")["last_login"]
    assert first != "" and user["previous_login"] == ""          # a first sign-in has none before it
    assert accounts.authenticate("prof", "teacherpass")["previous_login"] == first


def test_has_teacher_and_listing(data_dir):
    assert not accounts.has_teacher()
    accounts.register("alice", "longenough", "student", "Alice Santos")
    assert not accounts.has_teacher()
    accounts.register("prof", "teacherpass", "teacher")
    assert accounts.has_teacher()
    assert [u["username"] for u in accounts.list_users("student")] == ["alice"]
    assert accounts.display_names() == {"alice": "Alice Santos", "prof": "prof"}


def test_change_password(data_dir):
    accounts.register("alice", "longenough", "student")
    with pytest.raises(ValueError, match="not correct"):
        accounts.change_password("alice", "wrong", "brandnewpass")
    with pytest.raises(ValueError, match="at least"):
        accounts.change_password("alice", "longenough", "short")
    accounts.change_password("alice", "longenough", "brandnewpass")
    assert accounts.authenticate("alice", "brandnewpass")
    assert accounts.authenticate("alice", "longenough") is None


def test_rename(data_dir):
    accounts.register("alice", "longenough", "student")
    assert accounts.rename("alice", " Alice   S. ")["display_name"] == "Alice S."
    with pytest.raises(ValueError):
        accounts.rename("alice", "   ")


def test_cli_create_teacher_list_and_reset(data_dir, monkeypatch, capsys):
    answers = iter(["teacherpass", "teacherpass"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    assert cli.main(["create-teacher", "Reyes", "--display-name", "Prof. Reyes"]) == 0
    assert accounts.get_user("reyes")["role"] == "teacher"

    answers = iter(["abcdefgh", "different"])
    assert cli.main(["create-teacher", "other"]) == 1          # passwords do not match
    assert "do not match" in capsys.readouterr().err

    assert cli.main(["list-users"]) == 0
    assert "reyes" in capsys.readouterr().out

    assert cli.main(["reset-password", "ghost"]) == 1
    answers = iter(["newpassword", "newpassword"])
    assert cli.main(["reset-password", "reyes"]) == 0
    assert accounts.authenticate("reyes", "newpassword")


@pytest.mark.parametrize("password, username, problem", [
    ("short", "", "at least"),
    ("password123", "", "common"),
    ("marktext-demo", "", "common"),               # the demo password older versions printed
    ("alice.santos-2026", "alice.santos", "username"),
    ("aaaaaaaaab", "", "four different"),
    ("correct horse battery", "alice", None),
])
def test_password_rules(password, username, problem):
    found = accounts.password_problem(password, username)
    assert (found is None) if problem is None else (problem in found)


def test_weak_passwords_are_refused_for_new_accounts_and_changes(data_dir):
    with pytest.raises(ValueError, match="common"):
        accounts.register("carol", "iloveyou1", "student")
    accounts.register("carol", "studentpass", "student")
    with pytest.raises(ValueError, match="username"):
        accounts.reset_password("carol", "carol-2026-x")


def test_sign_in_works_while_users_json_is_open_elsewhere(data_dir, excel_lock):
    accounts.register("carol", "studentpass", "student")
    excel_lock(paths.users_path())
    user = accounts.authenticate("carol", "studentpass")
    assert user["username"] == "carol" and user["last_login"] == ""


@pytest.mark.parametrize("name", ["alice.", "alice-", "_alice", "nul", "con.txt", "com1", "lpt9.x"])
def test_usernames_that_windows_cannot_use_as_folders_are_refused(data_dir, name):
    with pytest.raises(ValueError):
        accounts.register(name, "studentpass", "student")


def test_a_missing_account_costs_the_same_hashing_as_a_wrong_password(data_dir, monkeypatch):
    checked = []
    real = accounts.verify_password
    monkeypatch.setattr(accounts, "verify_password", lambda pw, stored: checked.append(stored) or real(pw, stored))
    assert accounts.authenticate("nobody", "whatever1") is None
    assert len(checked) == 1 and checked[0].startswith("pbkdf2_sha256$1000$")


def test_sign_in_pauses_after_repeated_wrong_passwords(data_dir, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(accounts.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(accounts, "_failures", {})
    accounts.register("carol", "studentpass", "student")
    for _ in range(accounts.MAX_FAILURES):
        assert accounts.authenticate("carol", "wrong-guess") is None
    with pytest.raises(accounts.TooManyAttempts, match="Wait 30 seconds"):
        accounts.authenticate("carol", "studentpass")            # even the right one waits
    clock[0] += accounts.PAUSE + 1
    assert accounts.authenticate("carol", "studentpass")["username"] == "carol"
    assert "carol" not in accounts._failures                      # success clears the count


def test_the_setup_screen_cannot_make_a_second_teacher(data_dir):
    accounts.register("reyes", "teacherpass", "teacher", first_teacher=True)
    with pytest.raises(ValueError, match="already exists"):
        accounts.register("other", "teacherpass", "teacher", first_teacher=True)


def test_a_teacher_resets_a_students_password(course, people):
    cid = course["class"]["class_id"]
    with pytest.raises(ValueError, match="class's teacher"):
        classes.reset_student_password(cid, "alice", by="ben")
    with pytest.raises(ValueError, match="not an active student"):
        classes.reset_student_password(cid, "ben", by="prof")
    temporary = classes.reset_student_password(cid, "alice", by="prof")
    assert accounts.authenticate("alice", "studentpass") is None
    user = accounts.authenticate("alice", temporary)
    assert user["must_change"] is True
    accounts.change_password("alice", temporary, "my-own-pass-7")
    assert accounts.authenticate("alice", "my-own-pass-7")["must_change"] is False
    assert audit.read(action="password_reset")[0]["actor"] == "prof"


def test_the_command_line_rotates_the_key(data_dir, tmp_path, monkeypatch, capsys):
    import config as cfg
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "wm.json")
    old = cfg.load_config()["watermark"]["key_id"]
    assert cli.main(["rotate-key"]) == 0
    assert old in capsys.readouterr().out
    assert cfg.load_config()["watermark"]["retired_keys"][0]["key_id"] == old
    assert audit.read(action="key_rotated")[0]["details"] == "replaced key {}".format(old)

