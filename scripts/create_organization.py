# scripts/create_organization.py

"""
Script to create organizations from the command line.
Similar to create_admin.py, allows bootstrapping organizations.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from flask_app.models import Organization, db  # noqa: F401


def generate_slug(name):
    """Generate a URL-friendly slug from a name"""
    # Convert to lowercase
    slug = name.lower()
    # Replace spaces and underscores with hyphens
    slug = re.sub(r"[_\s]+", "-", slug)
    # Remove all non-alphanumeric characters except hyphens
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    # Remove multiple consecutive hyphens
    slug = re.sub(r"-+", "-", slug)
    # Remove leading/trailing hyphens
    slug = slug.strip("-")
    return slug


def create_organization():
    with app.app_context():
        name = input("Enter organization name: ").strip()

        if not name:
            print("Error: Organization name cannot be empty.")
            sys.exit(1)

        # Generate slug from name
        suggested_slug = generate_slug(name)
        print(f"Suggested slug: {suggested_slug}")

        slug_input = input(f'Enter slug (or press Enter to use "{suggested_slug}"): ').strip()
        slug = slug_input if slug_input else suggested_slug

        if not slug:
            print("Error: Slug cannot be empty.")
            sys.exit(1)

        # Validate slug format
        if not re.match(r"^[a-z0-9\-]+$", slug):
            print("Error: Slug can only contain lowercase letters, numbers, and hyphens.")
            sys.exit(1)

        # Check if slug already exists
        if Organization.find_by_slug(slug):
            print(f'Error: An organization with slug "{slug}" already exists.')
            sys.exit(1)

        description = input("Enter description (optional): ").strip() or None

        # Create organization
        org, error = Organization.safe_create(
            name=name, slug=slug, description=description, is_active=True
        )

        if error:
            print(f"Error creating organization: {error}")
            sys.exit(1)
        else:
            print("Organization created successfully!")
            print(f"   Name: {org.name}")
            print(f"   Slug: {org.slug}")
            print(f'   Description: {org.description or "None"}')
            print(f"   Active: {org.is_active}")
            print("\nYou can now assign users to this organization when creating them.")


if __name__ == "__main__":
    create_organization()
