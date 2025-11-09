# scripts/seed_database.py
"""
Database seeding script.
Populates the database with comprehensive sample data for development and testing.
"""

import argparse
import os
import sys
from datetime import date, time, timedelta
from getpass import getpass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faker import Faker
from werkzeug.security import generate_password_hash

from app import app

fake = Faker()
from flask_app.models import (
    ContactOrganization,
    ContactRole,
    ContactStatus,
    ContactType,
    EmailType,
    Event,
    EventFormat,
    EventOrganization,
    EventStatus,
    EventType,
    EventVolunteer,
    EventVolunteerRole,
    Organization,
    OrganizationAddress,
    OrganizationType,
    PhoneType,
    RegistrationStatus,
    Role,
    RoleType,
    Student,
    Teacher,
    User,
    UserOrganization,
    Volunteer,
    VolunteerAvailability,
    VolunteerHours,
    VolunteerInterest,
    VolunteerSkill,
    VolunteerStatus,
    db,
)
from flask_app.models.contact import AddressType, ContactAddress, ContactEmail, ContactPhone

# Statistics tracking
stats = {
    "admin_users": 0,
    "organizations": 0,
    "users": 0,
    "volunteers": 0,
    "students": 0,
    "teachers": 0,
    "events": 0,
    "errors": [],
}


def _commit_batch(pending_count, batch_size):
    """Commit the current SQLAlchemy session if we've reached the batch threshold."""
    if pending_count >= batch_size:
        try:
            db.session.commit()
            return 0
        except Exception as exc:  # noqa: BLE001 - surface commit issues during seeding
            db.session.rollback()
            stats["errors"].append(f"Batch commit failed: {exc}")
            print(f"  ❌ Batch commit failed: {exc}")
            return 0
    return pending_count


def clear_database():
    """Clear all seeded data from the database"""
    print("Clearing existing data...")
    with app.app_context():
        try:
            # Delete in reverse order of dependencies
            EventVolunteer.query.delete()
            EventOrganization.query.delete()
            Event.query.delete()
            VolunteerHours.query.delete()
            VolunteerAvailability.query.delete()
            VolunteerInterest.query.delete()
            VolunteerSkill.query.delete()
            Volunteer.query.delete()
            Student.query.delete()
            Teacher.query.delete()
            ContactRole.query.delete()
            ContactOrganization.query.delete()
            ContactEmail.query.delete()
            ContactPhone.query.delete()
            ContactAddress.query.delete()
            UserOrganization.query.delete()
            User.query.filter_by(is_super_admin=False).delete()
            Organization.query.delete()
            db.session.commit()
            print("✅ Database cleared")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error clearing database: {str(e)}")
            sys.exit(1)


def seed_admin_user(username="admin", email="admin@gmail.com", password=None, dry_run=False):
    """Create super admin user"""
    print("\n📝 Seeding admin user...")

    if dry_run:
        print(f"  [DRY RUN] Would create admin user: {username} ({email})")
        return None

    with app.app_context():
        # Check if admin already exists
        existing = User.query.filter_by(username=username).first()
        if existing:
            print(f"  ⏭️  Admin user '{username}' already exists, skipping")
            return existing

        if not password:
            password = "admin"  # Default password

        admin_user, error = User.safe_create(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            is_active=True,
            is_super_admin=True,
        )

        if error:
            stats["errors"].append(f"Admin user: {error}")
            print(f"  ❌ Error creating admin user: {error}")
            return None

        stats["admin_users"] += 1
        print(f"  ✅ Created admin user: {username} ({email})")
        return admin_user


def seed_organizations(dry_run=False):
    """Create sample organizations with full details"""
    print("\n📝 Seeding organizations...")

    organizations_data = [
        {
            "name": "Community Center",
            "slug": "community-center",
            "description": "Local community center providing various programs and services",
            "organization_type": OrganizationType.NON_PROFIT,
            "website": "https://communitycenter.example.com",
            "phone": "555-1001",
            "email": "info@communitycenter.example.com",
            "tax_id": "12-3456789",
            "contact_person_name": "Alice Johnson",
            "contact_person_title": "Director",
            "founded_date": date(2010, 1, 15),
            "address": {
                "street_address_1": "123 Main Street",
                "street_address_2": "Suite 100",
                "city": "Springfield",
                "state": "IL",
                "postal_code": "62701",
                "country": "US",
            },
        },
        {
            "name": "Local School District",
            "slug": "local-school",
            "description": "Public school district serving the local community",
            "organization_type": OrganizationType.SCHOOL,
            "website": "https://schools.example.com",
            "phone": "555-2001",
            "email": "info@schools.example.com",
            "tax_id": "98-7654321",
            "contact_person_name": "Dr. Robert Smith",
            "contact_person_title": "Superintendent",
            "founded_date": date(1950, 9, 1),
            "address": {
                "street_address_1": "456 Education Avenue",
                "city": "Springfield",
                "state": "IL",
                "postal_code": "62702",
                "country": "US",
            },
        },
        {
            "name": "Non-Profit Organization",
            "slug": "nonprofit-org",
            "description": "Charitable organization focused on community outreach",
            "organization_type": OrganizationType.NON_PROFIT,
            "website": "https://nonprofit.example.com",
            "phone": "555-3001",
            "email": "contact@nonprofit.example.com",
            "tax_id": "45-6789012",
            "contact_person_name": "Sarah Williams",
            "contact_person_title": "Executive Director",
            "founded_date": date(2005, 6, 10),
            "address": {
                "street_address_1": "789 Charity Boulevard",
                "city": "Springfield",
                "state": "IL",
                "postal_code": "62703",
                "country": "US",
            },
        },
    ]

    created_orgs = []

    for org_data in organizations_data:
        if dry_run:
            print(f"  [DRY RUN] Would create organization: {org_data['name']}")
            created_orgs.append(org_data)
            continue

        with app.app_context():
            existing = Organization.query.filter_by(slug=org_data["slug"]).first()
            if existing:
                print(f"  ⏭️  Organization '{org_data['name']}' already exists, skipping")
                created_orgs.append(existing)
                continue

            # Extract address data before creating organization
            address_data = org_data.get("address")

            org, error = Organization.safe_create(
                name=org_data["name"],
                slug=org_data["slug"],
                description=org_data["description"],
                organization_type=org_data["organization_type"],
                website=org_data.get("website"),
                phone=org_data.get("phone"),
                email=org_data.get("email"),
                tax_id=org_data.get("tax_id"),
                contact_person_name=org_data.get("contact_person_name"),
                contact_person_title=org_data.get("contact_person_title"),
                founded_date=org_data.get("founded_date"),
                is_active=True,
            )

            if error:
                stats["errors"].append(f"Organization {org_data['name']}: {error}")
                print(f"  ❌ Error creating organization {org_data['name']}: {error}")
                continue

            # Add address if provided
            if address_data:
                try:
                    address = OrganizationAddress(
                        organization_id=org.id,
                        address_type=AddressType.WORK,
                        street_address_1=address_data["street_address_1"],
                        street_address_2=address_data.get("street_address_2"),
                        city=address_data["city"],
                        state=address_data["state"],
                        postal_code=address_data["postal_code"],
                        country=address_data.get("country", "US"),
                        is_primary=True,
                    )
                    db.session.add(address)
                    db.session.commit()
                    print(f"  ✅ Added address for {org_data['name']}")
                except Exception as e:
                    db.session.rollback()
                    stats["errors"].append(f"Organization {org_data['name']} address: {str(e)}")
                    print(f"  ⚠️  Error adding address for {org_data['name']}: {str(e)}")

            stats["organizations"] += 1
            print(f"  ✅ Created organization: {org_data['name']} ({org_data['organization_type'].value})")
            created_orgs.append(org)

    return created_orgs


def seed_users(organizations, roles, dry_run=False):
    """Create sample users and assign to organizations"""
    print("\n📝 Seeding users...")

    users_data = [
        # Org Admins
        {
            "username": "orgadmin1",
            "email": "orgadmin1@gmail.com",
            "first_name": "Alice",
            "last_name": "Johnson",
            "role": "ORG_ADMIN",
            "org_slug": "community-center",
        },
        {
            "username": "orgadmin2",
            "email": "orgadmin2@gmail.com",
            "first_name": "Bob",
            "last_name": "Smith",
            "role": "ORG_ADMIN",
            "org_slug": "local-school",
        },
        # Coordinators
        {
            "username": "coordinator1",
            "email": "coordinator1@gmail.com",
            "first_name": "Carol",
            "last_name": "Williams",
            "role": "COORDINATOR",
            "org_slug": "community-center",
        },
        {
            "username": "coordinator2",
            "email": "coordinator2@gmail.com",
            "first_name": "David",
            "last_name": "Brown",
            "role": "COORDINATOR",
            "org_slug": "nonprofit-org",
        },
        {
            "username": "coordinator3",
            "email": "coordinator3@gmail.com",
            "first_name": "Emma",
            "last_name": "Davis",
            "role": "COORDINATOR",
            "org_slug": "local-school",
        },
        # Regular users
        {
            "username": "user1",
            "email": "user1@gmail.com",
            "first_name": "Frank",
            "last_name": "Miller",
            "role": "VOLUNTEER",
            "org_slug": "community-center",
        },
        {
            "username": "user2",
            "email": "user2@gmail.com",
            "first_name": "Grace",
            "last_name": "Wilson",
            "role": "VOLUNTEER",
            "org_slug": "nonprofit-org",
        },
        # Viewers
        {
            "username": "viewer1",
            "email": "viewer1@gmail.com",
            "first_name": "Henry",
            "last_name": "Moore",
            "role": "VIEWER",
            "org_slug": "community-center",
        },
    ]

    created_users = []

    if dry_run:
        for user_data in users_data:
            print(f"  [DRY RUN] Would create user: {user_data['username']}")
            created_users.append(user_data)
        return created_users

    with app.app_context():
        required_slugs = {user["org_slug"] for user in users_data}
        org_lookup = {
            org.slug: org
            for org in Organization.query.filter(Organization.slug.in_(required_slugs)).all()
        }

        role_names = {user["role"] for user in users_data}
        role_lookup = {
            role.name: role for role in Role.query.filter(Role.name.in_(role_names)).all()
        }

        usernames = [user["username"] for user in users_data]
        emails = [user["email"] for user in users_data]
        existing_users = {
            user.username: user for user in User.query.filter(User.username.in_(usernames)).all()
        }
        existing_email_users = {
            user.email: user for user in User.query.filter(User.email.in_(emails)).all()
        }

        batch_size = 25
        pending_count = 0

        for user_data in users_data:
            username = user_data["username"]
            email = user_data["email"]

            existing = existing_users.get(username) or existing_email_users.get(email)
            if existing:
                print(f"  ⏭️  User '{username}' already exists, skipping")
                created_users.append(existing)
                continue

            org = org_lookup.get(user_data["org_slug"])
            if not org:
                stats["errors"].append(
                    f"User {username}: Organization '{user_data['org_slug']}' not found"
                )
                print(f"  ❌ Organization '{user_data['org_slug']}' not found for user {username}")
                continue

            role = role_lookup.get(user_data["role"])
            if not role:
                stats["errors"].append(f"User {username}: Role '{user_data['role']}' not found")
                print(f"  ❌ Role '{user_data['role']}' not found for user {username}")
                continue

            try:
                user = User(
                    username=username,
                    email=email,
                    password_hash=generate_password_hash("password123"),
                    first_name=user_data["first_name"],
                    last_name=user_data["last_name"],
                    is_active=True,
                    is_super_admin=False,
                )
                db.session.add(user)
                db.session.flush()

                user_org = UserOrganization(
                    user_id=user.id,
                    organization_id=org.id,
                    role_id=role.id,
                    is_active=True,
                )
                db.session.add(user_org)

                created_users.append(user)
                existing_users[user.username] = user
                existing_email_users[user.email] = user
                stats["users"] += 1
                pending_count += 1
                print(f"  ✅ Created user: {username} ({role.name} in {org.name})")
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                stats["errors"].append(f"User {username}: {exc}")
                print(f"  ❌ Error creating user {username}: {exc}")
                continue

            pending_count = _commit_batch(pending_count, batch_size)

        if pending_count:
            pending_count = _commit_batch(pending_count, 1)

    return created_users


def seed_volunteers(organizations, dry_run=False):
    """Create sample volunteers with full data - generates 75 volunteers for pagination testing"""
    print("\n📝 Seeding volunteers...")

    # Predefined volunteers for variety
    volunteers_data = [
        {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@gmail.com",
            "phone": "555-0101",
            "volunteer_status": VolunteerStatus.ACTIVE,
            "is_local": True,
            "title": "Software Engineer",
            "industry": "Technology",
            "skills": ["Python", "Web Development", "Database Design"],
            "interests": ["Education", "Technology"],
            "org_slug": "community-center",
        },
        {
            "first_name": "Jane",
            "last_name": "Smith",
            "email": "jane.smith@gmail.com",
            "phone": "555-0102",
            "volunteer_status": VolunteerStatus.ACTIVE,
            "is_local": True,
            "title": "Teacher",
            "industry": "Education",
            "skills": ["Teaching", "Curriculum Development", "Mentoring"],
            "interests": ["Education", "Youth Development"],
            "org_slug": "local-school",
        },
        {
            "first_name": "Michael",
            "last_name": "Johnson",
            "email": "michael.j@gmail.com",
            "phone": "555-0103",
            "volunteer_status": VolunteerStatus.HOLD,
            "is_local": False,
            "title": "Marketing Manager",
            "industry": "Marketing",
            "skills": ["Marketing", "Social Media", "Event Planning"],
            "interests": ["Community Outreach", "Events"],
            "org_slug": "nonprofit-org",
        },
        {
            "first_name": "Sarah",
            "last_name": "Williams",
            "email": "sarah.w@gmail.com",
            "phone": "555-0104",
            "volunteer_status": VolunteerStatus.ACTIVE,
            "is_local": True,
            "title": "Nurse",
            "industry": "Healthcare",
            "skills": ["First Aid", "Health Education", "Patient Care"],
            "interests": ["Health", "Community Service"],
            "org_slug": "community-center",
        },
        {
            "first_name": "Robert",
            "last_name": "Brown",
            "email": "robert.b@gmail.com",
            "phone": "555-0105",
            "volunteer_status": VolunteerStatus.INACTIVE,
            "is_local": True,
            "title": "Retired",
            "industry": "Retired",
            "skills": ["Woodworking", "Carpentry", "General Maintenance"],
            "interests": ["Building", "Repairs"],
            "org_slug": "community-center",
        },
    ]

    # Generate 70 more volunteers using Faker (total 75 for ~4 pages at 20 per page)
    org_slugs = ["community-center", "local-school", "nonprofit-org"]
    industries = [
        "Technology",
        "Education",
        "Healthcare",
        "Marketing",
        "Finance",
        "Retail",
        "Construction",
        "Retired",
        "Student",
        "Various",
    ]
    titles = [
        "Software Engineer",
        "Teacher",
        "Nurse",
        "Marketing Manager",
        "Accountant",
        "Manager",
        "Consultant",
        "Retired",
        "Student",
        "Volunteer Coordinator",
    ]
    skill_pools = [
        ["Python", "Web Development", "Database Design"],
        ["Teaching", "Curriculum Development", "Mentoring"],
        ["First Aid", "Health Education", "Patient Care"],
        ["Marketing", "Social Media", "Event Planning"],
        ["Accounting", "Financial Planning", "Tax Preparation"],
        ["Management", "Leadership", "Project Management"],
        ["Communication", "Public Speaking", "Writing"],
        ["Woodworking", "Carpentry", "General Maintenance"],
        ["General Volunteering", "Community Service"],
        ["Data Analysis", "Research", "Reporting"],
    ]
    interest_pools = [
        ["Education", "Technology"],
        ["Education", "Youth Development"],
        ["Health", "Community Service"],
        ["Community Outreach", "Events"],
        ["Building", "Repairs"],
        ["Environment", "Sustainability"],
        ["Arts", "Culture"],
        ["Sports", "Recreation"],
        ["Social Justice", "Advocacy"],
        ["Animal Welfare", "Pets"],
    ]

    for i in range(70):
        first_name = fake.first_name()
        last_name = fake.last_name()
        email = f"{first_name.lower()}.{last_name.lower()}{i}@gmail.com"
        phone = fake.phone_number()[:15]  # Limit phone length

        # Vary status: 60% active, 25% hold, 15% inactive
        status_rand = fake.random_int(1, 100)
        if status_rand <= 60:
            status = VolunteerStatus.ACTIVE
        elif status_rand <= 85:
            status = VolunteerStatus.HOLD
        else:
            status = VolunteerStatus.INACTIVE

        # Randomly assign organization
        org_slug = fake.random.choice(org_slugs)
        industry = fake.random.choice(industries)
        title = fake.random.choice(titles)
        skills = fake.random.choice(skill_pools)
        interests = fake.random.choice(interest_pools)

        volunteers_data.append(
            {
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
                "volunteer_status": status,
                "is_local": fake.boolean(chance_of_getting_true=75),
                "title": title,
                "industry": industry,
                "skills": skills,
                "interests": interests,
                "org_slug": org_slug,
            }
        )

    created_volunteers = []
    # Use local stats for detailed tracking, but update global stats for summary
    local_stats = {
        "emails": 0,
        "phones": 0,
        "skills": 0,
        "interests": 0,
        "availability": 0,
        "hours": 0,
    }

    if dry_run:
        for vol_data in volunteers_data:
            print(f"  [DRY RUN] Would create volunteer: {vol_data['first_name']} {vol_data['last_name']}")
            created_volunteers.append(vol_data)
        return created_volunteers

    with app.app_context():
        required_slugs = {vol["org_slug"] for vol in volunteers_data}
        org_lookup = {
            org.slug: org
            for org in Organization.query.filter(Organization.slug.in_(required_slugs)).all()
        }

        volunteer_emails = [vol["email"] for vol in volunteers_data if vol.get("email")]
        existing_email_map = {}
        if volunteer_emails:
            existing_records = (
                db.session.query(Volunteer, ContactEmail.email)
                .join(ContactEmail, ContactEmail.contact_id == Volunteer.id)
                .filter(
                    ContactEmail.email.in_(volunteer_emails),
                    Volunteer.contact_type == ContactType.VOLUNTEER,
                )
                .all()
            )
            for volunteer, email in existing_records:
                existing_email_map[email] = volunteer

        batch_size = 20
        pending_count = 0

        for vol_data in volunteers_data:
            email = vol_data.get("email")
            if email and email in existing_email_map:
                print(f"  ⏭️  Volunteer with email '{email}' already exists, skipping")
                created_volunteers.append(existing_email_map[email])
                continue

            org = org_lookup.get(vol_data["org_slug"])
            if not org:
                stats["errors"].append(
                    f"Volunteer {vol_data['first_name']}: Organization '{vol_data['org_slug']}' not found"
                )
                print(f"  ❌ Organization '{vol_data['org_slug']}' not found for volunteer {vol_data['first_name']}")
                continue

            try:
                sequence_index = len(created_volunteers)
                volunteer = Volunteer(
                    contact_type=ContactType.VOLUNTEER,
                    first_name=vol_data["first_name"],
                    last_name=vol_data["last_name"],
                    volunteer_status=vol_data["volunteer_status"],
                    is_local=vol_data["is_local"],
                    title=vol_data.get("title"),
                    industry=vol_data.get("industry"),
                    organization_id=org.id,
                    status=ContactStatus.ACTIVE,
                    first_volunteer_date=date.today() - timedelta(days=30 * (sequence_index + 1)),
                )

                db.session.add(volunteer)
                db.session.flush()

                if email:
                    db.session.add(
                        ContactEmail(
                            contact_id=volunteer.id,
                            email=email,
                            email_type=EmailType.PERSONAL,
                            is_primary=True,
                            is_verified=False,
                        )
                    )
                    local_stats["emails"] += 1

                if vol_data.get("phone"):
                    db.session.add(
                        ContactPhone(
                            contact_id=volunteer.id,
                            phone_number=vol_data["phone"],
                            phone_type=PhoneType.MOBILE,
                            is_primary=True,
                            can_text=True,
                        )
                    )
                    local_stats["phones"] += 1

                for skill_name in vol_data.get("skills", []):
                    db.session.add(
                        VolunteerSkill(
                            volunteer_id=volunteer.id,
                            skill_name=skill_name,
                            skill_category="General",
                            proficiency_level="Intermediate",
                            verified=False,
                        )
                    )
                    local_stats["skills"] += 1

                for interest_name in vol_data.get("interests", []):
                    db.session.add(
                        VolunteerInterest(
                            volunteer_id=volunteer.id,
                            interest_name=interest_name,
                            interest_category="General",
                        )
                    )
                    local_stats["interests"] += 1

                if vol_data["volunteer_status"] == VolunteerStatus.ACTIVE:
                    for day in [0, 2, 4]:
                        db.session.add(
                            VolunteerAvailability(
                                volunteer_id=volunteer.id,
                                day_of_week=day,
                                start_time=time(9, 0),
                                end_time=time(12, 0),
                                timezone="America/New_York",
                                is_recurring=True,
                                is_active=True,
                            )
                        )
                        local_stats["availability"] += 1

                    for i in range(3):
                        hours_date = date.today() - timedelta(days=7 * (i + 1))
                        db.session.add(
                            VolunteerHours(
                                volunteer_id=volunteer.id,
                                organization_id=org.id,
                                volunteer_date=hours_date,
                                hours_worked=4.0 + (i * 0.5),
                                activity_type="General Volunteering",
                                notes=f"Volunteer work on {hours_date}",
                            )
                        )
                        local_stats["hours"] += 1

                    volunteer.total_volunteer_hours = 12.0 + (len(created_volunteers) * 0.5)
                    volunteer.last_volunteer_date = date.today() - timedelta(days=7)

                created_volunteers.append(volunteer)
                if email:
                    existing_email_map[email] = volunteer
                stats["volunteers"] += 1
                pending_count += 1
                print(f"  ✅ Created volunteer: {vol_data['first_name']} {vol_data['last_name']}")
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                stats["errors"].append(f"Volunteer {vol_data['first_name']}: {exc}")
                print(f"  ❌ Error creating volunteer: {exc}")
                continue

            pending_count = _commit_batch(pending_count, batch_size)

        if pending_count:
            pending_count = _commit_batch(pending_count, 1)

    print(
        f"  📊 Created {stats['volunteers']} volunteers with "
        f"{local_stats['emails']} emails, {local_stats['phones']} phones, "
        f"{local_stats['skills']} skills, {local_stats['interests']} interests, "
        f"{local_stats['availability']} availability slots, and "
        f"{local_stats['hours']} hours records"
    )
    return created_volunteers


def seed_students(organizations, dry_run=False):
    """Create sample students"""
    print("\n📝 Seeding students...")

    students_data = [
        {
            "first_name": "Alex",
            "last_name": "Martinez",
            "email": "alex.m@gmail.com",
            "org_slug": "local-school",
        },
        {
            "first_name": "Jessica",
            "last_name": "Anderson",
            "email": "jessica.a@gmail.com",
            "org_slug": "local-school",
        },
        {
            "first_name": "Christopher",
            "last_name": "Thomas",
            "email": "chris.t@gmail.com",
            "org_slug": "local-school",
        },
        {
            "first_name": "Amanda",
            "last_name": "Jackson",
            "email": "amanda.j@gmail.com",
            "org_slug": "local-school",
        },
        {
            "first_name": "Daniel",
            "last_name": "White",
            "email": "daniel.w@gmail.com",
            "org_slug": "local-school",
        },
    ]

    created_students = []

    if dry_run:
        for student_data in students_data:
            print(f"  [DRY RUN] Would create student: {student_data['first_name']} {student_data['last_name']}")
            created_students.append(student_data)
        return created_students

    with app.app_context():
        required_slugs = {student["org_slug"] for student in students_data}
        org_lookup = {
            org.slug: org
            for org in Organization.query.filter(Organization.slug.in_(required_slugs)).all()
        }

        pending_count = 0

        for student_data in students_data:
            org = org_lookup.get(student_data["org_slug"])
            if not org:
                stats["errors"].append(
                    f"Student {student_data['first_name']}: Organization '{student_data['org_slug']}' not found"
                )
                print(f"  ❌ Organization '{student_data['org_slug']}' not found for student {student_data['first_name']}")
                continue

            try:
                student = Student(
                    contact_type=ContactType.STUDENT,
                    first_name=student_data["first_name"],
                    last_name=student_data["last_name"],
                    organization_id=org.id,
                    status=ContactStatus.ACTIVE,
                )

                db.session.add(student)
                db.session.flush()

                if student_data.get("email"):
                    db.session.add(
                        ContactEmail(
                            contact_id=student.id,
                            email=student_data["email"],
                            email_type=EmailType.PERSONAL,
                            is_primary=True,
                        )
                    )

                created_students.append(student)
                stats["students"] += 1
                pending_count += 1
                print(f"  ✅ Created student: {student_data['first_name']} {student_data['last_name']}")
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                stats["errors"].append(f"Student {student_data['first_name']}: {exc}")
                print(f"  ❌ Error creating student: {exc}")
                continue

            pending_count = _commit_batch(pending_count, len(students_data))

        if pending_count:
            pending_count = _commit_batch(pending_count, 1)

    return created_students


def seed_teachers(organizations, dry_run=False):
    """Create sample teachers"""
    print("\n📝 Seeding teachers...")

    teachers_data = [
        {
            "first_name": "Dr. Maria",
            "last_name": "Garcia",
            "email": "maria.g@gmail.com",
            "org_slug": "local-school",
        },
        {
            "first_name": "Prof. Richard",
            "last_name": "Lee",
            "email": "richard.l@gmail.com",
            "org_slug": "local-school",
        },
        {
            "first_name": "Ms. Jennifer",
            "last_name": "Harris",
            "email": "jennifer.h@gmail.com",
            "org_slug": "local-school",
        },
    ]

    created_teachers = []

    if dry_run:
        for teacher_data in teachers_data:
            print(f"  [DRY RUN] Would create teacher: {teacher_data['first_name']} {teacher_data['last_name']}")
            created_teachers.append(teacher_data)
        return created_teachers

    with app.app_context():
        required_slugs = {teacher["org_slug"] for teacher in teachers_data}
        org_lookup = {
            org.slug: org
            for org in Organization.query.filter(Organization.slug.in_(required_slugs)).all()
        }

        pending_count = 0

        for teacher_data in teachers_data:
            org = org_lookup.get(teacher_data["org_slug"])
            if not org:
                stats["errors"].append(
                    f"Teacher {teacher_data['first_name']}: Organization '{teacher_data['org_slug']}' not found"
                )
                print(f"  ❌ Organization '{teacher_data['org_slug']}' not found for teacher {teacher_data['first_name']}")
                continue

            try:
                teacher = Teacher(
                    contact_type=ContactType.TEACHER,
                    first_name=teacher_data["first_name"],
                    last_name=teacher_data["last_name"],
                    organization_id=org.id,
                    status=ContactStatus.ACTIVE,
                )

                db.session.add(teacher)
                db.session.flush()

                if teacher_data.get("email"):
                    db.session.add(
                        ContactEmail(
                            contact_id=teacher.id,
                            email=teacher_data["email"],
                            email_type=EmailType.WORK,
                            is_primary=True,
                        )
                    )

                created_teachers.append(teacher)
                stats["teachers"] += 1
                pending_count += 1
                print(f"  ✅ Created teacher: {teacher_data['first_name']} {teacher_data['last_name']}")
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                stats["errors"].append(f"Teacher {teacher_data['first_name']}: {exc}")
                print(f"  ❌ Error creating teacher: {exc}")
                continue

            pending_count = _commit_batch(pending_count, len(teachers_data))

        if pending_count:
            pending_count = _commit_batch(pending_count, 1)

    return created_teachers


def seed_events(organizations, users, volunteers, dry_run=False):
    """Create sample events with variety of types, statuses, formats, and dates"""
    print("\n📝 Seeding events...")

    from datetime import datetime, timedelta, timezone

    from flask_app.models.event.enums import CancellationReason

    now = datetime.now(timezone.utc)

    # Get first admin user for created_by_user_id
    admin_user = User.query.filter_by(is_super_admin=True).first() if not dry_run else None
    created_by_user_id = admin_user.id if admin_user else None

    events_data = [
        # Past completed events
        {
            "title": "Community Volunteer Training Workshop",
            "slug": "volunteer-training-workshop",
            "description": (
                "Comprehensive training session for new volunteers covering safety protocols, "
                "organization policies, and best practices."
            ),
            "event_type": EventType.TRAINING,
            "event_status": EventStatus.COMPLETED,
            "event_format": EventFormat.IN_PERSON,
            "start_date": now - timedelta(days=30),
            "duration": 180,  # 3 hours
            "location_name": "Community Center Main Hall",
            "location_address": "123 Main Street, Springfield, IL 62701",
            "capacity": 50,
            "cost": 0.00,
            "org_slug": "community-center",
            "volunteers": [
                {
                    "contact_index": 0,
                    "role": EventVolunteerRole.ORGANIZER,
                    "status": RegistrationStatus.CONFIRMED,
                    "attended": True,
                },
                {
                    "contact_index": 1,
                    "role": EventVolunteerRole.ATTENDEE,
                    "status": RegistrationStatus.CONFIRMED,
                    "attended": True,
                },
                {
                    "contact_index": 2,
                    "role": EventVolunteerRole.ATTENDEE,
                    "status": RegistrationStatus.CONFIRMED,
                    "attended": True,
                },
            ],
        },
        {
            "title": "Monthly Volunteer Meeting",
            "slug": "monthly-volunteer-meeting",
            "description": "Regular monthly meeting to discuss upcoming events and volunteer opportunities.",
            "event_type": EventType.MEETING,
            "event_status": EventStatus.COMPLETED,
            "event_format": EventFormat.VIRTUAL,
            "start_date": now - timedelta(days=14),
            "duration": 60,
            "virtual_link": "https://zoom.us/j/123456789",
            "capacity": 100,
            "org_slug": "local-school",
            "volunteers": [
                {
                    "contact_index": 0,
                    "role": EventVolunteerRole.ORGANIZER,
                    "status": RegistrationStatus.CONFIRMED,
                    "attended": True,
                },
            ],
        },
        {
            "title": "Spring Fundraiser Gala",
            "slug": "spring-fundraiser-gala",
            "description": "Annual fundraising event with dinner, entertainment, and silent auction.",
            "event_type": EventType.FUNDRAISER,
            "event_status": EventStatus.COMPLETED,
            "event_format": EventFormat.IN_PERSON,
            "start_date": now - timedelta(days=60),
            "duration": 240,  # 4 hours
            "location_name": "Grand Ballroom",
            "location_address": "456 Education Avenue, Springfield, IL 62702",
            "capacity": 200,
            "cost": 75.00,
            "org_slug": "nonprofit-org",
            "volunteers": [
                {
                    "contact_index": 3,
                    "role": EventVolunteerRole.ORGANIZER,
                    "status": RegistrationStatus.CONFIRMED,
                    "attended": True,
                },
                {
                    "contact_index": 4,
                    "role": EventVolunteerRole.STAFF,
                    "status": RegistrationStatus.CONFIRMED,
                    "attended": True,
                },
            ],
        },
        # Upcoming confirmed events
        {
            "title": "Summer Volunteer Orientation",
            "slug": "summer-volunteer-orientation",
            "description": (
                "Orientation session for summer volunteer program. "
                "Learn about available opportunities and requirements."
            ),
            "event_type": EventType.WORKSHOP,
            "event_status": EventStatus.CONFIRMED,
            "event_format": EventFormat.HYBRID,
            "start_date": now + timedelta(days=14),
            "duration": 120,
            "registration_deadline": now + timedelta(days=10),
            "location_name": "Community Center Conference Room",
            "location_address": "123 Main Street, Springfield, IL 62701",
            "virtual_link": "https://zoom.us/j/987654321",
            "capacity": 40,
            "cost": 0.00,
            "org_slug": "community-center",
            "volunteers": [
                {"contact_index": 0, "role": EventVolunteerRole.ORGANIZER, "status": RegistrationStatus.CONFIRMED},
                {"contact_index": 1, "role": EventVolunteerRole.ATTENDEE, "status": RegistrationStatus.CONFIRMED},
                {"contact_index": 2, "role": EventVolunteerRole.ATTENDEE, "status": RegistrationStatus.PENDING},
            ],
        },
        {
            "title": "Tech Skills Workshop for Students",
            "slug": "tech-skills-workshop",
            "description": (
                "Hands-on workshop teaching basic programming and web development skills " "to high school students."
            ),
            "event_type": EventType.WORKSHOP,
            "event_status": EventStatus.CONFIRMED,
            "event_format": EventFormat.IN_PERSON,
            "start_date": now + timedelta(days=21),
            "duration": 180,
            "registration_deadline": now + timedelta(days=18),
            "location_name": "Local School Computer Lab",
            "location_address": "456 Education Avenue, Springfield, IL 62702",
            "capacity": 25,
            "cost": 0.00,
            "org_slug": "local-school",
            "volunteers": [
                {"contact_index": 0, "role": EventVolunteerRole.SPEAKER, "status": RegistrationStatus.CONFIRMED},
                {"contact_index": 1, "role": EventVolunteerRole.VOLUNTEER, "status": RegistrationStatus.CONFIRMED},
            ],
        },
        {
            "title": "Community Health Fair",
            "slug": "community-health-fair",
            "description": "Free health screenings, wellness information, and community resources.",
            "event_type": EventType.COMMUNITY_EVENT,
            "event_status": EventStatus.CONFIRMED,
            "event_format": EventFormat.IN_PERSON,
            "start_date": now + timedelta(days=35),
            "duration": 300,  # 5 hours
            "registration_deadline": now + timedelta(days=30),
            "location_name": "Community Park",
            "location_address": "789 Charity Boulevard, Springfield, IL 62703",
            "capacity": 500,
            "cost": 0.00,
            "org_slug": "nonprofit-org",
            "volunteers": [
                {"contact_index": 3, "role": EventVolunteerRole.ORGANIZER, "status": RegistrationStatus.CONFIRMED},
                {"contact_index": 4, "role": EventVolunteerRole.VOLUNTEER, "status": RegistrationStatus.CONFIRMED},
            ],
        },
        # Today's events
        {
            "title": "Volunteer Appreciation Lunch",
            "slug": "volunteer-appreciation-lunch",
            "description": "Thank you lunch for all our dedicated volunteers.",
            "event_type": EventType.COMMUNITY_EVENT,
            "event_status": EventStatus.CONFIRMED,
            "event_format": EventFormat.IN_PERSON,
            "start_date": now.replace(hour=12, minute=0, second=0, microsecond=0),
            "duration": 90,
            "location_name": "Community Center Dining Hall",
            "location_address": "123 Main Street, Springfield, IL 62701",
            "capacity": 80,
            "cost": 0.00,
            "org_slug": "community-center",
            "volunteers": [
                {"contact_index": 0, "role": EventVolunteerRole.ATTENDEE, "status": RegistrationStatus.CONFIRMED},
                {"contact_index": 1, "role": EventVolunteerRole.ATTENDEE, "status": RegistrationStatus.CONFIRMED},
            ],
        },
        # Draft events
        {
            "title": "Fall Festival Planning Meeting",
            "slug": "fall-festival-planning",
            "description": "Initial planning meeting for the annual fall festival.",
            "event_type": EventType.MEETING,
            "event_status": EventStatus.DRAFT,
            "event_format": EventFormat.VIRTUAL,
            "start_date": now + timedelta(days=45),
            "duration": 60,
            "virtual_link": "https://zoom.us/j/555555555",
            "capacity": 20,
            "org_slug": "community-center",
        },
        {
            "title": "Winter Holiday Fundraiser",
            "slug": "winter-holiday-fundraiser",
            "description": "Holiday-themed fundraiser with crafts, food, and entertainment.",
            "event_type": EventType.FUNDRAISER,
            "event_status": EventStatus.DRAFT,
            "event_format": EventFormat.IN_PERSON,
            "start_date": now + timedelta(days=90),
            "duration": 240,
            "location_name": "Community Center Main Hall",
            "location_address": "123 Main Street, Springfield, IL 62701",
            "capacity": 150,
            "cost": 25.00,
            "org_slug": "nonprofit-org",
        },
        # Requested events
        {
            "title": "Parent-Teacher Conference Support",
            "slug": "parent-teacher-conference-support",
            "description": "Volunteers needed to help with setup and logistics for parent-teacher conferences.",
            "event_type": EventType.OTHER,
            "event_status": EventStatus.REQUESTED,
            "event_format": EventFormat.IN_PERSON,
            "start_date": now + timedelta(days=28),
            "duration": 120,
            "location_name": "Local School",
            "location_address": "456 Education Avenue, Springfield, IL 62702",
            "capacity": 15,
            "org_slug": "local-school",
        },
        # Cancelled events
        {
            "title": "Outdoor Community Picnic",
            "slug": "outdoor-community-picnic",
            "description": "Cancelled due to weather. Rescheduled for next month.",
            "event_type": EventType.COMMUNITY_EVENT,
            "event_status": EventStatus.CANCELLED,
            "event_format": EventFormat.IN_PERSON,
            "start_date": now - timedelta(days=7),
            "duration": 180,
            "location_name": "Community Park",
            "location_address": "789 Charity Boulevard, Springfield, IL 62703",
            "capacity": 100,
            "cancellation_reason": CancellationReason.WEATHER,
            "org_slug": "nonprofit-org",
        },
        {
            "title": "Evening Volunteer Training",
            "slug": "evening-volunteer-training",
            "description": "Cancelled due to low registration.",
            "event_type": EventType.TRAINING,
            "event_status": EventStatus.CANCELLED,
            "event_format": EventFormat.VIRTUAL,
            "start_date": now - timedelta(days=3),
            "duration": 90,
            "virtual_link": "https://zoom.us/j/111111111",
            "capacity": 30,
            "cancellation_reason": CancellationReason.LOW_ATTENDANCE,
            "org_slug": "community-center",
        },
    ]

    created_events = []

    if dry_run:
        for event_data in events_data:
            print(f"  [DRY RUN] Would create event: {event_data['title']}")
            created_events.append(event_data)
        return created_events

    with app.app_context():
        required_slugs = {event["org_slug"] for event in events_data}
        org_lookup = {
            org.slug: org
            for org in Organization.query.filter(Organization.slug.in_(required_slugs)).all()
        }

        from flask_app.models import Contact
        from sqlalchemy import inspect as sqlalchemy_inspect

        batch_size = 5
        pending_count = 0

        for event_data in events_data:
            existing = Event.query.filter_by(slug=event_data["slug"]).first()
            if existing:
                print(f"  ⏭️  Event '{event_data['title']}' already exists, skipping")
                created_events.append(existing)
                continue

            org = org_lookup.get(event_data["org_slug"])
            if not org:
                stats["errors"].append(f"Event {event_data['title']}: Organization '{event_data['org_slug']}' not found")
                print(f"  ❌ Organization '{event_data['org_slug']}' not found for event {event_data['title']}")
                continue

            try:
                event = Event(
                    title=event_data["title"],
                    slug=event_data["slug"],
                    description=event_data.get("description"),
                    event_type=event_data["event_type"],
                    event_status=event_data["event_status"],
                    event_format=event_data["event_format"],
                    cancellation_reason=event_data.get("cancellation_reason"),
                    start_date=event_data["start_date"],
                    start_time=event_data.get("start_time"),
                    duration=event_data.get("duration"),
                    location_name=event_data.get("location_name"),
                    location_address=event_data.get("location_address"),
                    virtual_link=event_data.get("virtual_link"),
                    capacity=event_data.get("capacity"),
                    registration_deadline=event_data.get("registration_deadline"),
                    cost=event_data.get("cost"),
                    created_by_user_id=created_by_user_id,
                )

                if event.duration and event.start_date:
                    event.end_date = event.start_date + timedelta(minutes=event.duration)

                db.session.add(event)
                db.session.flush()

                db.session.add(
                    EventOrganization(
                        event_id=event.id,
                        organization_id=org.id,
                        is_primary=True,
                    )
                )

                volunteer_data_list = event_data.get("volunteers", [])
                if volunteer_data_list:
                    contact_ids = []
                    for vol_data in volunteer_data_list:
                        contact_index = vol_data.get("contact_index")
                        if contact_index is None or contact_index >= len(volunteers):
                            continue

                        volunteer = volunteers[contact_index]
                        if isinstance(volunteer, dict):
                            continue

                        try:
                            insp = sqlalchemy_inspect(volunteer)
                            if insp.persistent or insp.pending:
                                contact_ids.append((volunteer.id, vol_data))
                            elif insp.detached and insp.identity:
                                contact_ids.append((insp.identity[0], vol_data))
                        except Exception:
                            continue

                    if contact_ids:
                        ids_only = [cid[0] for cid in contact_ids]
                        contacts = Contact.query.filter(Contact.id.in_(ids_only)).all()
                        contact_dict = {c.id: c for c in contacts}

                        for contact_id, vol_data in contact_ids:
                            if contact_id in contact_dict:
                                db.session.add(
                                    EventVolunteer(
                                        event_id=event.id,
                                        contact_id=contact_id,
                                        role=vol_data.get("role", EventVolunteerRole.ATTENDEE),
                                        registration_status=vol_data.get(
                                            "status", RegistrationStatus.PENDING
                                        ),
                                        attended=vol_data.get("attended"),
                                    )
                                )

                created_events.append(event)
                stats["events"] += 1
                pending_count += 1
                print(f"  ✅ Created event: {event_data['title']} ({event_data['event_status'].value})")
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                stats["errors"].append(f"Event {event_data['title']}: {exc}")
                print(f"  ❌ Error creating event: {exc}")
                continue

            pending_count = _commit_batch(pending_count, batch_size)

        if pending_count:
            pending_count = _commit_batch(pending_count, 1)

    return created_events


def seed_contact_relationships(contacts, organizations, dry_run=False):
    """Link contacts to organizations and add roles"""
    print("\n📝 Seeding contact relationships...")

    if dry_run:
        print(f"  [DRY RUN] Would create relationships for {len(contacts)} contacts")
        return

    with app.app_context():
        # Query all contacts within session context to avoid detached instance errors
        from sqlalchemy import inspect as sqlalchemy_inspect

        from flask_app.models import Contact

        # Get contact IDs from the passed contacts (they might be detached)
        contact_ids = []
        for contact in contacts:
            # Check if it's a dict first
            if isinstance(contact, dict):
                if "id" in contact:
                    contact_ids.append(contact["id"])
            else:
                # For SQLAlchemy objects, use inspect to check state and get ID safely
                try:
                    insp = sqlalchemy_inspect(contact)
                    # If object is persistent or pending, we can access id
                    if insp.persistent or insp.pending:
                        contact_ids.append(contact.id)
                    elif insp.detached:
                        # For detached objects, try to get ID from identity
                        if insp.identity:
                            contact_ids.append(insp.identity[0])
                except Exception:
                    # Skip if we can't get the ID
                    pass

        if not contact_ids:
            print("  ⏭️  No contacts to create relationships for")
            return

        # Query contacts within session context
        all_contacts = Contact.query.filter(Contact.id.in_(contact_ids)).all()

        for contact in all_contacts:
            if not contact.organization_id:
                continue

            # Create ContactOrganization link if it doesn't exist
            existing_link = ContactOrganization.query.filter_by(
                contact_id=contact.id, organization_id=contact.organization_id
            ).first()

            if not existing_link:
                contact_org = ContactOrganization(
                    contact_id=contact.id,
                    organization_id=contact.organization_id,
                    is_primary=True,
                    start_date=date.today(),
                )
                db.session.add(contact_org)

            # Add ContactRole based on contact type
            role_type_map = {
                ContactType.VOLUNTEER: RoleType.VOLUNTEER,
                ContactType.STUDENT: RoleType.STUDENT,
                ContactType.TEACHER: RoleType.TEACHER,
            }

            role_type = role_type_map.get(contact.contact_type)
            if role_type:
                existing_role = ContactRole.query.filter_by(
                    contact_id=contact.id, role_type=role_type, is_active=True
                ).first()

                if not existing_role:
                    contact_role = ContactRole(
                        contact_id=contact.id,
                        role_type=role_type,
                        start_date=date.today(),
                        is_active=True,
                    )
                    db.session.add(contact_role)

        try:
            db.session.commit()
            print(f"  ✅ Created contact relationships for {len(all_contacts)} contacts")
        except Exception as e:
            db.session.rollback()
            stats["errors"].append(f"Contact relationships: {str(e)}")
            print(f"  ❌ Error creating contact relationships: {str(e)}")


def seed_database(
    clear=False,
    admin_username="admin",
    admin_email="admin@gmail.com",
    admin_password=None,
    dry_run=False,
):
    """Main function to seed the database"""
    print("=" * 60)
    print("Database Seeding Script")
    print("=" * 60)

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made to the database\n")

    with app.app_context():
        # Check if init_database has been run
        roles = Role.query.filter_by(is_system_role=True).all()
        if not roles:
            print("❌ Error: Database not initialized. Please run 'python scripts/init_database.py' first.")
            sys.exit(1)

        # Get roles dictionary
        roles_dict = {role.name: role for role in roles}

        if clear:
            clear_database()

        # Seed data
        seed_admin_user(admin_username, admin_email, admin_password, dry_run)
        organizations = seed_organizations(dry_run)
        users = seed_users(organizations, roles_dict, dry_run)
        volunteers = seed_volunteers(organizations, dry_run)
        students = seed_students(organizations, dry_run)
        teachers = seed_teachers(organizations, dry_run)

        # Combine all contacts for relationships
        all_contacts = volunteers + students + teachers
        seed_contact_relationships(all_contacts, organizations, dry_run)

        # Seed events (needs organizations, users, and volunteers)
        seed_events(organizations, users, volunteers, dry_run)

        # Print summary
        print("\n" + "=" * 60)
        print("Seeding Summary")
        print("=" * 60)
        print(f"Admin Users: {stats['admin_users']}")
        print(f"Organizations: {stats['organizations']}")
        print(f"Users: {stats['users']}")
        print(f"Volunteers: {stats['volunteers']}")
        print(f"Students: {stats['students']}")
        print(f"Teachers: {stats['teachers']}")
        print(f"Events: {stats['events']}")

        if stats["errors"]:
            print(f"\n⚠️  Errors encountered: {len(stats['errors'])}")
            for error in stats["errors"][:10]:  # Show first 10 errors
                print(f"  - {error}")
            if len(stats["errors"]) > 10:
                print(f"  ... and {len(stats['errors']) - 10} more errors")
        else:
            print("\n✅ Seeding completed successfully!")

        if not dry_run:
            print("\nDefault credentials:")
            print(f"  Admin: {admin_username} / {admin_password or 'admin'}")
            print("  Regular users: username / password123")


def main():
    """Command-line interface"""
    parser = argparse.ArgumentParser(description="Seed the database with sample data")
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing data before seeding",
    )
    parser.add_argument(
        "--admin-username",
        default="admin",
        help="Admin username (default: admin)",
    )
    parser.add_argument(
        "--admin-email",
        default="admin@gmail.com",
        help="Admin email (default: admin@gmail.com)",
    )
    parser.add_argument(
        "--admin-password",
        help="Admin password (default: admin, will prompt if not provided)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without actually creating",
    )

    args = parser.parse_args()

    admin_password = args.admin_password
    if not admin_password and not args.dry_run:
        admin_password = getpass("Enter admin password (or press Enter for 'admin'): ")
        if not admin_password:
            admin_password = "admin"

    seed_database(
        clear=args.clear,
        admin_username=args.admin_username,
        admin_email=args.admin_email,
        admin_password=admin_password,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
