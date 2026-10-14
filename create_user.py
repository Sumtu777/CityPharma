# ============================================
# create_user.py
# Creates a CityPharma login (e.g. the first manager account)
# after the database schema has been imported.
#
# Usage:
#   python create_user.py
#   python create_user.py --username manager1 --role manager
#
# The password is always typed in (hidden), never stored in code.
# ============================================

import argparse
import getpass

from werkzeug.security import generate_password_hash

from app import get_db_connection


def ask(value, prompt):
    """Use the value from the command line, or ask for it."""
    return value if value else input(prompt).strip()


def main():
    parser = argparse.ArgumentParser(description="Create a CityPharma user")
    parser.add_argument("--full-name")
    parser.add_argument("--username")
    parser.add_argument("--email")
    parser.add_argument("--role", choices=["manager", "staff"])
    args = parser.parse_args()

    full_name = ask(args.full_name, "Full name: ")
    username = ask(args.username, "Username: ")
    email = ask(args.email, "Email: ")
    role = ask(args.role, "Role (manager/staff): ").lower()

    if role not in ("manager", "staff"):
        print("Role must be 'manager' or 'staff'.")
        return

    password = getpass.getpass("Password (min 6 characters): ")
    if len(password) < 6:
        print("Password must be at least 6 characters.")
        return
    if getpass.getpass("Confirm password: ") != password:
        print("Passwords do not match.")
        return

    # Same hashing method the app uses when a manager adds a user
    password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT user_id FROM users WHERE username = %s", (username,))
    if cursor.fetchone():
        print(f"A user called '{username}' already exists.")
    else:
        cursor.execute(
            """INSERT INTO users (full_name, username, email, password_hash, role)
               VALUES (%s, %s, %s, %s, %s)""",
            (full_name, username, email, password_hash, role),
        )
        conn.commit()
        print(f"Created {role} account '{username}'.")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
