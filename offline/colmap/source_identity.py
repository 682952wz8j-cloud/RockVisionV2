"""Bind a COLMAP sparse model to the Generic Stage 2 selected capture set.

Identity means: no foreign registered images, and the loaded model is exactly
the reconstruction-recorded selected model. Partial registration is allowed.
This module does not change COLMAP thresholds or Sim(3) math.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from offline.ingestion.hashing import sha256_file

SCHEMA_VERSION = "colmap_source_identity.1"
PROVENANCE_FILENAME = "colmap_source_identity.json"
SELECTED_MODEL_RELATIVE_PATH = "sparse/best"
MODEL_SELECTION_RULE = (
    "max (num_reg_images, num_points3D) among numeric sparse/N models; "
    "authoritative export is sparse/best"
)

REASON_PROVEN = "COLMAP_SOURCE_IDENTITY_PROVEN"
REASON_NOT_PROVEN = "COLMAP_SOURCE_IDENTITY_NOT_PROVEN"
REASON_SET_MISMATCH = "COLMAP_SOURCE_SET_MISMATCH"
REASON_MODEL_MISMATCH = "COLMAP_MODEL_IDENTITY_MISMATCH"
REASON_FOREIGN_IMAGE = "COLMAP_FOREIGN_IMAGE"
REASON_AMBIGUOUS = "COLMAP_IMAGE_IDENTITY_AMBIGUOUS"

STATUS_AUTO_PASS = "AUTO_PASS"
STATUS_AUTO_FAIL = "AUTO_FAIL"
STATUS_HUMAN_REVIEW = "HUMAN_REVIEW_REQUIRED"
STATUS_DGRR = "DEVELOPMENT_GATE_REVIEW_REQUIRED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def duplicate_basenames(relative_paths: tuple[str, ...] | list[str]) -> list[str]:
    counts = Counter(Path(rel).name for rel in relative_paths)
    return sorted(name for name, count in counts.items() if count > 1)


def model_fingerprint(model_dir: Path) -> str:
    digest = hashlib.sha256()
    if not model_dir.is_dir():
        return ""
    files = sorted(path for path in model_dir.iterdir() if path.is_file())
    if not files:
        return ""
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def provenance_path(colmap_dir: Path) -> Path:
    return colmap_dir / PROVENANCE_FILENAME


def load_provenance(colmap_dir: Path) -> dict | None:
    path = provenance_path(colmap_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def resolve_recorded_model_dir(colmap_dir: Path, relative: str | None) -> Path | None:
    if not relative or not isinstance(relative, str):
        return None
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    root = colmap_dir.resolve()
    resolved = (colmap_dir / rel).resolve()
    if resolved != root and root not in resolved.parents:
        return None
    return resolved


def read_registered_names(model_dir: Path) -> list[str]:
    import pycolmap

    reconstruction = pycolmap.Reconstruction()
    reconstruction.read(str(model_dir))
    names = []
    for image_id in reconstruction.reg_image_ids():
        names.append(reconstruction.image(image_id).name)
    return sorted(names)


def selected_source_snapshot(incoming: Path, sources) -> tuple[tuple[str, ...], dict[str, str], list[str]]:
    relative_paths = tuple(sources.image_relative_paths or ())
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for rel in relative_paths:
        path = incoming / rel
        if not path.is_file():
            missing.append(rel)
            continue
        hashes[rel] = sha256_file(path)
    return relative_paths, hashes, missing


def build_provenance_payload(
    *,
    wall_id: str,
    selected_relative_paths: tuple[str, ...] | list[str],
    selected_sha256: dict[str, str],
    selected_model_id: int | None,
    selected_model_relative_path: str,
    source_model_relative_path: str | None,
    registered_image_names: list[str],
    model_dir: Path,
    image_dir_relative: str | None = None,
) -> dict:
    paths = list(selected_relative_paths)
    registered = sorted(registered_image_names)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _now(),
        "wallId": wall_id,
        "selectedImageRelativePaths": paths,
        "selectedImageBasenames": [Path(rel).name for rel in paths],
        "selectedImageSha256": {rel: selected_sha256[rel] for rel in paths if rel in selected_sha256},
        "selectedImageCount": len(paths),
        "imageDirRelative": image_dir_relative,
        "selectedModelId": selected_model_id,
        "selectedModelRelativePath": selected_model_relative_path,
        "sourceModelRelativePath": source_model_relative_path,
        "modelSelectionRule": MODEL_SELECTION_RULE,
        "registeredImageNames": registered,
        "registeredImageCount": len(registered),
        "modelFingerprint": model_fingerprint(model_dir),
        "outputFrame": "WallLocal",
        "wallMetricMetersProvenance": "NOT_CLAIMED",
    }


def write_provenance(colmap_dir: Path, payload: dict) -> Path:
    path = provenance_path(colmap_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_generic_reconstruct_provenance(
    *,
    dest: Path,
    wall_id: str,
    selected_relative_paths: list[str],
    selected_sha256: dict[str, str],
    selected_model_id: int | None,
    registered_image_names: list[str],
    image_dir_relative: str | None,
    source_model_relative_path: str | None,
) -> dict | None:
    model_dir = dest / SELECTED_MODEL_RELATIVE_PATH
    if not (model_dir / "images.bin").is_file():
        return None
    payload = build_provenance_payload(
        wall_id=wall_id,
        selected_relative_paths=selected_relative_paths,
        selected_sha256=selected_sha256,
        selected_model_id=selected_model_id,
        selected_model_relative_path=SELECTED_MODEL_RELATIVE_PATH,
        source_model_relative_path=source_model_relative_path,
        registered_image_names=registered_image_names,
        model_dir=model_dir,
        image_dir_relative=image_dir_relative,
    )
    write_provenance(dest, payload)
    return payload


def _result(
    *,
    status: str,
    reason: str,
    allowed: bool,
    problems: list[str],
    extra: dict | None = None,
) -> dict:
    payload = {
        "colmapSourceIdentityProvenance": status,
        "colmapSourceIdentityReasonCode": reason,
        "colmapSourceIdentityExecutionAllowed": allowed,
        "selectedModelRelativePath": None,
        "resolvedModelPath": None,
        "registeredImageNames": [],
        "selectedImageCount": 0,
        "registeredImageCount": 0,
        "foreignImageNames": [],
        "problems": problems,
        "outputFrame": "WallLocal",
        "wallMetricMetersProvenance": "NOT_CLAIMED",
        "genericStage2Pass": False,
        "productionBuildStage2Enabled": False,
    }
    if extra:
        payload.update(extra)
    return payload


def evaluate_colmap_source_identity(
    incoming: Path,
    sources,
    colmap_dir: Path,
    *,
    registered_image_names: list[str] | None = None,
) -> dict:
    relative_paths, current_hashes, missing_files = selected_source_snapshot(incoming, sources)
    dupes = duplicate_basenames(relative_paths)
    extra_base = {
        "selectedImageCount": len(relative_paths),
        "selectedImageRelativePaths": list(relative_paths),
    }
    if dupes:
        return _result(
            status=STATUS_HUMAN_REVIEW,
            reason=REASON_AMBIGUOUS,
            allowed=False,
            problems=[f"duplicate selected image basenames: {dupes}"],
            extra=extra_base,
        )
    if missing_files:
        return _result(
            status=STATUS_DGRR,
            reason=REASON_SET_MISMATCH,
            allowed=False,
            problems=[f"selected source images missing under incoming: {missing_files}"],
            extra=extra_base,
        )

    recorded = load_provenance(colmap_dir)
    if recorded is None:
        return _result(
            status=STATUS_DGRR,
            reason=REASON_NOT_PROVEN,
            allowed=False,
            problems=["COLMAP source identity provenance artifact is absent"],
            extra=extra_base,
        )

    if recorded.get("schemaVersion") != SCHEMA_VERSION:
        return _result(
            status=STATUS_DGRR,
            reason=REASON_NOT_PROVEN,
            allowed=False,
            problems=[f"unsupported identity schema {recorded.get('schemaVersion')}"],
            extra=extra_base,
        )

    if str(recorded.get("wallId") or "") != str(sources.wall_id or ""):
        return _result(
            status=STATUS_DGRR,
            reason=REASON_SET_MISMATCH,
            allowed=False,
            problems=[
                f"provenance wallId={recorded.get('wallId')!r} does not match selected wallId={sources.wall_id!r}"
            ],
            extra=extra_base,
        )

    recorded_dir = recorded.get("imageDirRelative")
    if recorded_dir and str(recorded_dir) != str(sources.image_dir_relative or ""):
        return _result(
            status=STATUS_DGRR,
            reason=REASON_SET_MISMATCH,
            allowed=False,
            problems=["selected image directory does not match reconstruction provenance"],
            extra=extra_base,
        )

    recorded_paths = tuple(recorded.get("selectedImageRelativePaths") or ())
    if set(recorded_paths) != set(relative_paths):
        return _result(
            status=STATUS_DGRR,
            reason=REASON_SET_MISMATCH,
            allowed=False,
            problems=["selected source image set does not match reconstruction provenance"],
            extra=extra_base,
        )

    recorded_hashes = recorded.get("selectedImageSha256") or {}
    hash_mismatch = sorted(
        rel
        for rel in relative_paths
        if recorded_hashes.get(rel) != current_hashes.get(rel)
    )
    if hash_mismatch:
        return _result(
            status=STATUS_DGRR,
            reason=REASON_SET_MISMATCH,
            allowed=False,
            problems=[f"selected image SHA256 mismatch vs reconstruction provenance: {hash_mismatch}"],
            extra=extra_base,
        )

    model_rel = recorded.get("selectedModelRelativePath")
    model_dir = resolve_recorded_model_dir(colmap_dir, model_rel)
    extra_model = {
        **extra_base,
        "selectedModelRelativePath": model_rel,
        "resolvedModelPath": str(model_dir) if model_dir else None,
    }
    if model_dir is None or not (model_dir / "images.bin").is_file():
        return _result(
            status=STATUS_DGRR,
            reason=REASON_MODEL_MISMATCH,
            allowed=False,
            problems=["recorded selected COLMAP model is absent or unsafe"],
            extra=extra_model,
        )

    actual_fp = model_fingerprint(model_dir)
    recorded_fp = recorded.get("modelFingerprint")
    if not recorded_fp or actual_fp != recorded_fp:
        return _result(
            status=STATUS_DGRR,
            reason=REASON_MODEL_MISMATCH,
            allowed=False,
            problems=["loaded COLMAP model fingerprint does not match recorded selected model"],
            extra=extra_model,
        )

    try:
        live_names = (
            sorted(registered_image_names)
            if registered_image_names is not None
            else read_registered_names(model_dir)
        )
    except Exception as exc:
        return _result(
            status=STATUS_DGRR,
            reason=REASON_NOT_PROVEN,
            allowed=False,
            problems=[f"unable to read registered COLMAP image names: {exc}"],
            extra=extra_model,
        )

    selected_basenames = {Path(rel).name for rel in relative_paths}
    foreign = sorted(name for name in live_names if name not in selected_basenames)
    extra_names = {
        **extra_model,
        "registeredImageNames": live_names,
        "registeredImageCount": len(live_names),
        "foreignImageNames": foreign,
    }
    if foreign:
        return _result(
            status=STATUS_AUTO_FAIL,
            reason=REASON_FOREIGN_IMAGE,
            allowed=False,
            problems=[f"COLMAP registered images outside selected source set: {foreign}"],
            extra=extra_names,
        )
    if not live_names:
        return _result(
            status=STATUS_DGRR,
            reason=REASON_NOT_PROVEN,
            allowed=False,
            problems=["recorded selected COLMAP model has no registered images"],
            extra=extra_names,
        )
    return _result(
        status=STATUS_AUTO_PASS,
        reason=REASON_PROVEN,
        allowed=True,
        problems=[],
        extra=extra_names,
    )


def rank_numeric_sparse_models(sparse_dir: Path) -> tuple[int, object] | None:
    import pycolmap

    ranked = []
    if not sparse_dir.is_dir():
        return None
    for child in sparse_dir.iterdir():
        if not child.is_dir() or not child.name.isdigit():
            continue
        if not (child / "images.bin").is_file():
            continue
        rec = pycolmap.Reconstruction()
        rec.read(str(child))
        ranked.append((int(child.name), rec, rec.num_reg_images(), rec.num_points3D()))
    if not ranked:
        return None
    selected_id, rec, _n_reg, _n_pts = max(ranked, key=lambda item: (item[2], item[3], -item[0]))
    return selected_id, rec


def materialize_identity_workspace(
    *,
    incoming: Path,
    sources,
    source_colmap_dir: Path,
    dest_colmap_dir: Path,
) -> dict:
    """Copy an independently proven selected model into dest. Does not modify source_colmap_dir."""
    relative_paths, hashes, missing = selected_source_snapshot(incoming, sources)
    dupes = duplicate_basenames(relative_paths)
    if dupes:
        return _result(
            status=STATUS_HUMAN_REVIEW,
            reason=REASON_AMBIGUOUS,
            allowed=False,
            problems=[f"duplicate selected image basenames: {dupes}"],
        )
    if missing:
        return _result(
            status=STATUS_DGRR,
            reason=REASON_SET_MISMATCH,
            allowed=False,
            problems=[f"selected source images missing under incoming: {missing}"],
        )

    ranked = rank_numeric_sparse_models(source_colmap_dir / "sparse")
    if ranked is None:
        return _result(
            status=STATUS_DGRR,
            reason=REASON_NOT_PROVEN,
            allowed=False,
            problems=["no numeric COLMAP sparse model is available to derive identity"],
        )
    selected_id, reconstruction = ranked
    from .metrics import registered_names as names_of

    live_names = sorted(names_of(reconstruction))
    selected_basenames = {Path(rel).name for rel in relative_paths}
    foreign = sorted(name for name in live_names if name not in selected_basenames)
    if foreign:
        return _result(
            status=STATUS_AUTO_FAIL,
            reason=REASON_FOREIGN_IMAGE,
            allowed=False,
            problems=[f"source COLMAP model contains foreign images: {foreign}"],
            extra={"foreignImageNames": foreign, "registeredImageNames": live_names},
        )
    if not live_names:
        return _result(
            status=STATUS_DGRR,
            reason=REASON_NOT_PROVEN,
            allowed=False,
            problems=["source COLMAP model has no registered images"],
        )

    source_model = source_colmap_dir / "sparse" / str(selected_id)
    dest_model = dest_colmap_dir / SELECTED_MODEL_RELATIVE_PATH
    if dest_model.exists():
        shutil.rmtree(dest_model)
    shutil.copytree(source_model, dest_model)
    payload = build_provenance_payload(
        wall_id=sources.wall_id,
        selected_relative_paths=relative_paths,
        selected_sha256=hashes,
        selected_model_id=selected_id,
        selected_model_relative_path=SELECTED_MODEL_RELATIVE_PATH,
        source_model_relative_path=f"sparse/{selected_id}",
        registered_image_names=live_names,
        model_dir=dest_model,
        image_dir_relative=sources.image_dir_relative,
    )
    write_provenance(dest_colmap_dir, payload)
    return evaluate_colmap_source_identity(incoming, sources, dest_colmap_dir)
