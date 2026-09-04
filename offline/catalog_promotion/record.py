"""cragpal.wall-promotion.v1 encode/decode."""

from __future__ import annotations

import json
import re

from offline.localization_package.package_schema import is_release_id, is_safe_id

PROMOTION_SCHEMA = "cragpal.wall-promotion.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PromotionRecordError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def encode_promotion_record(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def promotion_record(
    *,
    wall_id: str,
    release_id: str,
    name: str,
    promoted_at: str,
    release_manifest_sha256: str,
) -> dict:
    return {
        "schema": PROMOTION_SCHEMA,
        "wallId": wall_id,
        "releaseId": release_id,
        "name": name,
        "promotedAt": promoted_at,
        "releaseManifestSha256": release_manifest_sha256,
    }


def decode_promotion_record(
    payload: object,
    *,
    wall_id: str | None = None,
    release_id: str | None = None,
) -> dict:
    if not isinstance(payload, dict):
        raise PromotionRecordError("PROMOTION_RECORD_INVALID", "promotion record must be an object")
    if payload.get("schema") != PROMOTION_SCHEMA:
        raise PromotionRecordError(
            "PROMOTION_SCHEMA_UNSUPPORTED",
            "promotion schema is not cragpal.wall-promotion.v1",
        )
    rec_wall = str(payload.get("wallId") or "")
    rec_release = str(payload.get("releaseId") or "")
    if not is_safe_id(rec_wall):
        raise PromotionRecordError("PROMOTION_RECORD_INVALID", "invalid promotion wallId")
    if not is_release_id(rec_release):
        raise PromotionRecordError("PROMOTION_RECORD_INVALID", "invalid promotion releaseId")
    name = payload.get("name")
    if not isinstance(name, str) or not name or name.strip() != name:
        raise PromotionRecordError("PROMOTION_RECORD_INVALID", "promotion name is required")
    promoted_at = payload.get("promotedAt")
    if not isinstance(promoted_at, str) or not promoted_at:
        raise PromotionRecordError("PROMOTION_RECORD_INVALID", "promotedAt is required")
    sha = payload.get("releaseManifestSha256")
    if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
        raise PromotionRecordError("PROMOTION_RECORD_INVALID", "releaseManifestSha256 must be 64 lowercase hex")
    if wall_id is not None and rec_wall != wall_id:
        raise PromotionRecordError("PROMOTION_IDENTITY_CONFLICT", "promotion wallId mismatch")
    if release_id is not None and rec_release != release_id:
        raise PromotionRecordError("PROMOTION_IDENTITY_CONFLICT", "promotion releaseId mismatch")
    return payload


def promotion_identity(record: dict) -> tuple[str, str, str, str, str]:
    return (
        str(record.get("schema") or ""),
        str(record.get("wallId") or ""),
        str(record.get("releaseId") or ""),
        str(record.get("name") or ""),
        str(record.get("releaseManifestSha256") or ""),
    )
