"""Account tools for the command line. Teachers are never created from the
browser after the first one, so this is how a second teacher is added.

    python -m classroom.cli create-teacher reyes --display-name "Prof. Reyes"
    python -m classroom.cli list-users
    python -m classroom.cli reset-password alice
"""

import argparse
import getpass
import sys

from classroom import accounts, paths


def _ask_password():
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat the password: "):
        raise ValueError("The two passwords do not match.")
    return password


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m classroom.cli",
                                     description="MarkText Classroom account tools")
    sub = parser.add_subparsers(dest="command", required=True)
    teacher = sub.add_parser("create-teacher", help="add a teacher account")
    teacher.add_argument("username")
    teacher.add_argument("--display-name", default="")
    sub.add_parser("list-users", help="list every account (never the passwords)")
    reset = sub.add_parser("reset-password", help="set a new password for an account")
    reset.add_argument("username")
    args = parser.parse_args(argv)

    paths.ensure_dirs()
    try:
        if args.command == "create-teacher":
            user = accounts.register(args.username, _ask_password(), "teacher", args.display_name)
            print("Teacher {} ({}) created.".format(user["username"], user["display_name"]))
        elif args.command == "list-users":
            users = accounts.list_users()
            if not users:
                print("No accounts yet.")
            for u in users:
                print("{:<24} {:<8} {:<30} last sign-in {}".format(
                    u["username"], u["role"], u["display_name"], u["last_login"] or "never"))
        elif args.command == "reset-password":
            if not accounts.exists(args.username):
                raise ValueError("There is no user {}.".format(args.username))
            accounts.reset_password(args.username, _ask_password(), by="command line")
            print("Password changed for {}.".format(accounts.normalise_username(args.username)))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
