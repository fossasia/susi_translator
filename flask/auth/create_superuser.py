import argparse
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from transcribe_server import app, bcrypt, db
from auth.models import Organizer
from sqlalchemy.exc import SQLAlchemyError

def create_or_promote_superuser(email, password, name):
    with app.app_context():
        user = Organizer.query.filter_by(email=email).first()
        
        if user:
            print(f"User {email} already exists. Promoting to admin...")
            user.is_admin = True
            if password:
                user.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
                print("Password updated.")
            if name:
                user.name = name
        else:
            print(f"Creating new superuser {email}...")
            if not password:
                print("Error: Password is required for a new user.")
                sys.exit(1)
            pw_hash = bcrypt.generate_password_hash(password).decode("utf-8")
            user = Organizer(email=email, password_hash=pw_hash, name=name, is_admin=True)
            db.session.add(user)

        try:
            db.session.commit()
            print("Successfully saved superuser!")
        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"Database error: {e}")
            sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or promote an admin user")
    parser.add_argument("--email", required=True, help="Email address of the superuser")
    parser.add_argument("--password", help="Password (required for new users)")
    parser.add_argument("--name", help="Name of the superuser")
    
    args = parser.parse_args()
    create_or_promote_superuser(args.email, args.password, args.name)