"""cragpal.wall-promotion.v1 decode. Read-only. No COS I/O."""

from __future__ import annotations

from .contract import (
    CLASSIFIED_ENVIRONMENTS,
    PROMOTION_SCHEMA,
    SHA256_RE,
    ContractError,
    classified_environment_from_payload,
    is_release_id,
    is_safe_id,
)


class PromotionRecordError(ContractError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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
    if not isinstance(sha, str) or SHA256_RE.fullmatch(sha) is None:
        raise PromotionRecordError(
            "PROMOTION_RECORD_INVALID",
            "releaseManifestSha256 must be 64 lowercase hex",
        )
    if wall_id is not None and rec_wall != wall_id:
        raise PromotionRecordError("PROMOTION_IDENTITY_CONFLICT", "promotion wallId mismatch")
    if release_id is not None and rec_release != release_id:
        raise PromotionRecordError("PROMOTION_IDENTITY_CONFLICT", "promotion releaseId mismatch")
    try:
        classified_environment_from_payload(payload)
    except ContractError as exc:
        raise PromotionRecordError("PROMOTION_ENVIRONMENT_INVALID", str(exc)) from exc
    return payload


def promotion_environment(record: dict) -> str | None:
    try:
        return classified_environment_from_payload(record)
    except ContractError as exc:
        raise PromotionRecordError("PROMOTION_ENVIRONMENT_INVALID", str(exc)) from exc


def promotion_identity(record: dict) -> tuple[str, str, str, str, str, str]:
    env = promotion_environment(record)
    return (
        str(record.get("schema") or ""),
        str(record.get("wallId") or ""),
        str(record.get("releaseId") or ""),
        str(record.get("name") or ""),
        str(record.get("releaseManifestSha256") or ""),
        env or "",
    )


def promotion_record(
    *,
    wall_id: str,
    release_id: str,
    name: str,
    promoted_at: str,
    release_manifest_sha256: str,
    environment: str | None = None,
) -> dict:
    payload = {
        "schema": PROMOTION_SCHEMA,
        "wallId": wall_id,
        "releaseId": release_id,
        "name": name,
        "promotedAt": promoted_at,
        "releaseManifestSha256": release_manifest_sha256,
    }
    if environment is not None:
        if environment not in CLASSIFIED_ENVIRONMENTS:
            raise PromotionRecordError("PROMOTION_ENVIRONMENT_INVALID", "invalid environment")
        payload["environment"] = environment
    return payload
