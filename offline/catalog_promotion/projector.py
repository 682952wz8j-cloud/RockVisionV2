"""Deterministic catalog projection from immutable promotion records.

latestReleaseId = max(valid promoted release ordinal for wallId).
Catalog v1 is a view, not a mutable publication authority.
"""

from __future__ import annotations

from .catalog import CATALOG_SCHEMA, CatalogError, empty_catalog, encode_catalog, release_ordinal
from .record import PromotionRecordError, decode_promotion_record


class ProjectionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def project_catalog(records: list[dict]) -> dict:
    """Project decoded promotion records into cragpal.wall-catalog.v1."""
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
        try:
            latest = max(group, key=lambda item: release_ordinal(str(item["releaseId"])))
        except CatalogError as exc:
            raise ProjectionError("PROMOTION_RECORD_INVALID", str(exc)) from exc
        walls.append(
            {
                "wallId": wall_id,
                "name": latest["name"],
                "latestReleaseId": latest["releaseId"],
            }
        )
    catalog = empty_catalog()
    catalog["walls"] = walls
    catalog["schema"] = CATALOG_SCHEMA
    return catalog


def project_catalog_bytes(records: list[dict]) -> bytes:
    return encode_catalog(project_catalog(records))
