# create_admin.py

from getpass import getpass
import sys
from flask_app.models import db, User
from werkzeug.security import generate_password_hash
from app import app

def create_admin():
    with app.app_context():
        username = input('Enter username: ').strip()
        email = input('Enter email: ').strip()

        if User.query.filter_by(username=username).first():
            print('Error: Username already exists.')
            sys.exit(1)

        if User.query.filter_by(email=email).first():
            print('Error: Email already exists.')
            sys.exit(1)

        password = getpass('Enter password: ')
        password2 = getpass('Confirm password: ')

        if password != password2:
            print('Error: Passwords do not match.')
            sys.exit(1)

        if not password:
            print('Error: Password cannot be empty.')
            sys.exit(1)

        new_admin = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            is_active=True,
            is_admin=True
        )

        # Use the safe_create method from BaseModel
        admin_user, error = User.safe_create(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            is_active=True,
            is_admin=True
        )
        
        if error:
            print(f'Error creating admin account: {error}')
            sys.exit(1)
        else:
            print('✅ Admin account created successfully!')
            print(f'   Username: {admin_user.username}')
            print(f'   Email: {admin_user.email}')
            print(f'   Admin: {admin_user.is_admin}')
            print(f'   Active: {admin_user.is_active}')

if __name__ == '__main__':
    create_admin()
