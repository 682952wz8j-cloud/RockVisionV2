"""Gate 3C offline pipeline through same-image / LOO. Stops before Swift."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np

from offline.colmap.layout import wall_incoming
from offline.ingestion.hashing import snapshot_hashes
from offline.metric_registration.serialize import load_sim3, write_json

from .associate import associate_xy, summarize_association
from .colmap_io import image_observations, load_reconstruction
from .compatibility import loo_compatibility, same_image_compatibility, select_compatibility_images
from .constants import (
    ASSOCIATION_RADIUS_NAME,
    CANDIDATE_K,
    DESCRIPTOR_DIM,
    GRAYSCALE_NOTE,
    MAX_PIXEL_DISTANCE,
    MIN_DISTINCT_POINT3D_FOR_RATIO,
    PINNED_OPENCV_COMMIT,
    PINNED_OPENCV_VERSION,
    RATIO_THRESHOLD,
    SIFT_CONTRAST_THRESHOLD,
    SIFT_EDGE_THRESHOLD,
    SIFT_N_OCTAVE_LAYERS,
    SIFT_NFEATURES,
    SIFT_SIGMA,
)
from .extract import extract_all_reference_images, load_extracted_cache
from .opencv_env import load_pinned_opencv, provenance_payload
from .serialize import apply_s_wall_colmap, freeze_artifact, load_frozen
from .production_run import ProductionStage3BindError, resolve_production_stage3_inputs, wall_build_run_dir


def output_dir(root: Path, wall_id: str, *, run_dir: Path | None = None) -> Path:
    if run_dir is not None:
        return run_dir / "reference_matching" / ASSOCIATION_RADIUS_NAME
    return root / "offline" / "work" / wall_id / "reference_matching" / ASSOCIATION_RADIUS_NAME


def _percentiles(values: list[int] | list[float]) -> dict:
    if not values:
        return {"min": None, "median": None, "p90": None, "max": None, "count": 0}
    arr = np.asarray(values, dtype=np.float64)
    return {
        "min": float(np.min(arr)),
        "median": float(np.median(arr)),
        "p90": float(np.quantile(arr, 0.90)),
        "max": float(np.max(arr)),
        "count": int(len(arr)),
    }


def _merge_hist(total: dict, part: dict) -> None:
    for key, value in part.items():
        total[key] = int(total.get(key, 0)) + int(value)


def build_reference_matching(wall_id: str, root: Path, *, run_id: str | None = None) -> dict:
    production = run_id is not None
    bind = None
    if production:
        try:
            bind = resolve_production_stage3_inputs(root, wall_id, run_id)
        except ProductionStage3BindError as exc:
            safe_id = run_id if run_id and ".." not in run_id and "/" not in run_id and "\\" not in run_id else "_rejected_run"
            dest = output_dir(root, wall_id, run_dir=wall_build_run_dir(root, wall_id, safe_id))
            dest.mkdir(parents=True, exist_ok=True)
            payload = {
                "wallId": wall_id,
                "runId": run_id,
                "gate": "3C",
                "stage": "production_run_bind",
                "gateResult": "STOP",
                "productionBound": True,
                "legacyFallback": False,
                "errors": [str(exc)],
                "reasonCode": exc.code,
                "outputDirectory": str(dest),
            }
            write_json(dest / "gate3c_stop.json", payload)
            return payload
        dest = output_dir(root, wall_id, run_dir=bind.run_dir)
        sparse = bind.model_dir
        sim3_path = bind.sim3_path
        sim3 = bind.sim3
    else:
        dest = output_dir(root, wall_id)
        sparse = root / "offline" / "work" / wall_id / "colmap" / "sparse" / "0"
        sim3_path = root / "offline" / "work" / wall_id / "metric_registration" / "S_wall_colmap.json"
        sim3 = None
    dest.mkdir(parents=True, exist_ok=True)
    incoming = wall_incoming(root, wall_id)
    before = snapshot_hashes(incoming)
    errors: list[str] = []

    provenance = provenance_payload(root)
    if provenance.get("status") != "PINNED_SOURCE_MATCH":
        errors.append(provenance.get("error") or "OpenCV provenance STOP")
        payload = {
            "wallId": wall_id,
            "runId": run_id,
            "gate": "3C",
            "stage": "provenance",
            "gateResult": "STOP",
            "humanReviewRequired": True,
            "productionBound": production,
            "legacyFallback": False if production else None,
            "errors": errors,
            "opencv": provenance,
            "incomingUnchanged": snapshot_hashes(incoming) == before,
        }
        write_json(dest / "gate3c_stop.json", payload)
        return payload

    if not production:
        sim3 = load_sim3(sim3_path)
    if str(sim3.get("status")).upper() != "VALIDATED":
        errors.append(f"S_wall_colmap status is {sim3.get('status')}, expected VALIDATED")
    reconstruction = load_reconstruction(sparse)
    observations = image_observations(reconstruction)
    if not observations:
        errors.append("no registered COLMAP images")
    if errors:
        payload = {
            "wallId": wall_id,
            "gate": "3C",
            "stage": "inputs",
            "gateResult": "STOP",
            "errors": errors,
            "opencv": provenance,
            "incomingUnchanged": snapshot_hashes(incoming) == before,
        }
        write_json(dest / "gate3c_stop.json", payload)
        return payload

    extract_dir = dest.parent / "extract"
    extracted, extract_summary = extract_all_reference_images(root, incoming, observations, extract_dir)
    extracted_by_id = {item.image_id: item for item in extracted}

    descriptors_rows: list[np.ndarray] = []
    landmark_rows: list[dict] = []
    per_image_reports: list[dict] = []
    hist = {"0_1": 0, "1_2": 0, "2_3": 0, "3_5": 0, "gt_5": 0, "noReconstructedNeighbor": 0}
    totals = {
        "opencvFeaturesTotal": 0,
        "colmapReconstructedObservations": 0,
        "colmapPoints2DWithout3D": 0,
        "candidateAssociations": 0,
        "accepted": 0,
        "mutualRejected": 0,
        "uniquenessRejected": 0,
        "twoPxRejected": 0,
    }
    index = 0
    for obs in observations:
        meta = extracted_by_id[obs.image_id]
        if meta.cache is None:
            raise RuntimeError(f"missing extract cache for {obs.name}")
        item = load_extracted_cache(meta.cache, image_id=obs.image_id, name=obs.name, image_path=meta.path)
        assoc = associate_xy(item.xy, obs.xy, max_pixel_distance=MAX_PIXEL_DISTANCE)
        print(f"associated {obs.name} opencv={item.keypoint_count} accepted={int(np.sum(assoc.accepted_mask))}", flush=True)
        summary = summarize_association(
            opencv_count=item.keypoint_count,
            colmap_reconstructed=len(obs.xy),
            colmap_without_3d=obs.points2d_without_3d,
            result=assoc,
        )
        summary.update({"imageId": obs.image_id, "name": obs.name, "width": item.width, "height": item.height})
        image_bucket_sum = (
            summary["accepted"]
            + summary["twoPxRejected"]
            + summary["mutualRejected"]
            + summary["uniquenessRejected"]
        )
        if image_bucket_sum != summary["opencvFeaturesTotal"]:
            payload = {
                "wallId": wall_id,
                "gate": "3C",
                "stage": "association",
                "gateResult": "STOP",
                "errors": [
                    f"{obs.name}: accepted+noNeighborWithin2px+nonMutual+uniquenessRejected="
                    f"{image_bucket_sum} != {summary['opencvFeaturesTotal']}"
                ],
                "opencv": provenance,
                "incomingUnchanged": snapshot_hashes(incoming) == before,
            }
            write_json(dest / "gate3c_stop.json", payload)
            return payload
        per_image_reports.append(summary)
        for key in totals:
            totals[key] += int(summary[key]) if key != "opencvFeaturesTotal" else int(summary["opencvFeaturesTotal"])
        totals["opencvFeaturesTotal"] = sum(s["opencvFeaturesTotal"] for s in per_image_reports)
        _merge_hist(hist, summary["nearestDistanceHistogram"])
        if len(assoc.opencv_index) == 0:
            continue
        wall_xyz = apply_s_wall_colmap(obs.colmap_xyz[assoc.colmap_index], sim3)
        desc = item.descriptors[assoc.opencv_index]
        descriptors_rows.append(desc)
        for local_i, ocv_i, c_i, dist in zip(
            range(len(assoc.opencv_index)),
            assoc.opencv_index.tolist(),
            assoc.colmap_index.tolist(),
            assoc.distance.tolist(),
        ):
            landmark_rows.append(
                {
                    "index": index,
                    "referenceImageID": obs.image_id,
                    "referenceImageName": obs.name,
                    "referenceKeypointX": float(item.xy[ocv_i, 0]),
                    "referenceKeypointY": float(item.xy[ocv_i, 1]),
                    "point3DID": int(obs.point3d_ids[c_i]),
                    "colmapXYZ": [float(v) for v in obs.colmap_xyz[c_i]],
                    "wallLocalXYZ": [float(v) for v in wall_xyz[local_i]],
                    "associationDistancePx": float(dist),
                }
            )
            index += 1

    bucket_sum = (
        totals["accepted"]
        + totals["twoPxRejected"]
        + totals["mutualRejected"]
        + totals["uniquenessRejected"]
    )
    total_kp = totals["opencvFeaturesTotal"]
    buckets_closed = bucket_sum == total_kp
    if not buckets_closed:
        payload = {
            "wallId": wall_id,
            "gate": "3C",
            "stage": "association",
            "gateResult": "STOP",
            "humanReviewRequired": True,
            "errors": [
                "association buckets do not close: "
                f"accepted({totals['accepted']}) + noNeighborWithin2px({totals['twoPxRejected']}) + "
                f"nonMutual({totals['mutualRejected']}) + uniquenessRejected({totals['uniquenessRejected']}) "
                f"= {bucket_sum} != totalOpenCVKeypoints {total_kp}"
            ],
            "opencv": provenance,
            "incomingUnchanged": snapshot_hashes(incoming) == before,
        }
        write_json(dest / "gate3c_stop.json", payload)
        return payload

    descriptors = np.concatenate(descriptors_rows, axis=0) if descriptors_rows else np.zeros((0, DESCRIPTOR_DIM), dtype=np.float32)
    per_p3d = Counter(int(r["point3DID"]) for r in landmark_rows)
    desc_per = list(per_p3d.values())
    database_stats = {
        "referenceImages": len(observations),
        "nativeResolution": (
            f"{observations[0].width}×{observations[0].height}" if observations else None
        ),
        "opencvFeaturesTotal": totals["opencvFeaturesTotal"],
        "acceptedAssociatedDescriptors": len(landmark_rows),
        "uniquePoint3D": len(per_p3d),
        "descriptorRows": int(len(descriptors)),
        "descriptorMemoryBytes": int(len(descriptors) * DESCRIPTOR_DIM * 4),
        "descriptorsPerPoint3D": _percentiles(desc_per),
        "sift": {
            "implementation": "opencv",
            "opencvVersion": PINNED_OPENCV_VERSION,
            "opencvCommit": PINNED_OPENCV_COMMIT,
            "nfeatures": SIFT_NFEATURES,
            "nOctaveLayers": SIFT_N_OCTAVE_LAYERS,
            "contrastThreshold": SIFT_CONTRAST_THRESHOLD,
            "edgeThreshold": SIFT_EDGE_THRESHOLD,
            "sigma": SIFT_SIGMA,
            "descriptorDim": DESCRIPTOR_DIM,
            "descriptorDtype": "float32",
            "descriptorRowMajor": True,
        },
        "grayscaleNote": GRAYSCALE_NOTE,
    }
    association_report = {
        "wallId": wall_id,
        "maxPixelDistance": MAX_PIXEL_DISTANCE,
        "radiusName": ASSOCIATION_RADIUS_NAME,
        "usedDescriptorDistanceToColmap": False,
        "usedScale": False,
        "usedOrientation": False,
        "usedOctave": False,
        **totals,
        "totalOpenCVKeypoints": total_kp,
        "noNeighborWithin2px": totals["twoPxRejected"],
        "nonMutual": totals["mutualRejected"],
        "uniquenessRejected": totals["uniquenessRejected"],
        "noPoint3DObservation": totals["colmapPoints2DWithout3D"],
        "keypointBucketSum": bucket_sum,
        "keypointBucketsClosed": True,
        "no3DRejected": totals["colmapPoints2DWithout3D"],
        "associationYield": (totals["accepted"] / totals["opencvFeaturesTotal"]) if totals["opencvFeaturesTotal"] else 0.0,
        "nearestDistanceHistogram": hist,
        "reasonBucketsExclusive": True,
        "no3DNote": (
            "no3DRejected counts COLMAP points2D without POINT3D_ID. "
            "They do not enter the 2px neighbor set."
        ),
        "perImage": per_image_reports,
        "S_wall_colmap_status": sim3.get("status"),
        "xyzAreMeters": False,
        "wallLocalXYZFromExistingValidatedSim3": True,
    }
    reference_images = [
        {
            "id": obs.image_id,
            "name": obs.name,
            "width": obs.width,
            "height": obs.height,
            "colmapImageId": obs.image_id,
            "registered": True,
        }
        for obs in observations
    ]
    opencv_runtime = load_pinned_opencv(root)
    freeze = freeze_artifact(
        dest,
        wall_id=wall_id,
        descriptors=descriptors,
        rows=landmark_rows,
        reference_images=reference_images,
        association_report=association_report,
        database_stats=database_stats,
        opencv_provenance=opencv_runtime,
        sim3=sim3,
        extra={"artifactDiskFiles": ["descriptors.bin", "landmarks.json", "association_report.json", "database_stats.json", "freeze.json"]},
        production_bound=production,
        wall_build_run_id=None if bind is None else bind.run_id,
        colmap_model_fingerprint=None if bind is None else bind.model_fingerprint,
    )
    freeze["artifactDiskBytes"] = int(sum((dest / name).stat().st_size for name in freeze["artifactDiskFiles"] if (dest / name).is_file()))
    write_json(dest / "freeze.json", freeze)

    frozen = load_frozen(dest)
    freeze_identity = {
        "artifactSha256": freeze["descriptorsSha256"],
        "landmarksSha256": freeze["landmarksSha256"],
        "descriptorRowCount": int(len(frozen["descriptors"])),
        "uniquePoint3DCount": int(len(set(int(x) for x in frozen["point3dIds"].tolist()))) if len(frozen["point3dIds"]) else 0,
        "referenceImageCount": len({int(r["referenceImageID"]) for r in frozen["rows"]}),
        "usedForCompatibility": True,
        "secondReferenceDbForbidden": True,
    }
    write_json(dest / "freeze_identity.json", freeze_identity)
    if freeze_identity["descriptorRowCount"] != freeze["descriptorCount"]:
        payload = {
            "wallId": wall_id,
            "gate": "3C",
            "stage": "freeze",
            "gateResult": "STOP",
            "errors": ["frozen descriptor count does not match freeze.json"],
            "incomingUnchanged": snapshot_hashes(incoming) == before,
        }
        write_json(dest / "gate3c_stop.json", payload)
        return payload

    selection = select_compatibility_images(landmark_rows, extracted, loo_count=2)

    def _hydrate(item):
        if item is None or item.cache is None:
            return item
        print(f"loading query extract {item.name}", flush=True)
        return load_extracted_cache(item.cache, image_id=item.image_id, name=item.name, image_path=item.path)

    same_report = None
    same_img = _hydrate(selection["sameImage"])
    if same_img is not None:
        print(
            f"same-image matching query={same_img.keypoint_count} db={len(frozen['descriptors'])}",
            flush=True,
        )
        same_report = same_image_compatibility(None, frozen, same_img, selection["sameImageReason"])
        write_json(dest / "compatibility_same_image.json", same_report)
    loo_reports = []
    for query_meta in selection["loo"]:
        query = _hydrate(query_meta)
        print(
            f"LOO matching query={query.name} kp={query.keypoint_count} db_before_exclude={len(frozen['descriptors'])}",
            flush=True,
        )
        report = loo_compatibility(None, frozen, query, selection["looReasons"][query.image_id])
        loo_reports.append(report)
    write_json(dest / "compatibility_loo.json", {"queries": loo_reports})

    after = snapshot_hashes(incoming)
    payload = {
        "wallId": wall_id,
        "runId": run_id,
        "gate": "3C",
        "stage": "compatibility_human_review",
        "gateResult": "NEEDS REVIEW",
        "humanReviewRequired": True,
        "stopBeforeSwift": True,
        "productionBound": production,
        "legacyFallback": False if production else None,
        "incomingUnchanged": before == after,
        "opencv": opencv_runtime,
        "referenceDatabase": {
            **database_stats,
            "artifactDiskSize": freeze.get("artifactDiskBytes"),
            "artifactSha256": freeze.get("descriptorsSha256"),
            "landmarksSha256": freeze.get("landmarksSha256"),
            "freezeIdentity": freeze_identity,
        },
        "association": {
            "maxPixelDistance": MAX_PIXEL_DISTANCE,
            "accepted": totals["accepted"],
            "noNeighborWithin2px": totals["twoPxRejected"],
            "nonMutual": totals["mutualRejected"],
            "uniquenessRejected": totals["uniquenessRejected"],
            "noPoint3DObservation": totals["colmapPoints2DWithout3D"],
            "totalOpenCVKeypoints": total_kp,
            "keypointBucketsClosed": True,
            "mutualRejected": totals["mutualRejected"],
            "twoPxRejected": totals["twoPxRejected"],
            "no3DRejected": totals["colmapPoints2DWithout3D"],
            "yield": association_report["associationYield"],
            "nearestDistanceHistogram": hist,
        },
        "compatibilitySameImage": same_report,
        "compatibilityLOO": loo_reports,
        "runtimeConfigurationPlanned": {
            "resolution": "960×720",
            "sift": "frozen Gate 3B baseline",
            "matcher": "BF / L2",
            "candidateK": CANDIDATE_K,
            "minDistinctPoint3DForRatio": MIN_DISTINCT_POINT3D_FOR_RATIO,
            "ratioThreshold": RATIO_THRESHOLD,
            "queue": "none / skip-if-busy",
        },
        "freeze": freeze,
        "extract": extract_summary,
        "problems": [],
    }
    if same_report and same_report.get("nearZeroUniquePoint3D"):
        payload["problems"].append("same-image acceptedUniquePoint3D is 0 on a large query set")
        payload["gateResult"] = "STOP"
    for report in loo_reports:
        if report.get("queryImageRowsExcluded", 0) <= 0:
            payload["problems"].append(f"LOO excluded 0 rows for {report.get('queryImageName')}")
            payload["gateResult"] = "STOP"
        if report.get("nearZeroUniquePoint3D"):
            payload["problems"].append(f"LOO acceptedUniquePoint3D near 0 for {report.get('queryImageName')}")
            payload["gateResult"] = "STOP"
    write_json(dest / "gate3c_compatibility_review.json", payload)
    _write_markdown(dest, payload)
    return payload


def _write_markdown(dest: Path, payload: dict) -> None:
    same = payload.get("compatibilitySameImage") or {}
    loo = payload.get("compatibilityLOO") or []
    assoc = payload.get("association") or {}
    db = payload.get("referenceDatabase") or {}
    hist = assoc.get("nearestDistanceHistogram") or {}
    lines = [
        "# Gate 3C compatibility review",
        "",
        "STOP after step ⑦. Do not start Swift until this report is accepted.",
        "",
        f"Gate result: {payload.get('gateResult')}",
        "",
        "## OpenCV provenance",
        f"- Mac version: {(payload.get('opencv') or {}).get('cvVersion')}",
        f"- tag: {PINNED_OPENCV_VERSION}",
        f"- commit: {PINNED_OPENCV_COMMIT}",
        f"- status: {(payload.get('opencv') or {}).get('status')}",
        "",
        "## Reference database",
        f"- reference images: {db.get('referenceImages')}",
        f"- native resolution: {db.get('nativeResolution')}",
        f"- OpenCV features: {db.get('opencvFeaturesTotal')}",
        f"- accepted associated descriptors: {db.get('acceptedAssociatedDescriptors')}",
        f"- unique Point3D: {db.get('uniquePoint3D')}",
        f"- freeze identity: {db.get('freezeIdentity')}",
        f"- descriptor rows: {db.get('descriptorRows')}",
        f"- memory size: {db.get('descriptorMemoryBytes')}",
        f"- artifact disk size: {db.get('artifactDiskSize')}",
        f"- artifact SHA-256: {db.get('artifactSha256')}",
        f"- descriptors/Point3D: {db.get('descriptorsPerPoint3D')}",
        "",
        "## Association (2.0 px, exclusive buckets)",
        f"- accepted: {assoc.get('accepted')}",
        f"- mutual rejected: {assoc.get('mutualRejected')}",
        f"- uniqueness rejected: {assoc.get('uniquenessRejected')}",
        f"- 2px rejected: {assoc.get('twoPxRejected')}",
        f"- no-3D (COLMAP points2D without POINT3D_ID): {assoc.get('no3DRejected')}",
        f"- yield: {assoc.get('yield')}",
        f"- histogram 0-1 / 1-2 / 2-3 / 3-5 / >5: {hist.get('0_1')} / {hist.get('1_2')} / {hist.get('2_3')} / {hist.get('3_5')} / {hist.get('gt_5')}",
        "",
        "## Same-image",
        f"- query: {same.get('queryImageName')} ({same.get('queryImageId')})",
        f"- reason: {same.get('selectionReason')}",
        f"- query kp: {same.get('queryKp')}",
        f"- acceptedAfterRatio: {same.get('acceptedAfterRatio')}",
        f"- acceptedUniquePoint3D: {same.get('acceptedUniquePoint3D')}",
        f"- insufficientDistinctPoint3D: {same.get('insufficientDistinctPoint3D')}",
        f"- ratioRejected: {same.get('ratioRejected')}",
        f"- self-image winning fraction: {same.get('acceptedAfterRatioSelfImageFraction')}",
        f"- distance: {same.get('distanceDistribution')}",
        f"- ratio: {same.get('ratioDistribution')}",
        "",
        "## LOO cross-view",
    ]
    for item in loo:
        lines.extend(
            [
                f"### {item.get('queryImageName')}",
                f"- reason: {item.get('selectionReason')}",
                f"- rows excluded: {item.get('queryImageRowsExcluded')}",
                f"- query kp: {item.get('queryKp')}",
                f"- acceptedAfterRatio: {item.get('acceptedAfterRatio')}",
                f"- acceptedUniquePoint3D: {item.get('acceptedUniquePoint3D')}",
                f"- insufficientDistinctPoint3D: {item.get('insufficientDistinctPoint3D')}",
                f"- ratioRejected: {item.get('ratioRejected')}",
                f"- winning image is query: {item.get('winningImageIsQuery')}",
                f"- winning image is other: {item.get('winningImageNotQuery')}",
                f"- distance: {item.get('distanceDistribution')}",
                f"- ratio: {item.get('ratioDistribution')}",
                "",
            ]
        )
    lines.extend(["## Problems", *[f"- {p}" for p in payload.get("problems") or ["(none listed)"]]])
    (dest / "compatibility_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
