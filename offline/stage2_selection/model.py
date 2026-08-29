"""Model spatial metadata is a TerraSpatialFrame copy, not a geometry pointer.

terra_ply adjacency is no longer used as a selection rule.
Approved provenance is TerraExportRoot + agreeing ModelMetadata SRS/SRSOrigin.
PLY geometry is a cross-check capability (usedInFit=False), not frame provenance.
origin_compatible_with_mrk remains a spatial sanity check, not provenance.
"""

from __future__ import annotations

from .states import SelectionStatus


def apply_frozen_identity_regression(
    terra_result: dict,
    evidence: dict | None,
) -> tuple[dict, bool]:
    """Record that frozen A1/A2 identities match generic Terra selection.

    This does not select sources. Generic Terra rules must already have selected
    the same metadata copy and PLY. It is not a wall_id branch.
    """
    if not evidence:
        return terra_result, False
    meta_path = evidence.get("metadata_xml_relative_path")
    ply_path = evidence.get("ply_relative_path")
    selected_meta = terra_result.get("selectedModelSpatialMetadata") or {}
    selected_ply = terra_result.get("selectedModelSource") or {}
    if not meta_path or not ply_path:
        return terra_result, False
    if selected_meta.get("relativePath") != meta_path:
        return terra_result, False
    if selected_ply.get("relativePath") != ply_path:
        return terra_result, False
    if terra_result.get("status") != SelectionStatus.AUTO_PASS.value:
        return terra_result, False
    return terra_result, True
