"""The signed-in person's account: name and password (data/users.json)."""

import streamlit as st

from classroom import accounts
from ui import common

state = st.session_state
user = common.current_user()
record = accounts.get_user(user["username"]) or user

st.title("Account", anchor=False)
left, right = st.columns(2, gap="large")

with left:
    with st.container(border=True):
        st.subheader("Profile", anchor=False)
        st.table({":material/badge: Username": record["username"],
                  ":material/school: Role": record["role"].capitalize(),
                  ":material/event: Member since": common.when(record["created_at"]),
                  ":material/login: Last sign-in": common.when(record["last_login"]) or "Now"},
                 border="horizontal")
        with st.form("rename", border=False):
            name = st.text_input("Display name", value=record["display_name"], key="account_name")
            if st.form_submit_button("Save name", key="account_rename"):
                try:
                    state["user"] = accounts.rename(record["username"], name)
                except ValueError as exc:
                    st.error(str(exc), icon=":material/error:")
                else:
                    common.flash("Name saved.")
                    st.rerun()

with right:
    with st.container(border=True):
        st.subheader("Password", anchor=False)
        with st.form("password", border=False, clear_on_submit=True):
            old = st.text_input("Current password", type="password", key="account_old")
            new = st.text_input("New password", type="password", key="account_new",
                                help="At least {} characters.".format(accounts.MIN_PASSWORD))
            repeat = st.text_input("Repeat the new password", type="password", key="account_repeat")
            if st.form_submit_button("Change password", key="account_change"):
                try:
                    if new != repeat:
                        raise ValueError("The two new passwords do not match.")
                    accounts.change_password(record["username"], old, new)
                except ValueError as exc:
                    st.error(str(exc), icon=":material/error:")
                else:
                    common.flash("Password changed.", ":material/lock_reset:")
                    st.rerun()
    if record["role"] == "teacher":
        with st.container(border=True):
            st.subheader("More teachers", anchor=False)
            st.caption("Teacher accounts are created on the server, never from the sign-in page:")
            st.code("python -m classroom.cli create-teacher <username> --display-name \"<name>\"",
                    language="bash")
