# create_admin.py

import os
import sys
from getpass import getpass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash

from app import app
from flask_app.models import User, db  # noqa: F401


def create_admin():
    with app.app_context():
        username = input("Enter username: ").strip()
        email = input("Enter email: ").strip()

        if User.query.filter_by(username=username).first():
            print("Error: Username already exists.")
            sys.exit(1)

        if User.query.filter_by(email=email).first():
            print("Error: Email already exists.")
            sys.exit(1)

        password = getpass("Enter password: ")
        password2 = getpass("Confirm password: ")

        if password != password2:
            print("Error: Passwords do not match.")
            sys.exit(1)

        if not password:
            print("Error: Password cannot be empty.")
            sys.exit(1)

        # Use the safe_create method from BaseModel
        admin_user, error = User.safe_create(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            is_active=True,
            is_super_admin=True,
        )

        if error:
            print(f"Error creating admin account: {error}")
            sys.exit(1)
        else:
            print("✅ Super admin account created successfully!")
            print(f"   Username: {admin_user.username}")
            print(f"   Email: {admin_user.email}")
            print(f"   Super Admin: {admin_user.is_super_admin}")
            print(f"   Active: {admin_user.is_active}")
            print("\nNote: Super admins have full access to all organizations and system features.")


if __name__ == "__main__":
    create_admin()
