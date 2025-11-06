# scripts/create_contact_tables.py

"""
Script to create contact-related database tables.
This script can be run to ensure all contact tables are created in the database.

Note: If using db.create_all() in your app initialization, tables will be created automatically.
This script is useful for manual database setup or verification.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from flask_app.models import (
    Contact,
    ContactAddress,
    ContactEmail,
    ContactOrganization,
    ContactPhone,
    ContactRole,
    ContactTag,
    EmergencyContact,
    Student,
    Teacher,
    Volunteer,
    db,
)


def create_contact_tables():
    """Create all contact-related tables"""
    with app.app_context():
        print("Creating contact-related database tables...")

        # Import all models to ensure they're registered
        # This ensures SQLAlchemy knows about all tables
        try:
            # Create all tables (this will only create new ones)
            db.create_all()
            print("✓ Contact tables created successfully")

            # Verify tables exist
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()

            contact_tables = [
                "contacts",
                "contact_emails",
                "contact_phones",
                "contact_addresses",
                "contact_roles",
                "contact_organizations",
                "contact_tags",
                "emergency_contacts",
                "volunteers",
                "students",
                "teachers",
            ]

            print("\nVerifying tables:")
            for table in contact_tables:
                if table in tables:
                    print(f"  ✓ {table}")
                else:
                    print(f"  ✗ {table} (missing)")

            print("\nContact tables setup complete!")
            print("\nNext steps:")
            print("  - You can now create contacts using the Contact model")
            print("  - Use sub-classes (Volunteer, Student, Teacher) for type-specific contacts")
            print("  - Add roles via ContactRole for multi-class support")

        except Exception as e:
            print(f"✗ Error creating contact tables: {str(e)}")
            import traceback

            traceback.print_exc()
            return False

    return True


if __name__ == "__main__":
    create_contact_tables()

