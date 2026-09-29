"""The classroom app, driven headlessly with Streamlit's AppTest and a fake
engine: sign-in, the teacher's and the student's flows, the dialogs, the
exports and the assistant switch. No browser, no model."""

import json
import pathlib
import threading

import pytest
from fakes import FakeEngine
from streamlit.testing.v1 import AppTest

import config as cfg
import history
from classroom import accounts, assignments, classes, detection, paths, reviews, store, submissions
from ui import common, lab

ROOT = pathlib.Path(__file__).resolve().parent.parent
ESSAY = "People keep diaries to remember the small things. " * 25


@pytest.fixture
def new_app(data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "wm.json")
    monkeypatch.setattr(common, "make_engine", lambda config: FakeEngine(config))
    monkeypatch.setattr(lab, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(lab, "EXPORT_DIR", tmp_path / "logs" / "exports")
    common.get_engine.clear()
    common.MODEL.update(loaded=False)

    def make():
        return AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    yield make
    common.get_engine.clear()


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
    assert [m.label for m in at.metric] == ["Students", "Handed in", "To decide", "Flagged or likely"]
    figures = {m.label: m.value for m in at.metric}
    assert figures["Handed in"] == "2" and figures["Flagged or likely"] == "1"
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
    assert any("Excel" in t.value for t in at.toast)
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
