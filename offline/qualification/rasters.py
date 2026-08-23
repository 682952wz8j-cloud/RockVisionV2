from __future__ import annotations

from pathlib import Path

from .status import ProvenanceStatus, claim

MISSING = "missing"


def raster_bounds(width: int, height: int, params: dict) -> dict:
    a = float(params["pixelSizeX"])
    d = float(params["rotationY"])
    b = float(params["rotationX"])
    e = float(params["pixelSizeY"])
    c = float(params["upperLeftX"])
    f = float(params["upperLeftY"])
    # World-file (c,f) is center of the upper-left pixel.
    corners = []
    for col, row in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        x = c + col * a + row * b
        y = f + col * d + row * e
        corners.append((x, y))
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return {
        "pixelSizeX": a,
        "pixelSizeY": e,
        "rotationX": b,
        "rotationY": d,
        "minX": min(xs),
        "maxX": max(xs),
        "minY": min(ys),
        "maxY": max(ys),
        "widthMApprox": abs(max(xs) - min(xs)),
        "heightMApprox": abs(max(ys) - min(ys)),
        "cornerCenters": [{"x": x, "y": y} for x, y in corners],
    }


def qualify_raster(record: dict, sidecar_index: dict[str, dict]) -> dict:
    rel = record["relativePath"]
    stem = Path(record["filename"]).stem
    parent = str(Path(rel).parent)
    image = record.get("image") or {}
    width = image.get("pixelWidth")
    height = image.get("pixelHeight")
    tfw = sidecar_index.get(f"{parent}/{stem}.tfw".replace("\\", "/"))
    prj = sidecar_index.get(f"{parent}/{stem}.prj".replace("\\", "/"))
    # sidecar keys are relative paths
    tfw = tfw or next((v for k, v in sidecar_index.items() if k.endswith(f"/{stem}.tfw") or k == f"{stem}.tfw"), None)
    prj = prj or next((v for k, v in sidecar_index.items() if k.endswith(f"{stem}.prj")), None)

    crs = MISSING
    epsg = MISSING
    if prj and prj.get("parsed"):
        crs = prj.get("crsName", MISSING)
        epsg = prj.get("epsg", MISSING)
    bounds = MISSING
    if isinstance(width, int) and isinstance(height, int) and tfw and tfw.get("parsed") and tfw.get("parameters"):
        bounds = raster_bounds(width, height, tfw["parameters"])

    kind = "otherGeospatialRaster"
    name = record["filename"].lower()
    if name.startswith("dsm") or name == "dsm.tif":
        kind = "dsm"
    elif "gsd" in name:
        kind = "gsdOrOverview"
    elif name.startswith("result") or "dom" in name or "ortho" in name:
        kind = "orthophoto"

    return {
        "relativePath": rel,
        "kind": kind,
        "width": width,
        "height": height,
        "crsName": crs,
        "epsg": epsg,
        "bounds": bounds,
        "tfwParsed": bool(tfw and tfw.get("parsed")),
        "claims": [
            claim(
                ProvenanceStatus.PROVEN if epsg != MISSING else ProvenanceStatus.UNKNOWN,
                f"{record['filename']} CRS",
                [f"PRJ EPSG={epsg}", f"CRS name={crs}"],
            )
        ],
    }
