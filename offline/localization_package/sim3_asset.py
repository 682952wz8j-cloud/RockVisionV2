"""S_wall_colmap package checks. Reuses existing parser. No new Sim(3) math."""

from __future__ import annotations

from pathlib import Path

from offline.metric_registration.serialize import load_sim3

from .schema import SIM3_STATUS_VALIDATED, ReasonCode


def assess_sim3_asset(path: Path) -> tuple[list[ReasonCode], dict]:
    """Return reason codes (empty if ok) and the parsed payload."""
    try:
        payload = load_sim3(path)
    except OSError:
        return [ReasonCode.METRIC_SIM3_REQUIRED], {"error": "missing"}
    except (ValueError, KeyError, TypeError) as exc:
        return [ReasonCode.SIM3_INVALID_GEOMETRY], {"error": str(exc)}
    codes: list[ReasonCode] = []
    status = str(payload.get("status") or "")
    if status != SIM3_STATUS_VALIDATED:
        codes.append(ReasonCode.SIM3_NOT_VALIDATED)
    if not _finite_transform(payload):
        codes.append(ReasonCode.SIM3_INVALID_GEOMETRY)
    return codes, payload


def assess_sim3_identity(
    payload: dict,
    *,
    wall_id: str,
    run_id: str | None,
    model_fingerprint: str | None,
) -> list[ReasonCode]:
    """Fail closed unless the Sim3 JSON itself names wall + run + COLMAP fingerprint.

    Do not infer them from directories, filenames, or timestamps.
    """
    codes: list[ReasonCode] = []
    if payload.get("wallId") != wall_id:
        codes.append(ReasonCode.WALL_ID_MISMATCH)
    if payload.get("wallBuildRunId") != run_id:
        codes.append(ReasonCode.SIM3_WALL_BUILD_RUN_MISMATCH)
    fingerprint = payload.get("colmapModelFingerprint") or payload.get("modelFingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        codes.append(ReasonCode.COLMAP_SOURCE_IDENTITY_NOT_PROVEN)
    elif not isinstance(model_fingerprint, str) or fingerprint != model_fingerprint:
        codes.append(ReasonCode.SIM3_MODEL_FINGERPRINT_MISMATCH)
    return codes


def _finite_transform(payload: dict) -> bool:
    scale = payload.get("scale")
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not _finite(float(scale)) or float(scale) <= 0:
        return False
    rotation = payload.get("rotationMatrix")
    values = rotation.get("values") if isinstance(rotation, dict) else rotation
    if not _finite_matrix(values, 3, 3):
        return False
    translation = payload.get("translationMeters")
    if not _finite_vec(translation, 3):
        return False
    return True


def _finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def _finite_vec(value: object, count: int) -> bool:
    if not isinstance(value, list) or len(value) != count:
        return False
    try:
        return all(_finite(float(item)) for item in value)
    except (TypeError, ValueError):
        return False


def _finite_matrix(value: object, rows: int, cols: int) -> bool:
    if not isinstance(value, list) or len(value) != rows:
        return False
    return all(_finite_vec(row, cols) for row in value)
