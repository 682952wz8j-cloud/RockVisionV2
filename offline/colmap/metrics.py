"""Parse COLMAP database + sparse reconstruction quality metrics."""

from __future__ import annotations

from pathlib import Path
from statistics import median

COLMAP_MAX_IMAGE_ID = 2147483647


def split_pair_id(pair_id: int) -> tuple[int, int]:
    return int(pair_id) // COLMAP_MAX_IMAGE_ID, int(pair_id) % COLMAP_MAX_IMAGE_ID


def unpack_pair_table(payload) -> tuple[list, list]:
    if payload is None:
        return [], []
    if isinstance(payload, tuple) and len(payload) == 2:
        return list(payload[0]), list(payload[1])
    if isinstance(payload, list):
        return [], payload
    return [], []


def _stats(values: list[float] | list[int]) -> dict:
    if not values:
        return {"min": None, "median": None, "max": None, "mean": None, "count": 0}
    nums = [float(v) for v in values]
    return {
        "min": min(nums),
        "median": float(median(nums)),
        "max": max(nums),
        "mean": sum(nums) / len(nums),
        "count": len(nums),
    }


def keypoints_from_database(database) -> dict[str, dict]:
    images = database.read_all_images()
    out: dict[str, dict] = {}
    for image in images:
        image_id = image.image_id
        name = image.name
        key_count = database.num_keypoints_for_image(image_id) if database.exists_keypoints(image_id) else 0
        desc_count = database.num_descriptors_for_image(image_id) if database.exists_descriptors(image_id) else 0
        out[name] = {
            "imageId": int(image_id),
            "name": name,
            "keypoints": int(key_count),
            "descriptors": int(desc_count),
            "success": key_count > 0 and desc_count > 0,
        }
    return out


def matching_from_database(database) -> dict:
    _, match_rows = unpack_pair_table(database.read_all_matches())
    _, geom_rows = unpack_pair_table(database.read_two_view_geometries())
    raw_pair_counts: list[int] = []
    for pair_matches in match_rows:
        try:
            raw_pair_counts.append(len(pair_matches))
        except TypeError:
            raw_pair_counts.append(0)
    inlier_counts: list[int] = []
    for geom in geom_rows:
        inliers = getattr(geom, "inlier_matches", None)
        inlier_counts.append(len(inliers) if inliers is not None else 0)
    return {
        "attemptedPairs": int(database.num_matched_image_pairs()),
        "verifiedPairs": int(database.num_verified_image_pairs()),
        "rawMatches": _stats(raw_pair_counts),
        "inliers": _stats(inlier_counts),
        "totalInlierMatches": int(database.num_inlier_matches()),
    }


def observations_from_reconstruction(reconstruction) -> dict:
    per_image: dict[str, int] = {}
    for image_id in reconstruction.reg_image_ids():
        image = reconstruction.image(image_id)
        count = 0
        for point in image.points2D:
            if point.has_point3D():
                count += 1
        per_image[image.name] = count
    values = list(per_image.values())
    return {
        "perImage": per_image,
        "imagesWithObservations": sum(1 for value in values if value > 0),
        "total": int(sum(values)),
        "stats": _stats(values),
    }


def sparse_from_reconstruction(reconstruction) -> dict:
    track_lengths = []
    errors = []
    for point_id in reconstruction.point3D_ids():
        point = reconstruction.point3D(point_id)
        track_lengths.append(int(point.track.length()))
        errors.append(float(point.error))
    cameras = []
    camera_map = reconstruction.cameras
    camera_items = camera_map.items() if hasattr(camera_map, "items") else ((cam.camera_id, cam) for cam in camera_map)
    for camera_id, camera in camera_items:
        cameras.append(
            {
                "cameraId": int(camera_id),
                "model": str(camera.model),
                "width": int(camera.width),
                "height": int(camera.height),
                "params": [float(v) for v in camera.params],
                "paramsInfo": str(camera.params_info),
                "hasPriorFocalLength": bool(camera.has_prior_focal_length),
                "focalLength": float(camera.focal_length),
            }
        )
    return {
        "numCameras": int(reconstruction.num_cameras()),
        "registeredImages": int(reconstruction.num_reg_images()),
        "points3D": int(reconstruction.num_points3D()),
        "observations": int(reconstruction.compute_num_observations()),
        "meanTrackLength": float(reconstruction.compute_mean_track_length()),
        "trackLength": _stats(track_lengths),
        "reprojectionError": {
            "mean": float(reconstruction.compute_mean_reprojection_error()),
            **_stats(errors),
        },
        "meanObservationsPerRegImage": float(reconstruction.compute_mean_observations_per_reg_image()),
        "cameras": cameras,
    }


def registered_names(reconstruction) -> set[str]:
    names = set()
    for image_id in reconstruction.reg_image_ids():
        names.add(reconstruction.image(image_id).name)
    return names


def decide_gate_result(
    *,
    source_count: int,
    registered: int,
    models: int,
    points3d: int,
    observations: int,
    median_track: float | None,
    median_reproj: float | None,
    incoming_unchanged: bool,
    errors: list[str],
) -> str:
    if errors or not incoming_unchanged or source_count == 0 or registered == 0 or points3d == 0:
        return "FAIL"
    rate = registered / source_count if source_count else 0.0
    if rate < 0.90:
        return "NEEDS REVIEW"
    if models > 1:
        return "NEEDS REVIEW"
    if points3d < 100 or observations < 500:
        return "NEEDS REVIEW"
    if median_track is None or median_track < 2.0:
        return "NEEDS REVIEW"
    if median_reproj is None or median_reproj > 4.0:
        return "NEEDS REVIEW"
    return "PASS"
