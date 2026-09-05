"""Deterministic catalog view from legacy catalog + immutable promotions.

Pure functions. No COS I/O. No writes.

Transitional merge (Phase D3):

  CATALOG_VIEW = legacy catalog entries + promotion-record projection

Precedence:

- wall only in legacy → keep the legacy entry unchanged
- wall only in promotions → use the promotion-projected entry
- wall in both, same display name → promotion latestReleaseId is
  authoritative (highest rNNNNNN among promotion records for that wall)
- wall in both, different names → fail closed

Legacy catalog bytes are never modified. This module only builds a view.
iOS still receives cragpal.wall-catalog.v1.

Once every retained wall has canonical promotion records, a later
explicit migration may retire the legacy catalog fallback.

GET /v1/walls is PRODUCTION audience only. GET /v1/debug/walls is
DEBUG_TEST. Audience is never inferred from wallId or display name.
"""

from __future__ import annotations

from .contract import (
    AUDIENCE_DEBUG_TEST,
    AUDIENCE_PRODUCTION,
    CATALOG_SCHEMA,
    ENVIRONMENT_DEVELOPMENT_TEST,
    ENVIRONMENT_PRODUCTION,
    ContractError,
    catalog_entry,
    classified_environment_from_payload,
    empty_catalog,
    is_release_id,
    validate_catalog,
)
from .promotion import PromotionRecordError, decode_promotion_record, promotion_environment


class ProjectionError(ContractError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def release_ordinal(release_id: str) -> int:
    if not is_release_id(release_id):
        raise ProjectionError("PROMOTION_RECORD_INVALID", "invalid releaseId")
    return int(release_id[1:])


def project_promotions(records: list[dict]) -> dict:
    """Project promotion records into cragpal.wall-catalog.v1."""
    by_wall: dict[str, list[dict]] = {}
    seen_pair: dict[tuple[str, str], dict] = {}
    for raw in records:
        try:
            record = decode_promotion_record(raw)
        except PromotionRecordError as exc:
            raise ProjectionError(exc.code, str(exc)) from exc
        wall_id = str(record["wallId"])
        release_id = str(record["releaseId"])
        pair = (wall_id, release_id)
        prior = seen_pair.get(pair)
        if prior is not None and prior != record:
            raise ProjectionError(
                "PROMOTION_IDENTITY_CONFLICT",
                f"duplicate conflicting promotion identity for {wall_id}/{release_id}",
            )
        seen_pair[pair] = record
        by_wall.setdefault(wall_id, []).append(record)

    walls: list[dict] = []
    for wall_id in sorted(by_wall):
        group = by_wall[wall_id]
        names = {item["name"] for item in group}
        if len(names) != 1:
            raise ProjectionError(
                "PROMOTION_NAME_CONFLICT",
                f"conflicting display names for {wall_id}",
            )
        environments = {_promotion_environment(item) for item in group}
        if len(environments) != 1:
            raise ProjectionError(
                "PROMOTION_ENVIRONMENT_CONFLICT",
                f"conflicting environments for {wall_id}",
            )
        latest = max(group, key=lambda item: release_ordinal(str(item["releaseId"])))
        walls.append(
            catalog_entry(
                wall_id=wall_id,
                name=str(latest["name"]),
                latest_release_id=str(latest["releaseId"]),
                environment=next(iter(environments)),
            )
        )
    catalog = empty_catalog()
    catalog["walls"] = walls
    catalog["schema"] = CATALOG_SCHEMA
    return catalog


def merge_legacy_and_projected(legacy: dict, projected: dict) -> dict:
    """Merge validated legacy catalog with promotion-projected catalog."""
    try:
        legacy = validate_catalog(legacy)
        projected = validate_catalog(projected)
    except ContractError as exc:
        raise ProjectionError("CATALOG_INVALID", str(exc)) from exc

    by_legacy = {str(item["wallId"]): item for item in legacy["walls"]}
    by_projected = {str(item["wallId"]): item for item in projected["walls"]}
    walls: list[dict] = []
    for wall_id in sorted(set(by_legacy) | set(by_projected)):
        left = by_legacy.get(wall_id)
        right = by_projected.get(wall_id)
        if left is not None and right is None:
            walls.append(
                catalog_entry(
                    wall_id=wall_id,
                    name=str(left["name"]),
                    latest_release_id=str(left["latestReleaseId"]),
                    environment=_entry_environment(left),
                )
            )
            continue
        if right is not None and left is None:
            walls.append(
                catalog_entry(
                    wall_id=wall_id,
                    name=str(right["name"]),
                    latest_release_id=str(right["latestReleaseId"]),
                    environment=_entry_environment(right),
                )
            )
            continue
        assert left is not None and right is not None
        if left["name"] != right["name"]:
            raise ProjectionError(
                "LEGACY_PROMOTION_NAME_CONFLICT",
                f"legacy and promotion display names conflict for {wall_id}",
            )
        left_env = _entry_environment(left)
        right_env = _entry_environment(right)
        if left_env != right_env:
            raise ProjectionError(
                "PROMOTION_ENVIRONMENT_CONFLICT",
                f"legacy and promotion environments conflict for {wall_id}",
            )
        walls.append(
            catalog_entry(
                wall_id=wall_id,
                name=str(right["name"]),
                latest_release_id=str(right["latestReleaseId"]),
                environment=right_env,
            )
        )
    catalog = empty_catalog()
    catalog["walls"] = walls
    return catalog


def filter_catalog_for_audience(catalog: dict, audience: str) -> dict:
    """Apply PRODUCTION or DEBUG_TEST audience. Unknown environment already failed closed."""
    try:
        catalog = validate_catalog(catalog)
    except ContractError as exc:
        raise ProjectionError("CATALOG_INVALID", str(exc)) from exc
    if audience not in {AUDIENCE_PRODUCTION, AUDIENCE_DEBUG_TEST}:
        raise ProjectionError("CATALOG_AUDIENCE_INVALID", "unknown catalog audience")
    walls: list[dict] = []
    for item in catalog["walls"]:
        environment = _entry_environment(item)
        if audience == AUDIENCE_PRODUCTION:
            if environment == ENVIRONMENT_PRODUCTION:
                walls.append(item)
            continue
        if environment in {ENVIRONMENT_PRODUCTION, ENVIRONMENT_DEVELOPMENT_TEST, None}:
            walls.append(item)
    out = empty_catalog()
    out["walls"] = walls
    return out


def _entry_environment(item: dict) -> str | None:
    try:
        return classified_environment_from_payload(item)
    except ContractError as exc:
        raise ProjectionError("PROMOTION_ENVIRONMENT_INVALID", str(exc)) from exc


def _promotion_environment(record: dict) -> str | None:
    try:
        return promotion_environment(record)
    except PromotionRecordError as exc:
        raise ProjectionError(exc.code, str(exc)) from exc
