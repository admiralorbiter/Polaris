"""CSV adapter for volunteer ingest (IMP-10).

Responsible for validating CSV headers against the canonical volunteer
contract, streaming rows, and applying lightweight normalization so downstream
pipeline steps can persist data into staging tables.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import IO, Iterator, Sequence

from flask_app.importer.contracts import (
    FieldSpec,
    get_volunteer_alias_map,
    get_volunteer_field_specs,
    get_volunteer_required_headers,
    normalize_header,
)


class CSVAdapterError(Exception):
    """Base exception for CSV adapter failures."""


class CSVHeaderError(CSVAdapterError):
    """Raised when the CSV header row does not meet contract requirements."""

    def __init__(
        self,
        *,
        missing: Sequence[str] | None = None,
        unexpected: Sequence[str] | None = None,
        duplicates: Sequence[str] | None = None,
    ) -> None:
        details: list[str] = []
        if missing:
            details.append(f"Missing required columns: {', '.join(sorted(missing))}.")
        if unexpected:
            details.append(
                "Unexpected columns present: " + ", ".join(sorted(unexpected)) + ". Remove or map them before ingest."
            )
        if duplicates:
            details.append(
                "Duplicate canonical columns detected: "
                + ", ".join(sorted(duplicates))
                + ". Ensure each canonical field appears only once."
            )

        message = "CSV header validation failed. " + " ".join(details) if details else "CSV header validation failed."
        super().__init__(message)
        self.missing = tuple(missing or ())
        self.unexpected = tuple(unexpected or ())
        self.duplicates = tuple(duplicates or ())


class CSVRowError(CSVAdapterError):
    """Raised when an individual row cannot be parsed."""

    def __init__(self, row_number: int, message: str) -> None:
        super().__init__(f"Row {row_number}: {message}")
        self.row_number = row_number


@dataclass(frozen=True)
class HeaderValidationResult:
    raw_headers: tuple[str, ...]
    canonical_headers: tuple[str, ...]


@dataclass(frozen=True)
class VolunteerCSVRow:
    """Represents a parsed CSV row with canonical payloads."""

    sequence_number: int
    source_line: int
    raw: dict[str, object | None]
    normalized: dict[str, object | None]


@dataclass
class VolunteerCSVStatistics:
    """Accumulated statistics from CSV parsing."""

    rows_processed: int = 0
    rows_skipped_blank: int = 0


def _sanitize_header(header: str | None) -> str:
    token = (header or "").strip()
    return token.lstrip("\ufeff")


def _validate_headers(raw_headers: Sequence[str]) -> HeaderValidationResult:
    sanitized_headers = tuple(_sanitize_header(header) for header in raw_headers)
    alias_map = get_volunteer_alias_map()
    required_headers = set(get_volunteer_required_headers())
    duplicates: list[str] = []
    unexpected: list[str] = []
    seen: set[str] = set()
    header_pairs: list[tuple[str, str | None]] = []

    for header in sanitized_headers:
        normalized_header = normalize_header(header)
        canonical = alias_map.get(normalized_header)
        if canonical is None:
            header_pairs.append((header, None))
            unexpected.append(header)
            continue
        if canonical in seen:
            duplicates.append(canonical)
        else:
            seen.add(canonical)
        header_pairs.append((header, canonical))

    missing = sorted(required_headers - seen)
    if missing or unexpected or duplicates:
        raise CSVHeaderError(missing=missing, unexpected=unexpected, duplicates=duplicates)

    canonical_headers = tuple(canonical for _, canonical in header_pairs if canonical is not None)
    return HeaderValidationResult(raw_headers=sanitized_headers, canonical_headers=canonical_headers)


def _row_is_blank(row: dict[str, object | None]) -> bool:
    return all((value is None or (isinstance(value, str) and value.strip() == "")) for value in row.values())


class VolunteerCSVAdapter:
    """CSV reader that enforces the volunteer ingest contract."""

    def __init__(self, file_obj: IO[str], *, source_system: str = "csv", skip_blank_rows: bool = True) -> None:
        self._file_obj = file_obj
        self.source_system = source_system
        self.skip_blank_rows = skip_blank_rows
        self._header_result: HeaderValidationResult | None = None
        self.statistics = VolunteerCSVStatistics()
        self._field_specs = {spec.name: spec for spec in get_volunteer_field_specs()}

    @property
    def header(self) -> HeaderValidationResult | None:
        return self._header_result

    def _prepare_reader(self) -> csv.DictReader:
        self._file_obj.seek(0)
        reader = csv.DictReader(self._file_obj)
        if reader.fieldnames is None:
            raise CSVHeaderError(missing=get_volunteer_required_headers())

        header_result = _validate_headers(reader.fieldnames)
        reader.fieldnames = list(header_result.canonical_headers)
        self._header_result = header_result
        return reader

    def iter_rows(self) -> Iterator[VolunteerCSVRow]:
        reader = self._prepare_reader()
        for sequence_number, raw_row in enumerate(reader, start=1):
            row_copy = {key: value for key, value in raw_row.items()}

            if self.skip_blank_rows and _row_is_blank(row_copy):
                self.statistics.rows_skipped_blank += 1
                continue

            normalized = self._apply_normalizers(row_copy)
            self.statistics.rows_processed += 1

            yield VolunteerCSVRow(
                sequence_number=sequence_number,
                source_line=reader.line_num,
                raw=row_copy,
                normalized=normalized,
            )

    def _apply_normalizers(self, row: dict[str, object | None]) -> dict[str, object | None]:
        normalized: dict[str, object | None] = {}
        for key, value in row.items():
            spec: FieldSpec | None = self._field_specs.get(key)
            if spec is None or spec.normalizer is None:
                normalized[key] = value
            else:
                normalized[key] = spec.normalizer(value)
        return normalized
