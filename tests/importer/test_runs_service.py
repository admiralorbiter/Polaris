from __future__ import annotations

import pytest
from sqlalchemy.exc import NoResultFound

from flask_app.importer.pipeline.run_service import ImportRunService, RunFilters
from flask_app.models.importer.schema import ImportRunStatus


def test_run_filters_defaults():
    filters = RunFilters.coerce()
    assert filters.page == 1
    assert filters.page_size == 25
    assert filters.sort == "-started_at"
    assert filters.statuses == ()
    assert filters.sources == ()
    assert filters.include_dry_runs is True


def test_run_filters_invalid_status():
    with pytest.raises(ValueError):
        RunFilters.coerce(statuses=["bogus"])


def test_run_filters_invalid_sort():
    with pytest.raises(ValueError):
        RunFilters.coerce(sort="duration")


def test_list_runs_basic(importer_app, run_factory):
    run_factory(source="csv", status=ImportRunStatus.SUCCEEDED, started_offset_minutes=10)
    run_factory(source="csv", status=ImportRunStatus.FAILED, started_offset_minutes=5)
    run_factory(source="crm", status=ImportRunStatus.RUNNING, started_offset_minutes=2)

    service = ImportRunService()
    filters = RunFilters.coerce()
    result = service.list_runs(filters)

    assert result.total == 3
    assert result.page == 1
    assert result.total_pages == 1
    assert result.items[0].source == "crm"
    assert result.items[0].status == ImportRunStatus.RUNNING.value


def test_list_runs_filters_and_stats(importer_app, run_factory):
    run_factory(source="csv", status=ImportRunStatus.SUCCEEDED, started_offset_minutes=30, dry_run=True)
    run_factory(source="crm", status=ImportRunStatus.FAILED, started_offset_minutes=20)
    run_factory(source="crm", status=ImportRunStatus.SUCCEEDED, started_offset_minutes=10)

    service = ImportRunService()
    filters = RunFilters.coerce(sources=["crm"])
    result = service.list_runs(filters)
    assert result.total == 2
    assert all(item.source == "crm" for item in result.items)

    stats = service.get_stats(filters)
    assert stats.total == 2
    assert stats.statuses[ImportRunStatus.SUCCEEDED.value] == 1
    assert stats.statuses[ImportRunStatus.FAILED.value] == 1
    assert stats.sources["crm"] == 2
    assert stats.dry_runs.get("true", 0) == 0
    assert stats.dry_runs.get("false", 0) == 2


def test_list_runs_exclude_dry_runs(importer_app, run_factory):
    run_factory(source="csv", status=ImportRunStatus.SUCCEEDED, dry_run=True)
    run_factory(source="csv", status=ImportRunStatus.SUCCEEDED, dry_run=False)

    service = ImportRunService()
    filters = RunFilters.coerce(include_dry_runs="0")
    result = service.list_runs(filters)
    assert result.total == 1
    assert all(not item.dry_run for item in result.items)

    stats = service.get_stats(filters)
    assert stats.dry_runs.get("true", 0) == 0
    assert stats.dry_runs.get("false", 0) == 1


def test_get_run_not_found(importer_app):
    service = ImportRunService()
    with pytest.raises(NoResultFound):
        service.get_run(9999)


def test_list_sources(importer_app, run_factory):
    run_factory(source="csv")
    run_factory(source="crm")
    service = ImportRunService()
    sources = service.list_sources()
    assert set(sources) == {"csv", "crm"}

