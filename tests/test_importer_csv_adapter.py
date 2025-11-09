import io

import pytest

from flask_app.importer.adapters.csv_volunteers import CSVHeaderError, VolunteerCSVAdapter


def _make_csv(contents: str) -> io.StringIO:
    stream = io.StringIO(contents)
    stream.seek(0)
    return stream


def test_adapter_accepts_alias_headers_and_normalizes():
    csv_stream = _make_csv("First Name,Last Name,Email,Phone\n" "  Alice  ,Smith ,ALICE@example.org,+1 415 555 0101 \n")

    adapter = VolunteerCSVAdapter(csv_stream)
    rows = list(adapter.iter_rows())

    assert adapter.header is not None
    assert adapter.header.canonical_headers == ("first_name", "last_name", "email", "phone")
    assert len(rows) == 1
    row = rows[0]
    assert row.raw["first_name"] == "  Alice  "
    assert row.normalized["first_name"] == "Alice"
    assert row.normalized["email"] == "ALICE@example.org"
    assert adapter.statistics.rows_processed == 1


def test_adapter_rejects_missing_required_headers():
    csv_stream = _make_csv("last_name,email\n" "Doe,jane@example.org\n")
    adapter = VolunteerCSVAdapter(csv_stream)

    with pytest.raises(CSVHeaderError) as excinfo:
        list(adapter.iter_rows())

    error = excinfo.value
    assert "Missing required columns" in str(error)
    assert "first_name" in error.missing


def test_adapter_skips_blank_rows_and_tracks_statistics():
    csv_stream = _make_csv(
        "first_name,last_name,email\n" "Jane,Doe,jane@example.org\n" ",,\n" "John,Smith,john@example.org\n"
    )

    adapter = VolunteerCSVAdapter(csv_stream)
    rows = list(adapter.iter_rows())

    assert len(rows) == 2
    assert rows[0].sequence_number == 1
    assert rows[1].sequence_number == 3  # Blank row still increments the sequence counter.
    assert adapter.statistics.rows_processed == 2
    assert adapter.statistics.rows_skipped_blank == 1
