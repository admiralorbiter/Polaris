"""
Helpers for idempotent loader decisions backed by external_id_map.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from flask_app.models import ExternalIdMap, Volunteer

ENTITY_TYPE_VOLUNTEER = "volunteer"


class MissingExternalIdentifier(ValueError):
    """Raised when a payload cannot be resolved due to missing identifiers."""

    def __init__(self, external_system: str) -> None:
        super().__init__(
            f"No external identifier supplied for system '{external_system}'. "
            "Idempotent upsert requires external_id."
        )
        self.external_system = external_system


@dataclass(frozen=True)
class ImportTarget:
    """
    Resolution outcome for an incoming payload.

    `action` values:
    - ``create``: no prior mapping exists; loader should insert a new volunteer.
    - ``update``: active mapping found; loader should update the existing volunteer.
    - ``reactivate``: mapping existed but was soft-deleted; loader should reactivate and update.
    """

    action: Literal["create", "update", "reactivate"]
    id_map: ExternalIdMap | None
    volunteer: Volunteer | None


def resolve_import_target(
    session: Session,
    *,
    run_id: int,
    external_system: str,
    external_id: str | None,
) -> ImportTarget:
    """
    Resolve the import target for a payload using `external_id_map`.
    """

    if not external_id:
        raise MissingExternalIdentifier(external_system)

    base_filters = {
        "entity_type": ENTITY_TYPE_VOLUNTEER,
        "external_system": external_system,
        "external_id": external_id,
    }

    active_map = (
        session.query(ExternalIdMap).filter_by(**base_filters, is_active=True).order_by(ExternalIdMap.id.desc()).first()
    )
    if active_map is not None:
        active_map.mark_seen(run_id=run_id)
        volunteer = session.get(Volunteer, active_map.entity_id)
        return ImportTarget(action="update", id_map=active_map, volunteer=volunteer)

    inactive_map = (
        session.query(ExternalIdMap)
        .filter_by(**base_filters, is_active=False)
        .order_by(ExternalIdMap.last_seen_at.desc(), ExternalIdMap.id.desc())
        .first()
    )
    if inactive_map is not None:
        inactive_map.mark_seen(run_id=run_id)
        volunteer = session.get(Volunteer, inactive_map.entity_id)
        return ImportTarget(action="reactivate", id_map=inactive_map, volunteer=volunteer)

    return ImportTarget(action="create", id_map=None, volunteer=None)
