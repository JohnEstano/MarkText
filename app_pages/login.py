"""Sign in, register as a student, or (first run only) create the teacher.

Reads and writes data/users.json through classroom.accounts: passwords are
hashed there, never stored. A student who registers with a class code is
enrolled right away; an invitation from an imported roster is accepted too.
"""

import streamlit as st

from classroom import accounts, classes
from ui import common

state = st.session_state


def _enter(user, message):
    common.sign_in(user)
    common.flash(message, ":material/waving_hand:")
    st.rerun()


_, middle, _ = st.columns([1, 1.25, 1])
with middle:
    st.space("large")
    st.image("static/mark.svg", width=52)
    st.title("MarkText Classroom", anchor=False)
    st.caption("A class space for written work. Teachers can tell which submissions were "
               "drafted with MarkText's writing assistant.")

    if not accounts.has_teacher():
        with st.container(border=True):
            st.subheader("Set up the classroom", anchor=False)
            st.caption("Create the teacher account. Students register themselves and join your "
                       "classes with a code. More teachers can be added later from the command line.")
            with st.form("setup", border=False):
                username = st.text_input("Username", placeholder="reyes", key="setup_username")
                name = st.text_input("Display name", placeholder="Prof. Reyes", key="setup_name")
                password = st.text_input("Password", type="password", key="setup_password",
                                         help="At least {} characters.".format(accounts.MIN_PASSWORD))
                repeat = st.text_input("Repeat the password", type="password", key="setup_repeat")
                create = st.form_submit_button("Create teacher account", type="primary",
                                               width="stretch", key="setup_submit")
            if create:
                try:
                    if password != repeat:
                        raise ValueError("The two passwords do not match.")
                    if accounts.has_teacher():          # someone was quicker in another tab
                        raise ValueError("A teacher account already exists. Sign in instead.")
                    user = accounts.register(username, password, "teacher", name)
                except ValueError as exc:
                    st.error(str(exc), icon=":material/error:")
                else:
                    _enter(user, "Welcome, {}. Your classroom is ready.".format(user["display_name"]))
        st.stop()

    mode = st.segmented_control("Account", ["Sign in", "Register"], default="Sign in",
                                key="login_mode", label_visibility="collapsed", width="stretch")
    with st.container(border=True):
        if mode != "Register":
            with st.form("sign_in", border=False):
                username = st.text_input("Username", key="login_username")
                password = st.text_input("Password", type="password", key="login_password")
                submitted = st.form_submit_button("Sign in", type="primary", width="stretch",
                                                  key="login_submit")
            if submitted:
                user = accounts.authenticate(username, password)
                if user is None:
                    st.error("That username and password do not match.", icon=":material/error:")
                else:
                    _enter(user, "Signed in as {}.".format(user["display_name"]))
        else:
            st.caption("Students register here. Teachers get their account from the classroom's "
                       "administrator.")
            with st.form("register", border=False):
                username = st.text_input("Username", placeholder="alice.santos",
                                         key="register_username",
                                         help="3 to 24 characters: lowercase letters, digits, dots, "
                                              "dashes or underscores.")
                name = st.text_input("Your name", placeholder="Alice Santos", key="register_name")
                password = st.text_input("Password", type="password", key="register_password",
                                         help="At least {} characters.".format(accounts.MIN_PASSWORD))
                repeat = st.text_input("Repeat the password", type="password", key="register_repeat")
                code = st.text_input("Class code (optional)", placeholder="ABC-234",
                                     key="register_code")
                submitted = st.form_submit_button("Create account", type="primary", width="stretch",
                                                  key="register_submit")
            if submitted:
                try:
                    if password != repeat:
                        raise ValueError("The two passwords do not match.")
                    user = accounts.register(username, password, "student", name)
                except ValueError as exc:
                    st.error(str(exc), icon=":material/error:")
                else:
                    joined = classes.claim_invites(user["username"])
                    message = "Account created."
                    if code.strip():
                        try:
                            record = classes.join_class(code, user["username"])
                            message = "Account created. You joined {}.".format(record["name"])
                        except ValueError as exc:
                            message = "Account created, but the class code did not work: {}".format(exc)
                    elif joined:
                        message = "Account created. Your teacher had already added you to a class."
                    _enter(user, message)
