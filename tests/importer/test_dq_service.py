from __future__ import annotations

from flask_app.importer.pipeline.dq_service import DataQualityViolationService, ViolationFilters
from flask_app.models import db
from flask_app.models.importer.schema import DataQualitySeverity, DataQualityStatus


def test_violation_list_filters(importer_app, violation_factory):
    violation_factory(rule_code="VOL_EMAIL_INVALID", severity=DataQualitySeverity.ERROR, status=DataQualityStatus.OPEN)
    violation_factory(rule_code="VOL_PHONE_INVALID", severity=DataQualitySeverity.WARNING, status=DataQualityStatus.OPEN)

    service = DataQualityViolationService()
    filters = ViolationFilters.coerce(rule_codes=["VOL_EMAIL_INVALID"])
    result = service.list_violations(filters)

    assert result.total == 1
    assert result.items[0].rule_code == "VOL_EMAIL_INVALID"


def test_violation_stats(importer_app, violation_factory):
    violation_factory(rule_code="VOL_EMAIL_INVALID", severity=DataQualitySeverity.ERROR)
    violation_factory(rule_code="VOL_EMAIL_INVALID", severity=DataQualitySeverity.ERROR)
    violation_factory(rule_code="VOL_PHONE_INVALID", severity=DataQualitySeverity.WARNING)

    service = DataQualityViolationService()
    filters = ViolationFilters.coerce()
    stats = service.get_stats(filters)

    assert stats.total == 3
    assert stats.by_rule_code["VOL_EMAIL_INVALID"] == 2
    assert stats.by_severity[DataQualitySeverity.ERROR.value] == 2


def test_violation_export_sanitizes_csv(importer_app, violation_factory):
    violation = violation_factory()
    violation.staging_row.payload_json = {
        **violation.staging_row.payload_json,
        "email": '=HYPERLINK("http://evil")',
    }
    violation.details_json = {"formula": "+SUM(1,2)"}
    db.session.commit()
    service = DataQualityViolationService()
    filters = ViolationFilters.coerce()

    filename, csv_content = service.export_csv(filters, limit=10)
    assert filename.startswith("dq_violations_export_")
    assert "\n" in csv_content
    assert "'=HYPERLINK" in csv_content
    assert "'+SUM" in csv_content

