"""Accounts for teachers and students, stored in data/users.json.

Passwords are never stored. Each is hashed with PBKDF2-HMAC-SHA256 and a
random 16-byte salt (hashlib, standard library) and checked in constant time
(hmac.compare_digest). The stored string carries its own iteration count, so
the count can be raised later without breaking existing accounts.

Students register themselves from the sign-in page. Teachers are created by
the first-run setup screen (only while no teacher exists) or from the
command line (classroom/cli.py), never by self-registration.
"""

import hashlib
import hmac
import re
import secrets

from classroom import paths, store

ROLES = ("teacher", "student")
ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000
MIN_PASSWORD = 8
MAX_DISPLAY_NAME = 60
USERNAME_RULE = re.compile(r"[a-z0-9][a-z0-9_.-]{2,23}")
EMPTY = {"version": 1, "users": {}}


# ------------------------------------------------------------------ hashing
def hash_password(password, salt=None, iterations=None):
    iterations = int(iterations or ITERATIONS)
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "{}${}${}${}".format(ALGORITHM, iterations, salt.hex(), digest.hex())


def verify_password(password, stored):
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                        bytes.fromhex(salt), int(iterations))
    except (AttributeError, ValueError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)


# ---------------------------------------------------------------- usernames
def normalise_username(text):
    return (text or "").strip().lower()


def validate_username(username):
    if not USERNAME_RULE.fullmatch(username):
        raise ValueError("Usernames are 3 to 24 characters: lowercase letters, digits, dots, "
                         "dashes or underscores, starting with a letter or a digit.")


def validate_password(password):
    if len(password or "") < MIN_PASSWORD:
        raise ValueError("Passwords need at least {} characters.".format(MIN_PASSWORD))


def public(username, record):
    """What the app may hold in memory about a user: never the hash."""
    return {"username": username,
            "display_name": record.get("display_name") or username,
            "role": record.get("role", ""),
            "created_at": record.get("created_at", ""),
            "last_login": record.get("last_login", "")}


def _users():
    return store.read_json(paths.users_path(), EMPTY)["users"]


# --------------------------------------------------------------- operations
def register(username, password, role, display_name=""):
    """Create an account and return its public record. ValueError explains
    any rule that was broken (taken name, weak password, unknown role)."""
    username = normalise_username(username)
    validate_username(username)
    if role not in ROLES:
        raise ValueError("Role must be one of {}.".format(", ".join(ROLES)))
    validate_password(password)
    display_name = " ".join((display_name or "").split()) or username
    if len(display_name) > MAX_DISPLAY_NAME:
        raise ValueError("Display names are at most {} characters.".format(MAX_DISPLAY_NAME))
    record = {"display_name": display_name, "role": role,
              "password": hash_password(password),        # slow on purpose; outside the lock
              "created_at": store.now(), "last_login": ""}

    def add(data):
        if username in data["users"]:
            raise ValueError("The username {} is already taken.".format(username))
        data["users"][username] = record
    store.update_json(paths.users_path(), EMPTY, add)
    return public(username, record)


def authenticate(username, password):
    """The public record when the password matches, else None. A successful
    sign-in records last_login (an atomic write; no backup copy is kept for
    this routine field)."""
    username = normalise_username(username)
    record = _users().get(username)
    if record is None or not verify_password(password or "", record.get("password", "")):
        return None

    def touch(data):
        data["users"][username]["last_login"] = store.now()
        return public(username, data["users"][username])
    return store.update_json(paths.users_path(), EMPTY, touch, keep_backup=False)


def get_user(username):
    username = normalise_username(username)
    record = _users().get(username)
    return public(username, record) if record else None


def list_users(role=None):
    users = [public(u, r) for u, r in _users().items()]
    if role:
        users = [u for u in users if u["role"] == role]
    return sorted(users, key=lambda u: u["username"])


def display_names():
    """username -> display name, for tables."""
    return {u: r.get("display_name") or u for u, r in _users().items()}


def has_teacher():
    return any(r.get("role") == "teacher" for r in _users().values())


def exists(username):
    return normalise_username(username) in _users()


def change_password(username, old_password, new_password):
    username = normalise_username(username)
    record = _users().get(username)
    if record is None or not verify_password(old_password or "", record.get("password", "")):
        raise ValueError("The current password is not correct.")
    reset_password(username, new_password)


def reset_password(username, new_password):
    """Set a new password without the old one (the command line uses this)."""
    username = normalise_username(username)
    validate_password(new_password)
    hashed = hash_password(new_password)

    def change(data):
        if username not in data["users"]:
            raise ValueError("There is no user {}.".format(username))
        data["users"][username]["password"] = hashed
    store.update_json(paths.users_path(), EMPTY, change)


def rename(username, display_name):
    username = normalise_username(username)
    display_name = " ".join((display_name or "").split())
    if not display_name or len(display_name) > MAX_DISPLAY_NAME:
        raise ValueError("Display names are 1 to {} characters.".format(MAX_DISPLAY_NAME))

    def change(data):
        if username not in data["users"]:
            raise ValueError("There is no user {}.".format(username))
        data["users"][username]["display_name"] = display_name
        return public(username, data["users"][username])
    return store.update_json(paths.users_path(), EMPTY, change)
