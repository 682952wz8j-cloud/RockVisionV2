"""Selected-source parameters consumed by validated Stage 2 math wrappers."""

from __future__ import annotations

from dataclasses import dataclass

from .states import OUTPUT_FRAME, WALLMETRICMETERS_PROVENANCE


@dataclass(frozen=True)
class Stage2SelectedSources:
    wall_id: str
    image_relative_paths: tuple[str, ...]
    image_dir_relative: str
    mrk_relative_path: str
    metadata_xml_relative_path: str
    srs: str
    srs_origin: tuple[float, float, float]
    ply_relative_path: str | None
    association_method: str
    association_rule: str
    height_sfm_geo_desc: str | None = None
    height_legacy_mrk: str | None = None
    output_frame: str = OUTPUT_FRAME
    wall_metric_meters_provenance: str = WALLMETRICMETERS_PROVENANCE


def sources_from_selection(artifact: dict) -> Stage2SelectedSources | None:
    if artifact.get("selectionStatus") != "AUTO_PASS":
        return None
    capture = artifact.get("selectedCapture") or {}
    mrk = artifact.get("selectedMRKSource") or {}
    meta = artifact.get("selectedModelSpatialMetadata") or {}
    origin = meta.get("srsOrigin") or artifact.get("selectedSRSOrigin")
    if not capture or not mrk or not meta or not origin:
        return None
    images = tuple(capture.get("memberRelativePaths") or ())
    if not images:
        return None
    parents = {path.rsplit("/", 1)[0] if "/" in path else "." for path in images}
    if len(parents) != 1:
        return None
    ply = (artifact.get("selectedModelSource") or {}).get("relativePath")
    return Stage2SelectedSources(
        wall_id=str(artifact.get("wallId") or ""),
        image_relative_paths=images,
        image_dir_relative=next(iter(parents)),
        mrk_relative_path=str(mrk["relativePath"]),
        metadata_xml_relative_path=str(meta["relativePath"]),
        srs=str(artifact.get("selectedSRS") or meta.get("srs") or ""),
        srs_origin=(float(origin[0]), float(origin[1]), float(origin[2])),
        ply_relative_path=str(ply) if ply else None,
        association_method=str(mrk.get("associationMethod") or ""),
        association_rule=str(mrk.get("associationRule") or ""),
        height_sfm_geo_desc=None,
        height_legacy_mrk=None,
    )
