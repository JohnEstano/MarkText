"""About MarkText. Teachers: the README, the configuration (key hidden) and
an inventory of every file the classroom keeps. Students: a short page of
their own; the README explains how detection works and where it is weak,
which is the teacher's business, not something to coach students in."""

import pandas as pd
import streamlit as st

import config as cfg
import history
from classroom import paths
from ui import common, lab

user = common.current_user()
st.title("About", anchor=False)

FOR_STUDENTS = """
MarkText Classroom is where you hand in written work for your classes. Your teacher posts
assignments; you write your answer here or upload a .txt file, and hand it in. You can hand in
new versions while the assignment is open, and your teacher returns your work with a decision
and a note.

**The writing assistant.** The Assignment page can write a first draft for you. Its drafts
carry a hidden watermark, so your teacher can tell when text came from the assistant. Ask your
teacher whether you may use it for an assignment, and say so in your note when you do.

**What is kept.** Your account (your password only as a one-way hash), every version you hand
in, and the answer you are still writing, so that signing out does not lose it. Your teacher
sees what you hand in, not the answer you are still writing.
"""

if user["role"] == "teacher":
    with st.expander("Files MarkText keeps", icon=":material/folder_open:"):
        def rows(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return max(sum(1 for _ in f) - 1, 0)
            except OSError:
                return None
        files = [
            ("data/users.json", paths.users_path(), "accounts (passwords hashed)"),
            ("data/classes.json", paths.classes_path(), "classes and class codes"),
            ("data/rosters.csv", paths.rosters_path(), "who is in which class"),
            ("data/assignments.csv", paths.assignments_path(), "assignments"),
            ("data/submissions.csv", paths.submissions_path(), "index of every submitted version"),
            ("data/reviews.csv", paths.reviews_path(), "scores and the teacher's decisions"),
            ("logs/detection_history.csv", history.HISTORY_PATH, "every detection, lab and classroom"),
        ]
        table = [{"file": name, "holds": what,
                  "size (KB)": round(path.stat().st_size / 1024, 1) if path.exists() else 0.0,
                  "lines": rows(path) if path.suffix == ".csv" else None}
                 for name, path, what in files]
        texts = len(list(paths.submissions_dir().rglob("*.txt"))) if paths.submissions_dir().exists() else 0
        backups = len(list(paths.backups_dir().glob("*"))) if paths.backups_dir().exists() else 0
        reports = len(list(paths.reports_dir().glob("*.csv"))) if paths.reports_dir().exists() else 0
        unsent = len(list(paths.drafts_dir().rglob("*.json"))) if paths.drafts_dir().exists() else 0
        st.dataframe(pd.DataFrame(table), hide_index=True,
                     column_config={"lines": st.column_config.NumberColumn("data rows")})
        st.caption("Plus {} submission text files (each with a JSON sidecar), {} answers students "
                   "have not handed in yet in data/drafts, {} reports in data/reports and {} backup "
                   "copies in data/backups, written before every rewrite.".format(
                       texts, unsent, reports, backups))
    with st.expander("Configuration (config/watermark_config.json, key hidden)",
                     icon=":material/settings:"):
        st.json(cfg.redacted(cfg.load_config()))
    st.markdown(lab.read_readme())
else:
    st.markdown(FOR_STUDENTS)
