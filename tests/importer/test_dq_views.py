from __future__ import annotations

from flask_app.models import db
from flask_app.models.importer.schema import DataQualitySeverity, DataQualityStatus


def _login_super_admin(app, client):
    from werkzeug.security import generate_password_hash
    from flask_app.models import User

    with app.app_context():
        user = User(
            username="admin",
            email="admin@example.com",
            password_hash=generate_password_hash("adminpass123"),
            is_super_admin=True,
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
    response = client.post("/login", data={"username": "admin", "password": "adminpass123"})
    assert response.status_code in (200, 302)


def test_dq_list_requires_auth(importer_app, client):
    response = client.get("/importer/violations")
    assert response.status_code == 401


def test_dq_list_success(importer_app, client, violation_factory):
    violation_factory(rule_code="VOL_EMAIL_INVALID", severity=DataQualitySeverity.ERROR, status=DataQualityStatus.OPEN)
    _login_super_admin(importer_app, client)
    response = client.get("/importer/violations")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    assert data["violations"][0]["rule_code"] == "VOL_EMAIL_INVALID"


def test_dq_detail(importer_app, client, violation_factory):
    violation = violation_factory(rule_code="VOL_EMAIL_INVALID")
    _login_super_admin(importer_app, client)
    response = client.get(f"/importer/violations/{violation.id}")
    assert response.status_code == 200
    detail = response.get_json()
    assert detail["id"] == violation.id
    assert detail["rule_code"] == "VOL_EMAIL_INVALID"


def test_dq_export(importer_app, client, violation_factory):
    violation = violation_factory()
    violation.staging_row.payload_json = {
        **violation.staging_row.payload_json,
        "email": '=HYPERLINK("http://evil")',
    }
    db.session.commit()
    _login_super_admin(importer_app, client)
    response = client.get("/importer/violations/export")
    assert response.status_code == 200
    assert response.data.startswith(b"violation_id,run_id")
    assert b"'=HYPERLINK" in response.data


def test_dq_rule_codes_endpoint(importer_app, client, violation_factory):
    violation_factory(rule_code="VOL_CONTACT_REQUIRED")
    _login_super_admin(importer_app, client)
    response = client.get("/importer/violations/rule_codes")
    assert response.status_code == 200
    payload = response.get_json()
    assert "VOL_CONTACT_REQUIRED" in payload["rule_codes"]

