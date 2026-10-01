"""Classes, join codes and rosters.

data/classes.json holds one record per class: name, term, teacher and the
join code students type to enrol. data/rosters.csv holds one row per
(class, student) with a status:
- active: the student is in the class;
- invited: the teacher imported the username before the student registered.
  The student joins with the class code, which turns the invitation into
  membership. A username alone is not enough: anyone could register it
  first, so the code is the proof of being in the class;
- removed: the teacher took the student out. Rows are never deleted, so the
  roster keeps its history; every status change is a backed-up rewrite.
"""

import csv
import io
import re
import secrets

from classroom import accounts, audit, paths, store

EMPTY = {"version": 1, "classes": {}}
ROSTER_COLUMNS = ["class_id", "username", "status", "added_via", "joined_at", "removed_at"]
STATUSES = ("active", "invited", "removed")
EXPORT_COLUMNS = ["username", "display_name", "status", "added_via", "joined_at", "removed_at"]

# no 0/O or 1/I: codes are read aloud and copied from a projector
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
MAX_NAME = 80
MAX_IMPORT_ROWS = 500


# --------------------------------------------------------------- join codes
def new_join_code(taken=()):
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if code not in taken:
            return code


def format_code(code):
    """ABC234 -> ABC-234, for display."""
    return "{}-{}".format(code[:3], code[3:]) if len(code) == CODE_LENGTH else code


def normalise_code(text):
    """What the student typed -> the stored form (case, spaces, dash ignored)."""
    return re.sub(r"[\s\-]", "", text or "").upper()


# ------------------------------------------------------------------ classes
def _classes():
    return store.read_json(paths.classes_path(), EMPTY)["classes"]


def _clean(text, limit, what):
    text = " ".join((text or "").split())
    if len(text) > limit:
        raise ValueError("{} is limited to {} characters.".format(what, limit))
    return text


def create_class(name, teacher, term=""):
    name = _clean(name, MAX_NAME, "The class name")
    if not name:
        raise ValueError("Give the class a name.")
    term = _clean(term, MAX_NAME, "The term")
    owner = accounts.get_user(teacher)
    if owner is None or owner["role"] != "teacher":
        raise ValueError("Only a teacher can create a class.")
    record = {"class_id": store.new_id("cls"), "name": name, "term": term,
              "teacher": owner["username"], "join_code": "", "created_at": store.now(),
              "archived": False}

    def add(data):
        record["join_code"] = new_join_code({c["join_code"] for c in data["classes"].values()})
        data["classes"][record["class_id"]] = record
        return dict(record)
    created = store.update_json(paths.classes_path(), EMPTY, add)
    audit.record(owner["username"], "class_created", created["class_id"], name)
    return created


def get_class(class_id):
    record = _classes().get(class_id)
    return dict(record) if record else None


def list_classes(teacher=None, include_archived=False):
    """Newest first."""
    out = [dict(c) for c in _classes().values()
           if (teacher is None or c["teacher"] == teacher)
           and (include_archived or not c.get("archived"))]
    return sorted(out, key=lambda c: (c["created_at"], c["name"]), reverse=True)


def _change_class(class_id, by, change):
    def apply(data):
        record = data["classes"].get(class_id)
        if record is None:
            raise ValueError("There is no class {}.".format(class_id))
        if by is not None and record["teacher"] != by:
            raise ValueError("Only the class's teacher can change it.")
        return change(record, data)
    return store.update_json(paths.classes_path(), EMPTY, apply)


def rotate_join_code(class_id, by=None):
    """A new code; the old one stops working. Students already enrolled stay."""
    def change(record, data):
        record["join_code"] = new_join_code({c["join_code"] for c in data["classes"].values()})
        return record["join_code"]
    code = _change_class(class_id, by, change)
    audit.record(by, "join_code_changed", class_id)
    return code


def rename_class(class_id, name, term, by=None):
    name = _clean(name, MAX_NAME, "The class name")
    if not name:
        raise ValueError("Give the class a name.")
    term = _clean(term, MAX_NAME, "The term")

    def change(record, data):
        record.update(name=name, term=term)
        return dict(record)
    renamed = _change_class(class_id, by, change)
    audit.record(by, "class_renamed", class_id, name)
    return renamed


def set_archived(class_id, archived=True, by=None):
    def change(record, data):
        record["archived"] = bool(archived)
        return dict(record)
    changed = _change_class(class_id, by, change)
    audit.record(by, "class_archived" if archived else "class_restored", class_id)
    return changed


def find_by_join_code(code):
    code = normalise_code(code)
    for record in _classes().values():
        if record["join_code"] == code and not record.get("archived"):
            return dict(record)
    return None


# ------------------------------------------------------------------ rosters
def _rows():
    return store.read_rows(paths.rosters_path(), ROSTER_COLUMNS)


def roster(class_id, status="active"):
    """Roster rows of one class; status=None returns every row."""
    return [r for r in _rows()
            if r["class_id"] == class_id and (status is None or r["status"] == status)]


def membership(class_id, username):
    for row in _rows():
        if row["class_id"] == class_id and row["username"] == username:
            return row
    return None


def is_member(class_id, username):
    row = membership(class_id, accounts.normalise_username(username))
    return row is not None and row["status"] == "active"


def classes_for_student(username):
    """The classes the student is active in, newest first."""
    username = accounts.normalise_username(username)
    ids = {r["class_id"] for r in _rows() if r["username"] == username and r["status"] == "active"}
    return [c for c in list_classes(include_archived=False) if c["class_id"] in ids]


def student_counts():
    """class_id -> number of active students."""
    counts = {}
    for row in _rows():
        if row["status"] == "active":
            counts[row["class_id"]] = counts.get(row["class_id"], 0) + 1
    return counts


def join_class(code, username):
    """Enrol a student with the class's join code. Returns the class."""
    username = accounts.normalise_username(username)
    user = accounts.get_user(username)
    if user is None or user["role"] != "student":
        raise ValueError("Only students join classes with a code.")
    record = find_by_join_code(code)
    if record is None:
        raise ValueError("No class uses the code {}. Check it with your teacher.".format(
            format_code(normalise_code(code)) or "(empty)"))
    class_id = record["class_id"]
    path = paths.rosters_path()
    with store.lock_for(path):
        row = membership(class_id, username)
        if row and row["status"] == "active":
            raise ValueError("You are already in {}.".format(record["name"]))
        if row and row["status"] == "removed":
            raise ValueError("Your teacher removed you from {}. Ask them to add you again.".format(
                record["name"]))
        if row:                                         # an invitation: accept it
            store.update_where(path, ROSTER_COLUMNS, _is(class_id, username),
                               lambda r: dict(r, status="active", joined_at=store.now()),
                               "{} in {}".format(username, class_id))
        else:
            store.append_row(path, ROSTER_COLUMNS, {
                "class_id": class_id, "username": username, "status": "active",
                "added_via": "code", "joined_at": store.now(), "removed_at": ""})
    audit.record(username, "joined_class", class_id,
                 "accepted an invitation" if row else "with the join code")
    return record


def _is(class_id, username):
    return lambda r: r["class_id"] == class_id and r["username"] == username


def remove_student(class_id, username, by=None):
    """Mark the student (or an unclaimed invitation) removed. Their
    submissions stay on file. Returns the backup path."""
    record = get_class(class_id)
    if record is None:
        raise ValueError("There is no class {}.".format(class_id))
    if by is not None and record["teacher"] != by:
        raise ValueError("Only the class's teacher can change the roster.")
    username = accounts.normalise_username(username)

    def match(r):
        return _is(class_id, username)(r) and r["status"] != "removed"
    saved = store.update_where(paths.rosters_path(), ROSTER_COLUMNS, match,
                               lambda r: dict(r, status="removed", removed_at=store.now()),
                               "{} in {}".format(username, class_id))
    audit.record(by, "student_removed", class_id, username)
    return saved


def add_back(class_id, username, by=None):
    """Undo a removal: the row becomes active again, or invited when the
    student never joined (an imported name not yet claimed with the code).
    The class code refuses a removed student, so this is the way back.
    Returns the backup path."""
    record = get_class(class_id)
    if record is None:
        raise ValueError("There is no class {}.".format(class_id))
    if by is not None and record["teacher"] != by:
        raise ValueError("Only the class's teacher can change the roster.")
    username = accounts.normalise_username(username)

    def match(r):
        return _is(class_id, username)(r) and r["status"] == "removed"
    saved = store.update_where(paths.rosters_path(), ROSTER_COLUMNS, match,
                               lambda r: dict(r, status="active" if r["joined_at"] else "invited",
                                              removed_at=""),
                               "{} in {}".format(username, class_id))
    audit.record(by, "student_added_back", class_id, username)
    return saved


def reset_student_password(class_id, username, by):
    """A temporary password for a student of the teacher's class, returned
    once for the teacher to hand over; the student must replace it at the
    next sign-in. Only the class's teacher, only for an active student."""
    record = get_class(class_id)
    if record is None or record["teacher"] != by:
        raise ValueError("Only the class's teacher can reset a student's password.")
    username = accounts.normalise_username(username)
    if not is_member(class_id, username):
        raise ValueError("{} is not an active student of this class.".format(username))
    temporary = accounts.temporary_password()
    accounts.reset_password(username, temporary, by=by)
    return temporary


def parse_roster_csv(data):
    """Rows from an uploaded roster file. It needs a header with a
    `username` column; other columns (a display name, an email) are ignored."""
    try:
        text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    except UnicodeDecodeError as exc:
        raise ValueError("The roster file is not UTF-8 text. Save it as CSV UTF-8 and try "
                         "again.") from exc
    reader = csv.DictReader(io.StringIO(text))
    fields = {(f or "").strip().lower(): f for f in (reader.fieldnames or [])}
    if "username" not in fields:
        raise ValueError("The roster file needs a header row with a username column.")
    rows = []
    for row in reader:
        rows.append({"username": (row.get(fields["username"]) or "").strip()})
        if len(rows) > MAX_IMPORT_ROWS:
            raise ValueError("A roster file may list at most {} students.".format(MAX_IMPORT_ROWS))
    return rows


def import_roster(class_id, rows, by=None):
    """Add many students at once. Registered students are enrolled; unknown
    usernames become invitations that registering accepts. One backed-up
    rewrite for the whole import. Returns {"enrolled", "invited", "skipped"}
    where skipped is a list of (username, reason)."""
    record = get_class(class_id)
    if record is None:
        raise ValueError("There is no class {}.".format(class_id))
    if by is not None and record["teacher"] != by:
        raise ValueError("Only the class's teacher can change the roster.")
    result = {"enrolled": [], "invited": [], "skipped": []}
    path = paths.rosters_path()
    with store.lock_for(path):
        all_rows = _rows()
        mine = {r["username"]: r for r in all_rows if r["class_id"] == class_id}
        seen = set()
        for item in rows:
            raw = (item.get("username") or "").strip()
            username = accounts.normalise_username(raw)
            if not username:
                continue
            if username in seen:
                result["skipped"].append((username, "listed twice"))
                continue
            seen.add(username)
            try:
                accounts.validate_username(username)
            except ValueError:
                result["skipped"].append((raw, "not a valid username"))
                continue
            user = accounts.get_user(username)
            if user is not None and user["role"] != "student":
                result["skipped"].append((username, "is a teacher account"))
                continue
            row = mine.get(username)
            if row is not None and row["status"] == "active":
                result["skipped"].append((username, "already in the class"))
                continue
            if row is not None and row["status"] == "invited":
                result["skipped"].append((username, "already invited"))
                continue
            status = "active" if user is not None else "invited"
            if row is not None:                         # removed earlier: the teacher re-adds
                row.update(status=status, added_via="import", joined_at=store.now(), removed_at="")
            else:
                row = {"class_id": class_id, "username": username, "status": status,
                       "added_via": "import", "joined_at": store.now() if user else "",
                       "removed_at": ""}
                all_rows.append(row)
                mine[username] = row
            result["enrolled" if user is not None else "invited"].append(username)
        if result["enrolled"] or result["invited"]:
            store.rewrite_rows(path, ROSTER_COLUMNS, all_rows)
    audit.record(by, "roster_imported", class_id, "{} enrolled, {} invited, {} skipped".format(
        len(result["enrolled"]), len(result["invited"]), len(result["skipped"])))
    return result


def export_rows(class_id):
    """The roster with display names, active first, as written by export_roster()."""
    names = accounts.display_names()
    rows = [dict(r, display_name=names.get(r["username"], "")) for r in roster(class_id, None)]
    rows.sort(key=lambda r: (STATUSES.index(r["status"]), r["username"]))
    return rows


def export_roster(class_id, by=None):
    """Write the class roster, with display names, to a new CSV file under
    data/reports/ and return its path."""
    if get_class(class_id) is None:
        raise ValueError("There is no class {}.".format(class_id))
    target = store.unique_path(paths.reports_dir(), "roster_{}_{}".format(class_id, store.stamp()), ".csv")
    path = store.write_new_csv(target, EXPORT_COLUMNS, export_rows(class_id))
    audit.record(by, "exported", paths.data_relative(path), "roster of {}".format(class_id))
    return path
