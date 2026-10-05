"""
create_user.py - admin CLI to manage RCM Generator web-app accounts.

Run this ON THE SERVER (same folder as app.py). No internet needed - it only
uses auth.py (stdlib only).

Usage:
    python create_user.py add <username> ["Display Name"]
        Prompts for a password (hidden input), creates/updates the account.

    python create_user.py remove <username>
        Deletes the account.

    python create_user.py list
        Lists all existing usernames.
"""

import getpass
import sys

import auth


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "add":
        if len(sys.argv) < 3:
            print("Usage: python create_user.py add <username> [\"Display Name\"]")
            sys.exit(1)
        username = sys.argv[2]
        display_name = sys.argv[3] if len(sys.argv) > 3 else username
        password = getpass.getpass(f"Set password for '{username}': ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("ERROR: Passwords did not match. Nothing was saved.")
            sys.exit(1)
        if len(password) < 6:
            print("ERROR: Use a password with at least 6 characters.")
            sys.exit(1)
        auth.add_user(username, password, display_name)
        print(f"OK: account '{username}' ({display_name}) created/updated.")

    elif command == "remove":
        if len(sys.argv) < 3:
            print("Usage: python create_user.py remove <username>")
            sys.exit(1)
        username = sys.argv[2]
        if auth.remove_user(username):
            print(f"OK: account '{username}' removed.")
        else:
            print(f"No such account: '{username}'.")

    elif command == "list":
        users = auth.list_users()
        if not users:
            print("No accounts exist yet.")
        else:
            print("Accounts:")
            for u in users:
                print(f"  - {u}")

    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
