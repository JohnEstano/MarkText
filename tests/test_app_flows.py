"""The classroom app, driven headlessly with Streamlit's AppTest and a fake
engine: sign-in, the teacher's and the student's flows, the dialogs, the
exports and the assistant switch. No browser, no model."""

import json
import pathlib
import threading
import time

import pytest
from fakes import FakeEngine
from streamlit.testing.v1 import AppTest

import config as cfg
import history
from classroom import (accounts, assignments, assistant, backups, classes, detection, drafts, paths, reports,
                       reviews, store, submissions)
from ui import common, lab

ROOT = pathlib.Path(__file__).resolve().parent.parent
ESSAY = "People keep diaries to remember the small things. " * 25


@pytest.fixture
def new_app(data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "wm.json")
    monkeypatch.setattr(common, "make_engine", lambda config: FakeEngine(config))
    monkeypatch.setattr(common, "make_scorer", lambda config: FakeEngine(config))
    monkeypatch.setattr(lab, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(lab, "EXPORT_DIR", tmp_path / "logs" / "exports")
    common.get_engine.clear()
    common.get_scorer.clear()
    common.MODEL.update(loaded=False)

    def make():
        return AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    yield make
    common.get_engine.clear()
    common.get_scorer.clear()


def ok(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def sign_in(at, username, password):
    at.text_input(key="login_username").input(username)
    at.text_input(key="login_password").input(password)
    return ok(at.button(key="login_submit").click().run())


def follow(at, page):
    """AppTest follows st.switch_page only within one run; the browser keeps
    the new page. Re-open it the way the browser would."""
    return ok(at.switch_page("app_pages/{}.py".format(page)).run())


def titles(at):
    return [t.value for t in at.title]


def subheaders(at):
    return [s.value for s in at.subheader]


@pytest.fixture
def school(people):
    cls = classes.create_class("Intro to writing", "prof", "Term 1")
    task = assignments.create_assignment(cls["class_id"], "Why people keep diaries",
                                         "About 200 words.", "", "prof")
    classes.join_class(cls["join_code"], "alice")
    return {"class": cls, "assignment": task}


def test_first_run_creates_the_teacher(new_app):
    at = ok(new_app())
    assert "Set up the classroom" in subheaders(at)
    at.text_input(key="setup_username").input("Reyes")
    at.text_input(key="setup_name").input("Prof. Reyes")
    at.text_input(key="setup_password").input("teacherpass")
    at.text_input(key="setup_repeat").input("teacherpass")
    ok(at.button(key="setup_submit").click().run())
    assert titles(at) == ["Hello, Prof. Reyes"]
    assert accounts.get_user("reyes")["role"] == "teacher"
    assert at.button(key="home_new_class")                      # empty state offers a class


def test_register_and_bad_password(new_app, people):
    at = ok(new_app())
    assert "Set up the classroom" not in subheaders(at)
    sign_in(at, "alice", "wrong password")
    assert at.error[0].value == "That username and password do not match."
    at.segmented_control(key="login_mode").set_value("Register").run()
    at.text_input(key="register_username").input("carl")
    at.text_input(key="register_name").input("Carl Mendoza")
    at.text_input(key="register_password").input("studentpass")
    at.text_input(key="register_repeat").input("studentpass")
    ok(at.button(key="register_submit").click().run())
    assert titles(at) == ["Hello, Carl"] and accounts.get_user("carl")["role"] == "student"


def test_teacher_creates_a_class_and_an_assignment_in_dialogs(new_app, people):
    at = sign_in(new_app(), "prof", "teacherpass")
    ok(at.button(key="home_new_class").click().run())
    at.text_input(key="new_class_name").input("Research methods")
    ok(at.button(key="new_class_create").click().run())
    created = classes.list_classes("prof")
    assert [c["name"] for c in created] == ["Research methods"]
    assert titles(at)[0] == "Research methods"                  # the app switched to the class
    follow(at, "teacher_classes")
    cid = created[0]["class_id"]
    ok(at.button(key="task_new_" + cid).click().run())
    at.text_input(key="new_task_title").input("Interview a scientist")
    at.text_area(key="new_task_instructions").input("Two pages.")
    ok(at.button(key="new_task_create").click().run())
    assert [t["title"] for t in assignments.list_assignments(cid)] == ["Interview a scientist"]
    assert "Assignment created. Students in the class can see it now." in [t.value for t in at.toast]


def test_student_joins_with_a_code_and_hands_in_two_versions(new_app, people):
    cls = classes.create_class("Intro", "prof")
    task = assignments.create_assignment(cls["class_id"], "Diaries", "", "", "prof")
    aid = task["assignment_id"]
    at = sign_in(new_app(), "ben", "studentpass")
    assert any("You are not in a class yet" in m.value for m in at.markdown)
    at.text_input(key="join_code").input(classes.format_code(cls["join_code"]).lower())
    ok(at.button(key="join_submit").click().run())
    assert classes.is_member(cls["class_id"], "ben")
    ok(at.button(key="open_" + aid).click().run())
    assert titles(at) == ["Assignment"]
    follow(at, "student_assignment")
    at.text_area(key="editor_" + aid).input(ESSAY)
    ok(at.button(key="hand_in").click().run())
    at.text_area(key="editor_" + aid).input(ESSAY + " Revised.")
    at.text_input(key="version_note_" + aid).input("fixed the ending")
    ok(at.button(key="hand_in").click().run())
    versions = submissions.versions(aid, "ben")
    assert [(v["version"], v["status"]) for v in versions] == [("1", "superseded"), ("2", "current")]
    assert versions[1]["version_note"] == "fixed the ending"


def test_teacher_scores_decides_returns_and_the_student_sees_only_the_decision(new_app, school):
    aid = school["assignment"]["assignment_id"]
    submissions.submit(aid, "alice", ESSAY)
    at = sign_in(new_app(), "prof", "teacherpass")
    ok(at.switch_page("app_pages/teacher_review.py").run())
    ok(at.button(key="score_all").click().run())
    sub = submissions.current_submission(aid, "alice")
    review = reviews.latest_review(sub["submission_id"])
    assert review["label"] == "NOT DETECTED" and history.find_record(review["run_id"])["source"] == "submission"
    rid = review["review_id"]
    at.segmented_control(key="decision_" + rid).set_value("needs_review")
    at.text_area(key="note_" + rid).input("Please add your own example.")
    ok(at.button(key="save_" + rid).click().run())
    assert reviews.get_review(rid)["decision"] == "needs_review"
    ok(at.button(key="return_" + rid).click().run())
    ok(at.button(key="return_confirm").click().run())
    assert reviews.get_review(rid)["returned"] == "1"

    student = sign_in(new_app(), "alice", "studentpass")
    ok(student.switch_page("app_pages/student_assignment.py").run())
    assert "Your teacher's decision" in subheaders(student)
    shown = " ".join(m.value for m in student.markdown)
    assert "Please add your own example" in shown
    assert not student.metric                                  # no detector numbers
    assert "z-score" not in shown and "Not detected" not in shown


def test_report_export_writes_a_file(new_app, school):
    aid = school["assignment"]["assignment_id"]
    submissions.submit(aid, "alice", ESSAY)
    at = sign_in(new_app(), "prof", "teacherpass")
    ok(at.switch_page("app_pages/teacher_review.py").run())
    ok(at.download_button(key="export_report").click().run())
    written = list(paths.reports_dir().glob("assignment_{}_*.csv".format(aid)))
    assert len(written) == 1
    assert "alice" in written[0].read_text(encoding="utf-8")


def test_roster_import_and_export_on_the_classes_page(new_app, school):
    cid = school["class"]["class_id"]
    at = sign_in(new_app(), "prof", "teacherpass")
    ok(at.switch_page("app_pages/teacher_classes.py").run())
    ok(at.button(key="open_" + cid).click().run())
    ok(at.download_button(key="roster_export_" + cid).click().run())
    assert list(paths.reports_dir().glob("roster_{}_*.csv".format(cid)))


def test_assistant_switch_hides_the_card(new_app, school, tmp_path):
    aid = school["assignment"]["assignment_id"]
    conf = cfg.load_config(tmp_path / "wm.json")
    conf["classroom"]["assistant_enabled"] = False
    cfg.save_config(conf, tmp_path / "wm.json")
    at = sign_in(new_app(), "alice", "studentpass")
    ok(at.switch_page("app_pages/student_assignment.py").run())
    assert "Your answer" in subheaders(at)
    assert "Draft with the assistant" not in subheaders(at)
    assert aid


def test_assistant_draft_fills_the_editor_and_is_recorded(new_app, school):
    aid = school["assignment"]["assignment_id"]
    at = sign_in(new_app(), "alice", "studentpass")
    ok(at.switch_page("app_pages/student_assignment.py").run())
    assert "Draft with the assistant" in subheaders(at)
    ok(at.button(key="assistant_go").click().run())
    ok(at.button(key="draft_use").click().run())
    assert at.text_area(key="editor_" + aid).value.startswith("wm wm")
    ok(at.button(key="hand_in").click().run())
    sub = submissions.current_submission(aid, "alice")
    assert sub["source"] == "assistant"
    side = submissions.sidecar(sub)
    assert side["generation"]["mode"] == "watermarked"
    assert str(cfg.load_config()["watermark"]["hashing_key"]) not in json.dumps(side)


def test_sign_out_and_role_boundaries(new_app, school):
    at = sign_in(new_app(), "alice", "studentpass")
    with pytest.raises(ValueError):
        at.switch_page("app_pages/teacher_review.py")
    ok(at.button(key="sign_out").click().run())
    assert titles(at) == ["MarkText Classroom"]


def test_lab_pages_run_for_the_teacher(new_app, people):
    at = sign_in(new_app(), "prof", "teacherpass")
    ok(at.switch_page("app_pages/lab_generate.py").run())
    ok(at.button(key="gen_submit").click().run())
    assert at.session_state["gen_text"].startswith("wm")
    ok(at.download_button(key="gen_save").click().run())
    saved = list((lab.GENERATED_DIR / "watermarked").glob("*.json"))
    assert saved and "hashing_key" not in saved[0].read_text(encoding="utf-8")
    ok(at.switch_page("app_pages/lab_detect.py").run())
    at.text_area(key="detect_text").input(ESSAY)
    ok(at.button(key="detect_run").click().run())
    assert history.read_history()[0]["source"] == "manual"
    ok(at.switch_page("app_pages/lab_history.py").run())
    ok(at.button(key="clear_history").click().run())
    ok(at.button(key="clear_confirm").click().run())
    assert history.read_history() == []
    ok(at.switch_page("app_pages/lab_experiment.py").run())
    ok(at.switch_page("app_pages/about.py").run())
    ok(at.switch_page("app_pages/account.py").run())


def test_the_student_picker_follows_a_choice_made_elsewhere(new_app, school, people):
    """Regression: a row picked in the table (or a link from the home page)
    must also move the student picker, not only the panel below it."""
    classes.join_class(school["class"]["join_code"], "ben")
    aid = school["assignment"]["assignment_id"]
    submissions.submit(aid, "alice", ESSAY)
    submissions.submit(aid, "ben", ESSAY)
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    picker = "_pick_review_pick"
    assert at.selectbox(key=picker).value == "alice"
    at.session_state["review_pick"] = "ben"          # what the table's row click does
    ok(at.run())
    assert at.selectbox(key=picker).value == "ben"


def test_teacher_home_with_two_scored_versions_of_one_student(new_app, school):
    """Regression: a student with two scored versions crashed the home page
    (two buttons with the same key). Only the current version counts now."""
    eng, lock = FakeEngine(), threading.Lock()
    aid = school["assignment"]["assignment_id"]
    for text in ("wm " * 150, "wm " * 160):
        sub = submissions.submit(aid, "alice", text)
        detection.detect_submission(eng, lock, sub, "prof")
    at = sign_in(new_app(), "prof", "teacherpass")
    assert titles(at) == ["Hello, Prof. Reyes"]
    assert [m.label for m in at.metric] == ["Students", "Versions handed in", "To decide", "Flagged or likely"]
    figures = {m.label: m.value for m in at.metric}
    assert figures["Versions handed in"] == "2" and figures["Flagged or likely"] == "1"
    assert len([b for b in at.button if (b.key or "").startswith("home_flag_")]) == 1
    assert at.get("vega_lite_chart")                         # the scores chart is drawn


def test_student_home_figures(new_app, school):
    aid = school["assignment"]["assignment_id"]
    at = sign_in(new_app(), "alice", "studentpass")
    figures = {m.label: m.value for m in at.metric}
    assert figures == {"To hand in": "1", "Waiting for your teacher": "0", "Returned": "0", "Classes": "1"}
    submissions.submit(aid, "alice", ESSAY)
    ok(at.run())
    assert {m.label: m.value for m in at.metric}["Waiting for your teacher"] == "1"


# ------------------------------------------------------------ robustness
def test_two_students_with_the_same_name_can_both_be_opened(new_app, school, people):
    """Regression: a select box maps a picked label to the last option with
    that label, so the first of two students with one name could not be opened."""
    accounts.register("alice2", "studentpass", "student", "Alice Santos")
    classes.join_class(school["class"]["join_code"], "alice2")
    aid = school["assignment"]["assignment_id"]
    submissions.submit(aid, "alice", ESSAY)
    submissions.submit(aid, "alice2", ESSAY)
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    picker = at.selectbox(key="_pick_review_pick")
    assert sorted(picker.options) == ["Alice Santos · alice", "Alice Santos · alice2"]
    ok(picker.set_value("alice").run())
    assert at.session_state["review_pick"] == "alice"
    ok(at.selectbox(key="_pick_review_pick").set_value("alice2").run())
    assert at.session_state["review_pick"] == "alice2"


def test_a_weak_password_is_flagged_until_it_is_changed(new_app, people):
    # an account from before the password rules, with the old demo password
    store.update_json(paths.users_path(), accounts.EMPTY, lambda d: d["users"]["ben"].update(
        password=accounts.hash_password("marktext-demo")))
    at = sign_in(new_app(), "ben", "marktext-demo")
    assert any("easy to guess" in w.value for w in at.warning)
    follow(at, "account")
    at.text_input(key="account_old").input("marktext-demo")
    at.text_input(key="account_new").input("a-better-pass-9")
    at.text_input(key="account_repeat").input("a-better-pass-9")
    ok(at.button(key="account_change").click().run())
    assert not any("easy to guess" in w.value for w in at.warning)


def test_first_run_notes_reach_the_teacher_home(new_app):
    at = ok(new_app())
    at.text_input(key="setup_username").input("reyes")
    at.text_input(key="setup_name").input("Prof. Reyes")
    at.text_input(key="setup_password").input("teacherpass")
    at.text_input(key="setup_repeat").input("teacherpass")
    ok(at.button(key="setup_submit").click().run())
    assert any("new private hashing key" in w.value for w in at.warning)
    ok(at.button(key="home_dismiss_notes").click().run())
    assert not any("hashing key" in w.value for w in at.warning)


def test_a_decision_changed_after_return_needs_a_second_return(new_app, school):
    aid = school["assignment"]["assignment_id"]
    sub = submissions.submit(aid, "alice", ESSAY)
    rid = detection.detect_submission(FakeEngine(), threading.Lock(), sub, "prof")["review_id"]
    reviews.decide(rid, "accepted", "Well argued.", "prof")
    reviews.return_to_student(rid, by="prof")
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    at.segmented_control(key="decision_" + rid).set_value("flagged")
    at.text_area(key="note_" + rid).input("Please come and see me.")
    ok(at.button(key="save_" + rid).click().run())
    assert any("still sees" in c.value for c in at.caption)
    assert at.button(key="return_" + rid).label == "Return again"

    def student_sees():
        student = sign_in(new_app(), "alice", "studentpass")
        ok(student.switch_page("app_pages/student_assignment.py").run())
        return " ".join(m.value for m in student.markdown)
    before = student_sees()
    assert "Accepted" in before and "Well argued" in before and "come and see me" not in before
    ok(at.button(key="return_" + rid).click().run())
    ok(at.button(key="return_confirm").click().run())
    after = student_sees()
    assert "Flagged" in after and "come and see me" in after


def test_a_damaged_data_file_shows_a_message_not_a_traceback(new_app, school):
    paths.reviews_path().write_text("something,else\n1,2\n", encoding="utf-8")
    at = sign_in(new_app(), "prof", "teacherpass")
    assert any("reviews.csv" in e.value and "backups" in e.value for e in at.error)


def test_saving_a_decision_while_the_file_is_open_in_excel(new_app, school, excel_lock):
    aid = school["assignment"]["assignment_id"]
    sub = submissions.submit(aid, "alice", ESSAY)
    rid = detection.detect_submission(FakeEngine(), threading.Lock(), sub, "prof")["review_id"]
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    excel_lock(paths.reviews_path())
    at.segmented_control(key="decision_" + rid).set_value("accepted")
    ok(at.button(key="save_" + rid).click().run())
    assert any("Excel" in e.value for e in at.error)                # beside Save, not a passing toast
    assert reviews.get_review(rid)["decision"] == "pending"


def test_scoring_skips_a_missing_text_and_says_so(new_app, school, people):
    classes.join_class(school["class"]["join_code"], "ben")
    aid = school["assignment"]["assignment_id"]
    gone = submissions.submit(aid, "alice", ESSAY)
    submissions.submit(aid, "ben", ESSAY)
    paths.resolve(gone["text_path"]).unlink()
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    ok(at.button(key="score_all").click().run())
    assert any("missing" in w.value for w in at.warning)
    assert reviews.latest_review(gone["submission_id"]) is None
    assert submissions.current_submission(aid, "ben") and len(reviews.list_reviews()) == 1


def test_the_demo_class_uses_the_password_typed_in_the_dialog(new_app, data_dir):
    accounts.register("prof", "teacherpass", "teacher", "Prof. Reyes")
    at = sign_in(new_app(), "prof", "teacherpass")
    ok(at.button(key="home_demo").click().run())
    at.text_input(key="demo_password").input("river-lamp-41")
    ok(at.button(key="demo_build").click().run())
    assert accounts.authenticate("dan", "river-lamp-41")
    assert titles(at) == ["Review"]


def test_a_passage_that_decided_the_verdict_is_highlighted(new_app, school):
    aid = school["assignment"]["assignment_id"]
    text = "I wrote this part myself. " * 20 + "The assistant wrote this part. " * 30
    sub = submissions.submit(aid, "alice", text)
    start = text.index("The assistant")
    stats = {"num_tokens_scored": 300, "num_green_tokens": 176, "green_fraction": 176 / 300,
             "z_score": 3.12, "p_value": 9e-4, "label": "LIKELY MARKTEXT", "device": "cpu",
             "repeated": 0, "passage": {"z": 6.2, "p": 2.5e-9, "start": start, "end": len(text)}}
    reviews.record_detection(sub, stats, "run1", "fake/model", "0a1b2c3d", "prof")
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    shown = " ".join(m.value for m in at.markdown)
    assert r":orange-background[The assistant wrote this part\." in shown
    assert any("The verdict comes from this passage" in c.value for c in at.caption)
    assert any("The highlighted passage begins" in c.value and "The assistant wrote" in c.value
               for c in at.caption)                                 # in words, not colour alone


def test_a_display_name_is_shown_as_text_not_markdown(new_app, school):
    accounts.rename("alice", "![x](http://example.com/p.png) **Alice**")
    aid = school["assignment"]["assignment_id"]
    sub = submissions.submit(aid, "alice", "wm " * 150)
    detection.detect_submission(FakeEngine(), threading.Lock(), sub, "prof")
    at = sign_in(new_app(), "prof", "teacherpass")
    shown = " ".join(m.value for m in at.markdown)
    assert r"\!\[x\]\(http://example.com/p.png\) \*\*Alice\*\*" in shown
    assert "![x](" not in shown


def test_an_idle_tab_is_signed_out(new_app, school):
    at = sign_in(new_app(), "prof", "teacherpass")
    at.session_state["last_seen"] -= 31 * 60
    ok(at.run())
    assert titles(at) == ["MarkText Classroom"]
    assert any("without activity" in t.value for t in at.toast)


def test_the_review_page_warns_about_a_changed_text(new_app, school):
    aid = school["assignment"]["assignment_id"]
    sub = submissions.submit(aid, "alice", ESSAY)
    paths.resolve(sub["text_path"]).write_text(ESSAY + " Added later.", encoding="utf-8")
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    assert any("changed after it was handed in" in w.value for w in at.warning)


def test_an_unsaved_note_survives_looking_at_another_student(new_app, school, people):
    classes.join_class(school["class"]["join_code"], "ben")
    aid = school["assignment"]["assignment_id"]
    eng, lock = FakeEngine(), threading.Lock()
    rids = {}
    for who in ("alice", "ben"):
        sub = submissions.submit(aid, who, ESSAY)
        rids[who] = detection.detect_submission(eng, lock, sub, "prof")["review_id"]
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    ok(at.selectbox(key="_pick_review_pick").set_value("alice").run())
    ok(at.text_area(key="note_" + rids["alice"]).input("Half a thought").run())
    ok(at.selectbox(key="_pick_review_pick").set_value("ben").run())
    ok(at.selectbox(key="_pick_review_pick").set_value("alice").run())
    assert at.text_area(key="note_" + rids["alice"]).value == "Half a thought"
    assert any("Not saved yet" in c.value for c in at.caption)
    assert reviews.get_review(rids["alice"])["note"] == ""


def test_the_records_page_checks_files_and_restores_a_backup(new_app, school):
    cid = school["class"]["class_id"]
    submissions.submit(school["assignment"]["assignment_id"], "alice", ESSAY)
    classes.rename_class(cid, "Renamed class", "", by="prof")
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_records")
    assert titles(at) == ["Records"]
    assert at.dataframe                                        # the activity log is listed
    ok(at.button(key="check_run").click().run())
    assert any("All files agree" in s.value for s in at.success)     # said, not shown as zeros
    assert not at.metric
    copy = [c["backup"] for c in backups.listing() if c["file"] == "classes.json"][0]
    ok(at.selectbox(key="backup_pick").select(copy).run())
    ok(at.button(key="backup_restore").click().run())
    ok(at.button(key="restore_confirm").click().run())
    assert classes.get_class(cid)["name"] == "Intro to writing"
    assert any("Restored data/classes.json" in t.value for t in at.toast)


def test_scoring_does_not_load_the_model(new_app, school):
    submissions.submit(school["assignment"]["assignment_id"], "alice", ESSAY)
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    ok(at.button(key="score_all").click().run())
    assert len(reviews.list_reviews()) == 1
    assert not common.MODEL["loaded"]                           # the scorer needs no weights


# ------------------------------------------------------------ group 5: teacher tools
def _decided(school, who, decision="accepted", points=None):
    sub = submissions.submit(school["assignment"]["assignment_id"], who, ESSAY)
    rid = detection.detect_submission(FakeEngine(), threading.Lock(), sub, "prof")["review_id"]
    reviews.decide(rid, decision, "Thanks, " + who, "prof", points=points)
    return rid


def test_editing_an_assignment_and_renaming_a_class(new_app, school):
    cid, aid = school["class"]["class_id"], school["assignment"]["assignment_id"]
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_classes")
    ok(at.button(key="open_" + cid).click().run())
    ok(at.button(key="edit_" + aid).click().run())
    at.text_input(key="edit_task_title").input("Why we keep diaries")
    at.number_input(key="edit_task_points").set_value(10)
    ok(at.button(key="edit_task_save").click().run())
    task = assignments.get_assignment(aid)
    assert (task["title"], task["points"]) == ("Why we keep diaries", "10")
    ok(at.button(key="class_rename").click().run())
    at.text_input(key="rename_class_name").input("Writing 101")
    ok(at.button(key="rename_save").click().run())
    assert classes.get_class(cid)["name"] == "Writing 101"


def test_return_all_and_points_reach_the_student(new_app, school, people):
    classes.join_class(school["class"]["join_code"], "ben")
    assignments.update_assignment(school["assignment"]["assignment_id"], by="prof", points=10)
    rids = [_decided(school, "alice", points=8.5), _decided(school, "ben", "needs_review", points=6)]
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    assert at.button(key="return_all").label == "Return all decided (2)"
    ok(at.button(key="return_all").click().run())
    ok(at.button(key="return_all_confirm").click().run())
    assert all(reviews.get_review(r)["returned"] == "1" for r in rids)
    student = sign_in(new_app(), "alice", "studentpass")
    ok(student.switch_page("app_pages/student_assignment.py").run())
    assert "8.5 / 10 points" in " ".join(m.value for m in student.markdown)


def test_points_are_entered_with_the_decision(new_app, school):
    assignments.update_assignment(school["assignment"]["assignment_id"], by="prof", points=20)
    sub = submissions.submit(school["assignment"]["assignment_id"], "alice", ESSAY)
    rid = detection.detect_submission(FakeEngine(), threading.Lock(), sub, "prof")["review_id"]
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    at.segmented_control(key="decision_" + rid).set_value("accepted")
    at.number_input(key="points_" + rid).set_value(17.5)
    ok(at.button(key="save_" + rid).click().run())
    assert reviews.get_review(rid)["points"] == "17.5"


def test_a_teacher_resets_a_password_and_the_student_must_change_it(new_app, school):
    cid = school["class"]["class_id"]
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_classes")
    ok(at.button(key="open_" + cid).click().run())
    ok(at.selectbox(key="remove_pick_" + cid).select("alice").run())
    ok(at.button(key="reset_" + cid).click().run())
    ok(at.button(key="reset_confirm").click().run())
    temporary = at.code[-1].value
    assert accounts.authenticate("alice", temporary)
    ok(at.button(key="reset_done").click().run())
    student = sign_in(new_app(), "alice", temporary)
    assert any("temporary password" in w.value for w in student.warning)


def test_the_teacher_sees_what_changed_in_an_assistant_draft(new_app, school):
    aid = school["assignment"]["assignment_id"]
    at = sign_in(new_app(), "alice", "studentpass")
    follow(at, "student_assignment")
    ok(at.button(key="assistant_go").click().run())
    ok(at.button(key="draft_use").click().run())
    draft = at.text_area(key="editor_" + aid).value
    at.text_area(key="editor_" + aid).input("My own opening sentence. " + draft)
    ok(at.button(key="hand_in").click().run())
    side = submissions.sidecar(submissions.current_submission(aid, "alice"))
    assert side["generation"]["text"] == draft
    teacher = sign_in(new_app(), "prof", "teacherpass")
    follow(teacher, "teacher_review")
    assert any("of the assistant's draft is still in this version" in c.value for c in teacher.caption)
    assert ":green-background[**My own opening sentence.**]" in " ".join(m.value for m in teacher.markdown)


def test_one_students_work_across_the_class(new_app, school):
    cid = school["class"]["class_id"]
    _decided(school, "alice")
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_classes")
    ok(at.button(key="open_" + cid).click().run())
    ok(at.selectbox(key="history_pick_" + cid).select("alice").run())
    table = next(d.value for d in at.dataframe if {"Assignment", "Version"} <= set(d.value.columns))
    assert list(table["Assignment"]) == ["Why people keep diaries"] and list(table["Decision"]) == ["Accepted"]


def test_after_a_key_rotation_a_draft_is_scored_with_its_own_key(new_app, school, tmp_path):
    aid = school["assignment"]["assignment_id"]
    at = sign_in(new_app(), "alice", "studentpass")
    follow(at, "student_assignment")
    ok(at.button(key="assistant_go").click().run())
    ok(at.button(key="draft_use").click().run())
    ok(at.button(key="hand_in").click().run())
    old, new = cfg.rotate_key(tmp_path / "wm.json")
    teacher = sign_in(new_app(), "prof", "teacherpass")
    follow(teacher, "teacher_review")
    ok(teacher.button(key="score_all").click().run())
    review = reviews.latest_review(submissions.current_submission(aid, "alice")["submission_id"])
    assert review["key_id"] == old and review["label"] == "LIKELY MARKTEXT"
    assert any("the key this draft was made with" in c.value for c in teacher.caption)


def test_a_score_from_the_old_counting_is_marked_and_scored_again(new_app, school):
    aid = school["assignment"]["assignment_id"]
    sub = submissions.submit(aid, "alice", ESSAY)
    old_stats = {"num_tokens_scored": 196, "num_green_tokens": 127, "green_fraction": 127 / 196,
                 "z_score": 4.14, "p_value": 1.7e-5, "label": "LIKELY MARKTEXT", "device": "cpu"}
    old = reviews.record_detection(sub, old_stats, "run1", "fake/model", "0a1b2c3d", "prof")
    reviews.decide(old["review_id"], "flagged", "Looks drafted.", "prof")

    at = sign_in(new_app(), "prof", "teacherpass")                  # Home
    assert any("made before repeated words counted once" in w.value for w in at.warning)
    assert any("old count" in c.value for c in at.caption)          # on the recent flag
    follow(at, "teacher_review")
    assert at.dataframe[0].value["Detector"].tolist() == ["Likely MarkText (old count)"]
    assert any("earlier counting" in w.value for w in at.warning)
    ok(at.button(key="score_old").click().run())                    # "Score again (1)"
    new = reviews.latest_review(sub["submission_id"])
    assert new["label"] == "NOT DETECTED" and not reviews.counted_every_repeat(new)
    assert (new["decision"], new["note"]) == ("flagged", "Looks drafted.")
    assert at.dataframe[0].value["Detector"].tolist() == ["Not detected"]
    assert not [b for b in at.button if b.key == "score_old"]       # nothing old is left
    assert any("changed the verdict from Likely MarkText to Not detected" in c.value for c in at.caption)
    home = sign_in(new_app(), "prof", "teacherpass")
    assert not any("made before repeated words counted once" in w.value for w in home.warning)


def test_an_answer_survives_an_idle_sign_out_and_the_hand_in_still_says_so(new_app, school):
    aid = school["assignment"]["assignment_id"]
    at = sign_in(new_app(), "alice", "studentpass")
    follow(at, "student_assignment")
    ok(at.text_area(key="editor_" + aid).input("Half an essay about diaries.").run())
    assert drafts.load("alice", aid)["text"] == "Half an essay about diaries."
    at.session_state["last_seen"] -= 31 * 60                       # half an hour of typing
    ok(at.text_area(key="editor_" + aid).input("Half an essay about diaries, and more.").run())
    assert at.session_state["user"] is None                         # signed out by that click,
    assert drafts.load("alice", aid)["text"].endswith("and more.")  # after the text was kept

    at = sign_in(new_app(), "alice", "studentpass")
    follow(at, "student_assignment")
    assert at.text_area(key="editor_" + aid).value.endswith("and more.")
    assert any("Restored the answer" in c.value for c in at.caption)
    at.session_state["last_seen"] -= 31 * 60
    ok(at.button(key="hand_in").click().run())                      # handed in after another quiet spell
    assert submissions.current_submission(aid, "alice")["version"] == "1"
    assert drafts.load("alice", aid) is None
    toasts = [t.value for t in at.toast]
    assert "Version 1 handed in." in toasts and any("without activity" in t for t in toasts)


def test_taking_a_draft_asks_before_it_replaces_the_students_text(new_app, school):
    aid = school["assignment"]["assignment_id"]
    at = sign_in(new_app(), "alice", "studentpass")
    follow(at, "student_assignment")
    ok(at.text_area(key="editor_" + aid).input("My own opening paragraph.").run())
    ok(at.button(key="assistant_go").click().run())
    draft = at.session_state["assistant_draft"]["text"]
    ok(at.button(key="draft_use").click().run())
    assert at.text_area(key="editor_" + aid).value == "My own opening paragraph."     # asked, not replaced
    ok(at.button(key="replace_cancel").click().run())
    assert at.text_area(key="editor_" + aid).value == "My own opening paragraph."
    ok(at.button(key="draft_use").click().run())
    ok(at.button(key="replace_below").click().run())
    assert at.text_area(key="editor_" + aid).value == "My own opening paragraph.\n\n" + draft
    assert drafts.load("alice", aid)["source"] == "assistant"
    ok(at.text_area(key="editor_" + aid).input("Something else entirely.").run())
    ok(at.button(key="assistant_go").click().run())
    ok(at.button(key="draft_use").click().run())
    ok(at.button(key="replace_confirm").click().run())
    assert at.text_area(key="editor_" + aid).value == at.session_state["draft_" + aid] == draft


def test_a_draft_still_arrives_when_the_page_reruns_while_the_model_writes(new_app, school, monkeypatch):
    """A click starts a new run at once and the old run stops at its next
    touch of the session state, so the draft is written in a thread of its
    own (common.start_job) and any later run picks it up."""
    release, real = threading.Event(), assistant.draft

    def slow_draft(*args, **kwargs):
        release.wait(10)                                           # the model, taking its minute
        return real(*args, **kwargs)
    monkeypatch.setattr(assistant, "draft", slow_draft)
    at = sign_in(new_app(), "alice", "studentpass")
    follow(at, "student_assignment")
    ok(at.button(key="assistant_go").click().run())
    assert any("so far" in p.proto.text for p in at.get("progress"))
    assert not [b for b in at.button if b.key == "draft_use"]
    ok(at.button(key="assistant_go").click().run())                # clicked again while it writes
    assert any("still writing" in i.value for i in at.info)
    follow(at, "student_home")                                     # the student wanders off
    release.set()
    for _ in range(100):
        if at.session_state["assistant_job"]["done"]:
            break
        time.sleep(0.05)
    follow(at, "student_assignment")
    assert [b for b in at.button if b.key == "draft_use"]           # the draft is there
    assert "assistant_job" not in at.session_state


def test_returning_unsaved_changes_saves_them_first(new_app, school):
    aid = school["assignment"]["assignment_id"]
    sub = submissions.submit(aid, "alice", ESSAY)
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    ok(at.button(key="score_all").click().run())
    rid = reviews.latest_review(sub["submission_id"])["review_id"]
    at.segmented_control(key="decision_" + rid).set_value("needs_review")
    at.text_area(key="note_" + rid).input("Add an example from your own life.")
    ok(at.run())                                                     # changed, not saved
    assert [b.label for b in at.button if b.key == "return_" + rid] == ["Save and return"]
    ok(at.button(key="return_" + rid).click().run())
    assert any("Add an example from your own life" in m.value for m in at.markdown)   # what is sent
    assert any("Not saved yet: returning saves it first" in c.value for c in at.caption)
    ok(at.button(key="return_confirm").click().run())
    saved = reviews.get_review(rid)
    assert (saved["decision"], saved["note"], saved["returned"]) == \
        ("needs_review", "Add an example from your own life.", "1")
    assert reviews.shown_to_student(saved)["note"] == "Add an example from your own life."


def test_return_all_warns_about_changes_not_saved(new_app, school):
    aid = school["assignment"]["assignment_id"]
    classes.join_class(school["class"]["join_code"], "ben")
    subs = {who: submissions.submit(aid, who, ESSAY) for who in ("alice", "ben")}
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    ok(at.button(key="score_all").click().run())
    rids = {who: reviews.latest_review(s["submission_id"])["review_id"] for who, s in subs.items()}
    for who in rids:
        reviews.decide(rids[who], "accepted", "Good.", "prof")
    at.session_state["review_pick"] = "ben"
    ok(at.run())
    at.text_area(key="note_" + rids["ben"]).input("Good, but name your source.")
    ok(at.run())
    ok(at.button(key="return_all").click().run())
    assert any("Not saved yet for" in w.value and "Ben" in w.value for w in at.warning)


def test_feedback_stays_in_view_while_the_student_revises(new_app, school):
    aid = school["assignment"]["assignment_id"]
    sub = submissions.submit(aid, "alice", ESSAY)
    rev = reviews.record_detection(sub, {"label": "NOT DETECTED", "z_score": -0.5, "repeated": 0},
                                   "run1", "fake/model", "0a1b2c3d", "prof")
    reviews.decide(rev["review_id"], "needs_review", "Add an example.", "prof")
    reviews.return_to_student(rev["review_id"], by="prof")
    at = sign_in(new_app(), "alice", "studentpass")
    follow(at, "student_assignment")
    ok(at.button(key="start_from").click().run())                  # empty editor: no question asked
    assert at.text_area(key="editor_" + aid).value.strip() == ESSAY.strip()
    at.text_area(key="editor_" + aid).input(ESSAY + " My grandmother kept one too.")
    ok(at.button(key="hand_in").click().run())
    assert "Your teacher's decision" in subheaders(at)              # still there after version 2
    captions = " ".join(c.value for c in at.caption)
    assert "On version 1" in captions and "You handed in version 2 after this" in captions
    assert any("Add an example" in m.value for m in at.markdown)
    feedback =reports.returned_feedback(aid, "alice")
    assert (feedback["version"], feedback["note"]) == (1, "Add an example.")
    follow(at, "student_home")
    assert any("on version 1; version 2 is with your teacher" in c.value for c in at.caption)


def test_students_get_an_about_page_of_their_own_and_lengths_in_words(new_app, school):
    aid = school["assignment"]["assignment_id"]
    student = sign_in(new_app(), "alice", "studentpass")
    follow(student, "about")
    shown = " ".join(m.value for m in student.markdown)
    assert "hidden watermark" in shown and "z-score" not in shown and "Installation" not in shown
    follow(student, "student_assignment")
    length = student.select_slider(key="assistant_length_" + aid)
    assert length.label == "Length" and not length.help and "about 190 words" in length.options
    teacher = sign_in(new_app(), "prof", "teacherpass")
    follow(teacher, "about")
    assert any("Installation" in m.value for m in teacher.markdown)    # the README, for teachers


def test_errors_stay_beside_the_control_they_are_about(new_app, school):
    at = sign_in(new_app(), "alice", "studentpass")
    follow(at, "student_assignment")
    ok(at.button(key="hand_in").click().run())                      # nothing written yet
    assert any("The submission is empty" in e.value for e in at.error)
    assert not at.toast
    follow(at, "student_home")
    assert not at.text_input(key="join_code").help                  # no tooltip Tab stop
    at.text_input(key="join_code").input("ZZZ-999")
    ok(at.button(key="join_submit").click().run())
    assert any("No class uses the code" in e.value for e in at.error)


def test_a_flag_or_a_revision_needs_a_note_and_the_student_is_told_what_to_do(new_app, school):
    aid = school["assignment"]["assignment_id"]
    sub = submissions.submit(aid, "alice", ESSAY)
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    ok(at.button(key="score_all").click().run())
    rid = reviews.latest_review(sub["submission_id"])["review_id"]
    at.segmented_control(key="decision_" + rid).set_value("needs_review")
    ok(at.button(key="save_" + rid).click().run())
    assert any("Add a note" in e.value for e in at.error)
    assert reviews.get_review(rid)["decision"] == "pending"
    at.text_area(key="note_" + rid).input("Add one example from your own life.")
    ok(at.button(key="save_" + rid).click().run())
    ok(at.button(key="return_" + rid).click().run())
    ok(at.button(key="return_confirm").click().run())
    student = sign_in(new_app(), "alice", "studentpass")
    follow(student, "student_assignment")
    assert any("would like you to revise this" in m.value for m in student.markdown)


def test_next_waiting_student_and_adding_a_removed_student_back(new_app, school):
    aid, cid = school["assignment"]["assignment_id"], school["class"]["class_id"]
    classes.join_class(school["class"]["join_code"], "ben")
    for who in ("alice", "ben"):
        submissions.submit(aid, who, ESSAY)
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")
    ok(at.button(key="score_all").click().run())
    assert at.session_state["review_pick"] == "alice"
    ok(at.button(key="next_waiting").click().run())
    assert at.session_state["review_pick"] == "ben"
    ok(at.button(key="next_waiting").click().run())                 # round to the start
    assert at.session_state["review_pick"] == "alice"
    classes.remove_student(cid, "ben", by="prof")
    at.session_state["open_class_id"] = cid
    follow(at, "teacher_classes")
    assert at.selectbox(key="remove_pick_" + cid).label == "Student"
    ok(at.button(key="add_back_{}_ben".format(cid)).click().run())
    assert classes.is_member(cid, "ben")


def test_the_home_page_fits_a_phone_and_keeps_the_password_warning(new_app, school):
    cid = school["class"]["class_id"]
    at = sign_in(new_app(), "prof", "teacherpass")
    at.session_state["weak_password"] = "Your password is easy to guess."
    ok(at.run())
    assert any("easy to guess" in w.value for w in at.warning)      # on Home, below the title
    assert not at.dataframe                                         # the classes are a list
    ok(at.button(key="home_class_" + cid).click().run())
    assert at.session_state["open_class_id"] == cid
    follow(at, "teacher_classes")
    assert titles(at) == ["Intro to writing"]
    assert not any("easy to guess" in w.value for w in at.warning)  # not above every page


def test_after_a_sign_out_the_next_person_starts_on_their_own_home(new_app, school):
    at = sign_in(new_app(), "alice", "studentpass")
    follow(at, "about")
    ok(at.button(key="sign_out").click().run())
    assert any("Forgot your password" in c.value for c in at.caption)
    at = sign_in(at, "prof", "teacherpass")
    assert titles(at) == ["Hello, Prof. Reyes"]                     # not Alice's last page


def test_the_account_page_shows_the_previous_sign_in_and_keeps_a_mistyped_change(new_app, people):
    sign_in(new_app(), "alice", "studentpass")                     # an earlier sign-in
    at = sign_in(new_app(), "alice", "studentpass")
    follow(at, "account")
    profile = str(at.table[0].value)
    assert "Previous sign-in" in profile and "None before this one" not in profile
    at.text_input(key="account_old").input("studentpass")
    at.text_input(key="account_new").input("brand-new-pass-7")
    at.text_input(key="account_repeat").input("brand-new-pass-8")  # a typo
    ok(at.button(key="account_change").click().run())
    assert any("do not match" in e.value for e in at.error)
    assert at.text_input(key="account_new").value == "brand-new-pass-7"     # nothing to type again
    at.text_input(key="account_repeat").input("brand-new-pass-7")
    ok(at.button(key="account_change").click().run())
    assert at.text_input(key="account_new").value == ""                     # emptied once it worked
    assert accounts.authenticate("alice", "brand-new-pass-7")


def test_the_lab_writes_verdicts_like_the_other_pages_and_its_command_matches(new_app, people):
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "lab_detect")
    at.text_area(key="detect_text").input(ESSAY)
    ok(at.button(key="detect_run").click().run())
    follow(at, "lab_history")
    assert at.multiselect(key="hist_results").options == ["Not detected"]
    follow(at, "lab_experiment")
    assert any("--prompts 3 " in c.value for c in at.code)          # not all 100 prompts


def test_empty_pages_link_to_where_they_fill_and_home_knows_archived_classes(new_app, people):
    cls = classes.create_class("Intro", "prof")
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "teacher_review")                                    # a class without assignments
    links = [link.proto.label for link in at.get("page_link")]
    assert "Open the class" in links and at.session_state["open_class_id"] == cls["class_id"]
    classes.set_archived(cls["class_id"], True, by="prof")
    follow(at, "teacher_home")
    assert any("All your classes are archived" in m.value for m in at.markdown)


def test_long_home_lists_show_five_and_the_rest_under_more(new_app, school):
    cid = school["class"]["class_id"]
    for n in range(6):                                             # seven open assignments in all
        assignments.create_assignment(cid, "Essay {}".format(n), "", "", "prof")
    at = sign_in(new_app(), "alice", "studentpass")
    assert "2 more" in [e.label for e in at.expander]


def test_the_detect_result_goes_when_the_text_changes(new_app, people):
    at = sign_in(new_app(), "prof", "teacherpass")
    follow(at, "lab_detect")
    at.text_area(key="detect_text").input(ESSAY)
    ok(at.button(key="detect_run").click().run())
    assert at.session_state["detect_stats"] is not None
    ok(at.text_area(key="detect_text").input(ESSAY + " One more sentence.").run())
    assert at.session_state["detect_stats"] is None                 # no old score on a new text
    assert any("Nothing scored yet" in c.value for c in at.caption)


def tab_goes_field_to_field(at):
    """No help tooltip on any text box (each one is a Tab stop), and the
    script that takes the show-password buttons out of the Tab order."""
    assert [t.label for t in at.text_input if t.help] == []
    assert any(h.proto.unsafe_allow_javascript and 'aria-label$="password"' in h.proto.body
               for h in at.get("html"))


def test_the_sign_in_page_has_the_name_beside_the_forms(new_app, people):
    at = ok(new_app())
    brand, forms = at.columns[1], at.columns[2]
    assert [t.value for t in brand.title] == ["MarkText Classroom"]
    assert [t.key for t in forms.text_input] == ["login_username", "login_password"]
    tab_goes_field_to_field(at)
    ok(at.segmented_control(key="login_mode").set_value("Register").run())
    forms = at.columns[2]
    assert [t.key for t in forms.text_input] == ["register_username", "register_name", "register_password",
                                                 "register_repeat", "register_code"]
    hints = [c.value for c in forms.caption]
    assert accounts.USERNAME_HINT in hints and accounts.PASSWORD_HINT in hints
    tab_goes_field_to_field(at)


def test_the_first_run_setup_has_the_name_beside_the_form(new_app):
    at = ok(new_app())
    assert [t.value for t in at.columns[1].title] == ["MarkText Classroom"]
    assert [t.key for t in at.columns[2].text_input] == ["setup_username", "setup_name", "setup_password",
                                                         "setup_repeat"]
    tab_goes_field_to_field(at)


def test_the_password_change_has_no_tooltips(new_app, people):
    at = sign_in(new_app(), "alice", "studentpass")
    follow(at, "account")
    assert accounts.PASSWORD_HINT in [c.value for c in at.caption]
    tab_goes_field_to_field(at)
