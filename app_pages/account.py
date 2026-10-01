"""The signed-in person's account: name and password (data/users.json)."""

import streamlit as st

from classroom import accounts
from ui import common

state = st.session_state
user = common.current_user()
record = accounts.get_user(user["username"]) or user
PASSWORD_FIELDS = ("account_old", "account_new", "account_repeat")
if state.pop("password_changed", False):
    # emptied only after a change that worked: a typo must not cost all three fields
    for key in PASSWORD_FIELDS:
        state.pop(key, None)

st.title("Account", anchor=False)
left, right = st.columns(2, gap="large")

with left:
    with st.container(border=True):
        st.subheader("Profile", anchor=False)
        st.table({":material/badge: Username": record["username"],
                  ":material/school: Role": record["role"].capitalize(),
                  ":material/event: Member since": common.when(record["created_at"]),
                  # last_login is this sign-in; the one before was kept when signing in
                  ":material/login: Previous sign-in": common.when(user.get("previous_login")) or "None before this one"},
                 border="horizontal")
        with st.form("rename", border=False):
            name = st.text_input("Display name", value=record["display_name"], key="account_name")
            if st.form_submit_button("Save name", key="account_rename"):
                try:
                    state["user"] = dict(accounts.rename(record["username"], name),
                                         previous_login=user.get("previous_login", ""))
                except ValueError as exc:
                    st.error(common.md(str(exc)), icon=":material/error:")
                else:
                    common.flash("Name saved.")
                    st.rerun()

with right:
    with st.container(border=True):
        st.subheader("Password", anchor=False)
        with st.form("password", border=False):
            old = st.text_input("Current password", type="password", key="account_old")
            new = st.text_input("New password", type="password", key="account_new")
            st.caption(accounts.PASSWORD_HINT)
            repeat = st.text_input("Repeat the new password", type="password", key="account_repeat")
            if st.form_submit_button("Change password", key="account_change"):
                try:
                    if new != repeat:
                        raise ValueError("The two new passwords do not match.")
                    accounts.change_password(record["username"], old, new)
                except ValueError as exc:
                    st.error(common.md(str(exc)), icon=":material/error:")
                else:
                    state["weak_password"] = False
                    state["password_changed"] = True
                    common.flash("Password changed.", ":material/lock_reset:")
                    st.rerun()
    if record["role"] == "teacher":
        with st.container(border=True):
            st.subheader("More teachers", anchor=False)
            st.caption("Teacher accounts are created on the server, never from the sign-in page:")
            st.code("python -m classroom.cli create-teacher <username> --display-name \"<name>\"",
                    language="bash")
common.skip_show_password_buttons()
