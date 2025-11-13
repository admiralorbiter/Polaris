"""Shared fixtures for route tests"""

import pytest

from flask_app.models import Contact, ContactEmail, Organization, db


@pytest.fixture
def sample_contacts_for_dashboard(app, test_organization):
    """Create sample contacts for dashboard testing"""
    contacts = []
    for i in range(5):
        contact = Contact(
            first_name=f"Contact{i}",
            last_name="Test",
            organization_id=test_organization.id if i < 3 else None,
        )
        contacts.append(contact)
        db.session.add(contact)
        db.session.flush()  # Flush to get contact.id

        # Add email to first 3 contacts
        if i < 3:
            email = ContactEmail(
                contact_id=contact.id,
                email=f"contact{i}@example.com",
                email_type="PERSONAL",
            )
            db.session.add(email)

    db.session.commit()
    return contacts
