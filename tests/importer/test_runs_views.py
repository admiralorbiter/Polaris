from __future__ import annotations

from werkzeug.security import generate_password_hash

from flask_app.models import AdminLog, User, db
from flask_app.models.importer.schema import ImportRunStatus


def _login_super_admin(app, client):
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


def test_runs_list_requires_authentication(importer_app, client):
    response = client.get("/importer/runs")
    assert response.status_code == 401


def test_runs_list_success(importer_app, client, run_factory):
    run_factory(source="csv", status=ImportRunStatus.SUCCEEDED)
    run_factory(source="crm", status=ImportRunStatus.FAILED)

    _login_super_admin(importer_app, client)
    response = client.get("/importer/runs")
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["total"] == 2
    assert len(payload["runs"]) == 2

    audit_entries = AdminLog.query.filter_by(action="IMPORT_RUN_VIEW").all()
    assert audit_entries


def test_run_detail(importer_app, client, run_factory):
    run = run_factory(source="crm", status=ImportRunStatus.FAILED)
    _login_super_admin(importer_app, client)
    response = client.get(f"/importer/runs/{run.id}")
    assert response.status_code == 200
    detail = response.get_json()
    assert detail["run_id"] == run.id
    assert detail["counts_json"]["core"]["volunteers"]["rows_inserted"] == 45


def test_run_stats(importer_app, client, run_factory):
    run_factory(source="csv", status=ImportRunStatus.SUCCEEDED)
    run_factory(source="crm", status=ImportRunStatus.FAILED)
    _login_super_admin(importer_app, client)
    response = client.get("/importer/runs/stats")
    assert response.status_code == 200
    stats = response.get_json()
    assert stats["total"] == 2
    assert stats["by_status"][ImportRunStatus.SUCCEEDED.value] == 1


def test_run_download(importer_app, client, run_factory):
    run = run_factory(source="csv", status=ImportRunStatus.SUCCEEDED, keep_file=True)
    with importer_app.app_context():
        persisted = db.session.get(type(run), run.id)
        assert persisted and persisted.ingest_params_json
        assert persisted.ingest_params_json.get("file_path")
    _login_super_admin(importer_app, client)
    response = client.get(f"/admin/imports/{run.id}/download")
    assert response.status_code == 200, response.get_json()
    assert response.data.startswith(b"id,name")


def test_admin_nav_shows_importer_runs(importer_app, client):
    _login_super_admin(importer_app, client)
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "/admin/imports/runs/dashboard" in html
    assert "Importer Runs" in html
    assert "/admin/imports/violations" in html
    assert "DQ Inbox" in html


def test_admin_nav_hides_importer_runs_when_disabled(app, client):
    _login_super_admin(app, client)
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "/admin/imports/runs/dashboard" not in html

