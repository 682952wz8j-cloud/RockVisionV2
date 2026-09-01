from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from offline.ingestion.hashing import sha256_file, snapshot_hashes
from offline.ingestion.pipeline import repo_root_from

from .diagnostics import write_diagnostics
from .layout import (
    DJI_CAPTURE_DIR,
    check_incoming_layout,
    output_dir,
    wall_incoming,
)
from .manifest import build_manifest, load_and_select
from .metrics import (
    decide_gate_result,
    keypoints_from_database,
    matching_from_database,
    observations_from_reconstruction,
    registered_names,
    sparse_from_reconstruction,
    split_pair_id,
    unpack_pair_table,
)
from .report import render_reconstruction_report, write_json
from .source_identity import (
    REASON_AMBIGUOUS,
    duplicate_basenames,
    write_generic_reconstruct_provenance,
)

CAMERA_MODEL_NAME = "SIMPLE_RADIAL"
ENGINE = "pycolmap"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_log(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def reconstruct(wall_id: str, root: Path, *, sources=None, dest: Path | None = None) -> dict:
    incoming = wall_incoming(root, wall_id)
    dest = dest or output_dir(root, wall_id)
    dest.mkdir(parents=True, exist_ok=True)
    logs: list[str] = [f"reconstruct start {_now()}", f"wall={wall_id}"]
    generic = sources is not None

    if not generic:
        layout_errors = check_incoming_layout(root, wall_id)
        if layout_errors:
            payload = {
                "wallId": wall_id,
                "gateResult": "FAIL",
                "sWallColmap": "NOT COMPUTED",
                "errors": layout_errors,
                "problems": layout_errors,
                "incomingUnchanged": True,
            }
            (dest / "layout_error.md").write_text(
                "# COLMAP Gate STOP\n\n" + "\n".join(f"- {e}" for e in layout_errors) + "\n",
                encoding="utf-8",
            )
            write_json(dest / "reconstruction_metrics.json", payload)
            _write_log(dest / "logs" / "reconstruct.log", logs + layout_errors)
            return payload

    before = snapshot_hashes(incoming)
    if generic:
        dupes = duplicate_basenames(sources.image_relative_paths)
        if dupes:
            payload = {
                "wallId": wall_id,
                "gateResult": "HUMAN_REVIEW_REQUIRED",
                "sWallColmap": "NOT COMPUTED",
                "errors": [f"duplicate selected image basenames: {dupes}"],
                "problems": [f"duplicate selected image basenames: {dupes}"],
                "reasonCode": REASON_AMBIGUOUS,
                "incomingUnchanged": True,
                "genericStage2Pass": False,
                "productionBuildStage2Enabled": False,
            }
            write_json(dest / "reconstruction_metrics.json", payload)
            _write_log(dest / "logs" / "reconstruct.log", logs + payload["errors"])
            return payload
        selected = []
        for rel in sources.image_relative_paths:
            path = incoming / rel
            selected.append(
                {
                    "relativePath": rel,
                    "filename": Path(rel).name,
                    "mrkPhotoId": None,
                    "mrkAssociationStatus": "PROVEN",
                    "mrkMatched": True,
                }
            )
            if not path.is_file():
                select_errors = [f"source image missing under wall incoming: {rel}"]
                after = snapshot_hashes(incoming)
                payload = {
                    "wallId": wall_id,
                    "gateResult": "FAIL",
                    "sWallColmap": "NOT COMPUTED",
                    "errors": select_errors,
                    "problems": select_errors,
                    "incomingUnchanged": before == after,
                    "sourceImages": len(selected),
                }
                write_json(dest / "reconstruction_metrics.json", payload)
                _write_log(dest / "logs" / "reconstruct.log", logs + select_errors)
                return payload
        select_errors: list[str] = []
        image_dir = incoming / sources.image_dir_relative
    else:
        selected, select_errors, _source = load_and_select(root, wall_id)
        image_dir = incoming / DJI_CAPTURE_DIR
    if select_errors:
        after = snapshot_hashes(incoming)
        payload = {
            "wallId": wall_id,
            "gateResult": "FAIL",
            "sWallColmap": "NOT COMPUTED",
            "errors": select_errors,
            "problems": select_errors,
            "incomingUnchanged": before == after,
            "sourceImages": len(selected),
        }
        write_json(dest / "reconstruction_metrics.json", payload)
        _write_log(dest / "logs" / "reconstruct.log", logs + select_errors)
        return payload

    hashes = {row["relativePath"]: sha256_file(incoming / row["relativePath"]) for row in selected}
    image_names = [row["filename"] for row in selected]

    inferred = _infer_camera(image_dir / image_names[0])
    camera_model = {
        "selected": CAMERA_MODEL_NAME,
        "width": inferred.get("width"),
        "height": inferred.get("height"),
        "initialFocalPx": inferred.get("focalLength"),
        "initialParams": inferred.get("params"),
        "paramsInfo": inferred.get("paramsInfo"),
        "hasPriorFocalLength": inferred.get("hasPriorFocalLength"),
        "intrinsicsShared": True,
        "cameraMode": "SINGLE",
        "intrinsicsOptimized": {
            "focalLength": True,
            "extraParams": True,
            "principalPoint": False,
        },
        "reason": (
            "COLMAP EXIF inference is SIMPLE_RADIAL; CameraMode.SINGLE shares one physical camera."
            if generic
            else "COLMAP EXIF inference on DJI M4E originals is SIMPLE_RADIAL; all 47 frames share one physical camera."
        ),
    }
    manifest = build_manifest(
        wall_id=wall_id,
        selected=selected,
        incoming_wall=incoming,
        camera_model=camera_model,
        sha256_by_rel=hashes,
        capture_session="selected_primary_capture" if generic else None,
        source_folder=sources.image_dir_relative if generic else None,
    )
    write_json(dest / "colmap_source_manifest.json", manifest)
    logs.append(f"source set {len(selected)} images from {image_dir}")

    errors: list[str] = []
    problems: list[str] = []
    feature_table: dict[str, dict] = {}
    matching = {}
    sparse = {}
    observations = {}
    models: dict = {}
    selected_model_id = None
    source_model_relative_path = None
    registered_image_names: list[str] = []
    unregistered: list[str] = list(image_names)
    registered = 0
    pair_graph: list[dict] = []
    engine_version = "missing"

    try:
        import pycolmap
    except ImportError:
        errors.append("pycolmap is not installed")
        after = snapshot_hashes(incoming)
        return _finalize(
            dest,
            wall_id,
            manifest,
            camera_model,
            feature_table,
            matching,
            sparse,
            observations,
            models,
            selected_model_id,
            image_names,
            unregistered,
            registered,
            before,
            after,
            errors,
            problems,
            logs,
            engine_version,
        )

    engine_version = f"pycolmap {getattr(pycolmap, '__version__', '?')}"
    logs.append(engine_version)

    db_path = dest / "database.db"
    sparse_dir = dest / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)

    try:
        reused = _database_has_sources(db_path, image_names)
        if reused:
            logs.append("reusing existing database (features+matches already present)")
        else:
            if db_path.exists():
                db_path.unlink()
            logs.append("extract_features")
            pycolmap.extract_features(
                database_path=str(db_path),
                image_path=str(image_dir),
                image_names=image_names,
                camera_mode=pycolmap.CameraMode.SINGLE,
                camera_model=CAMERA_MODEL_NAME,
            )
        database = pycolmap.Database.open(str(db_path))
        feature_table = keypoints_from_database(database)
        failed = [name for name, row in feature_table.items() if not row["success"]]
        missing = [name for name in image_names if name not in feature_table]
        if failed or missing:
            errors.append("feature extraction failed for: " + ", ".join(failed + missing))
        logs.append(f"features images={len(feature_table)} failed={len(failed)+len(missing)}")

        if not reused or database.num_matched_image_pairs() == 0:
            logs.append("match_sequential overlap=10 quadratic_overlap=true")
            pairing = pycolmap.SequentialPairingOptions()
            pairing.overlap = 10
            pairing.quadratic_overlap = True
            pairing.loop_detection = False
            database.close()
            pycolmap.match_sequential(database_path=str(db_path), pairing_options=pairing)
            database = pycolmap.Database.open(str(db_path))
        matching = matching_from_database(database)
        matching["strategy"] = "sequential"
        matching["overlap"] = 10
        matching["quadraticOverlap"] = True
        matching["usedRtkForMatching"] = False
        pair_graph = _pair_graph(database)
        database.close()
        logs.append(
            f"matching attempted={matching.get('attemptedPairs')} verified={matching.get('verifiedPairs')}"
        )

        existing_models = _load_sparse_models(sparse_dir)
        if existing_models:
            logs.append(f"reusing existing sparse models {sorted(existing_models)}")
            maps = existing_models
        else:
            logs.append("incremental_mapping")
            maps = pycolmap.incremental_mapping(
                database_path=str(db_path),
                image_path=str(image_dir),
                output_path=str(sparse_dir),
            )
        models = {int(key): value for key, value in (maps or {}).items()}
        if not models:
            errors.append("incremental_mapping returned no models")
        else:
            selected_model_id, best = max(
                models.items(),
                key=lambda item: (item[1].num_reg_images(), item[1].num_points3D()),
            )
            source_model_relative_path = f"sparse/{selected_model_id}"
            best_dir = dest / "sparse" / "best"
            best_dir.mkdir(parents=True, exist_ok=True)
            best.write(str(best_dir))
            sparse = sparse_from_reconstruction(best)
            observations = observations_from_reconstruction(best)
            names = registered_names(best)
            registered_image_names = sorted(names)
            # COLMAP stores names as imported (filename only)
            unregistered = [name for name in image_names if name not in names]
            registered = len(image_names) - len(unregistered)
            write_diagnostics(best, dest / "diagnostics", pair_graph)
            logs.append(
                f"model {selected_model_id} registered={registered} points3D={sparse.get('points3D')}"
            )
            if len(models) > 1:
                problems.append(
                    f"reconstruction split into {len(models)} models; metrics use the largest"
                )
    except Exception as exc:
        errors.append(f"COLMAP pipeline exception: {exc}")
        logs.append(traceback.format_exc())

    after = snapshot_hashes(incoming)
    if before != after:
        errors.append("incoming files changed during reconstruction; incoming must remain immutable")

    return _finalize(
        dest,
        wall_id,
        manifest,
        camera_model,
        feature_table,
        matching,
        sparse,
        observations,
        models,
        selected_model_id,
        image_names,
        unregistered,
        registered,
        before,
        after,
        errors,
        problems,
        logs,
        engine_version,
        generic=generic,
        hashes=hashes,
        registered_image_names=registered_image_names,
        source_model_relative_path=source_model_relative_path,
    )


def _infer_camera(image_path: Path) -> dict:
    try:
        import pycolmap
    except ImportError:
        return {}
    camera = pycolmap.infer_camera_from_image(str(image_path))
    return {
        "model": str(camera.model),
        "width": int(camera.width),
        "height": int(camera.height),
        "focalLength": float(camera.focal_length),
        "params": [float(v) for v in camera.params],
        "paramsInfo": str(camera.params_info),
        "hasPriorFocalLength": bool(camera.has_prior_focal_length),
    }


def _load_sparse_models(sparse_dir: Path) -> dict:
    import pycolmap

    models = {}
    if not sparse_dir.is_dir():
        return models
    for child in sparse_dir.iterdir():
        if not child.is_dir() or not child.name.isdigit():
            continue
        if not (child / "images.bin").is_file():
            continue
        rec = pycolmap.Reconstruction()
        rec.read(str(child))
        models[int(child.name)] = rec
    return models


def _database_has_sources(db_path: Path, image_names: list[str]) -> bool:
    if not db_path.is_file():
        return False
    try:
        import pycolmap
    except ImportError:
        return False
    database = pycolmap.Database.open(str(db_path))
    try:
        present = {image.name for image in database.read_all_images()}
        return set(image_names) <= present and database.num_keypoints() > 0
    finally:
        database.close()


def _pair_graph(database) -> list[dict]:
    images = {image.image_id: image.name for image in database.read_all_images()}
    pair_ids, geoms = unpack_pair_table(database.read_two_view_geometries())
    graph = []
    for pair_id, geom in zip(pair_ids, geoms):
        id_a, id_b = split_pair_id(int(pair_id))
        inliers = getattr(geom, "inlier_matches", None)
        graph.append(
            {
                "imageA": images.get(id_a, str(id_a)),
                "imageB": images.get(id_b, str(id_b)),
                "inliers": len(inliers) if inliers is not None else 0,
            }
        )
    return graph


def _finalize(
    dest: Path,
    wall_id: str,
    manifest: dict,
    camera_model: dict,
    feature_table: dict,
    matching: dict,
    sparse: dict,
    observations: dict,
    models: dict,
    selected_model_id,
    image_names: list[str],
    unregistered: list[str],
    registered: int,
    before: dict,
    after: dict,
    errors: list[str],
    problems: list[str],
    logs: list[str],
    engine_version: str,
    *,
    generic: bool = False,
    hashes: dict[str, str] | None = None,
    registered_image_names: list[str] | None = None,
    source_model_relative_path: str | None = None,
) -> dict:
    from .metrics import _stats

    incoming_unchanged = before == after
    kp = [row["keypoints"] for row in feature_table.values()]
    desc = [row["descriptors"] for row in feature_table.values()]
    success = sum(1 for row in feature_table.values() if row["success"])
    failed = [name for name, row in feature_table.items() if not row["success"]]
    source_count = len(image_names)
    rate = (registered / source_count) if source_count else 0.0
    if failed:
        problems.append("feature extraction failed: " + ", ".join(failed))
    if unregistered:
        problems.append("unregistered images: " + ", ".join(unregistered))
    if rate < 0.90:
        problems.append(f"registration rate {rate:.3f} is below 0.90")

    gate = decide_gate_result(
        source_count=source_count,
        registered=registered,
        models=len(models),
        points3d=int(sparse.get("points3D") or 0),
        observations=int((observations or {}).get("total") or 0),
        median_track=((sparse.get("trackLength") or {}).get("median")),
        median_reproj=((sparse.get("reprojectionError") or {}).get("median")),
        incoming_unchanged=incoming_unchanged,
        errors=errors,
    )
    payload = {
        "schemaVersion": "colmap.1",
        "wallId": wall_id,
        "generatedAt": _now(),
        "engine": engine_version,
        "incomingUnchanged": incoming_unchanged,
        "sourceImages": source_count,
        "captureSession": manifest.get("captureSession"),
        "registeredImages": registered,
        "unregisteredImages": unregistered,
        "unregisteredImagesCount": len(unregistered),
        "registrationRate": rate,
        "modelCount": len(models),
        "selectedModelId": selected_model_id,
        "features": {
            "success": success,
            "failed": failed,
            "keypoints": _stats(kp),
            "descriptors": _stats(desc),
            "perImage": feature_table,
        },
        "matching": matching,
        "sparse": sparse,
        "observations": observations,
        "cameraModel": camera_model,
        "sWallColmap": "NOT COMPUTED",
        "errors": errors,
        "problems": problems,
        "gateResult": gate,
        "colmapNotContinued": [
            "dense",
            "mesh",
            "S_wall_colmap",
            "wall_package",
            "opencv_ios",
            "iphone_sift",
            "pnp",
        ],
        "genericStage2Pass": False,
        "productionBuildStage2Enabled": False,
        "outputFrame": "WallLocal",
        "wallMetricMetersProvenance": "NOT_CLAIMED",
    }
    if generic:
        selected_paths = [row["relativePath"] for row in (manifest.get("images") or []) if row.get("relativePath")]
        identity = write_generic_reconstruct_provenance(
            dest=dest,
            wall_id=wall_id,
            selected_relative_paths=selected_paths,
            selected_sha256=hashes or {},
            selected_model_id=selected_model_id,
            registered_image_names=list(registered_image_names or []),
            image_dir_relative=manifest.get("sourceFolder"),
            source_model_relative_path=source_model_relative_path,
        )
        payload["colmapSourceIdentity"] = identity
        payload["selectedModelRelativePath"] = None if identity is None else identity.get("selectedModelRelativePath")
    write_json(dest / "reconstruction_metrics.json", payload)
    (dest / "reconstruction_report.md").write_text(render_reconstruction_report(payload), encoding="utf-8")
    _write_log(dest / "logs" / "reconstruct.log", logs + errors + problems + [f"gate={gate}"])
    return payload
