"""MarkText Classroom: teachers, students, classes, assignments, submissions
and the teacher's review of each submission.

Pure Python (no Streamlit, no torch), so every rule here is unit-tested and
the same functions serve the web pages, the command line and the demo seed.
All files live under data/ (classroom/paths.py); every rewrite goes through
classroom/store.py (backup first, then an atomic replace).
"""
