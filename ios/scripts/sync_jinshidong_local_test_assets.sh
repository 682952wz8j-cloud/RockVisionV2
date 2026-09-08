#!/bin/sh
# Copy Jinshidong local-test binaries into the iOS resource folder.
# Manifest and route JSON are committed. Binaries stay gitignored, like DevelopmentFixture.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$ROOT/ios/RockVision/Resources/JinshidongLocalTest"
PKG="$ROOT/offline/work/wall_jinshidong_01/wall_build/wb_20260906T024519Z_6e08b5ff/localization_package"
ROUTES="$ROOT/offline/work/wall_jinshidong_01/route_ingestion/bound_wb_20260906T024519Z_6e08b5ff/ios_local_test"
mkdir -p "$DEST"
if [ ! -f "$PKG/assets/stage3-descriptors" ] || [ ! -f "$PKG/assets/stage3-landmarks" ] || [ ! -f "$PKG/assets/s-wall-colmap" ]; then
  echo "missing jinshidong localization_package assets" >&2
  exit 1
fi
cp "$PKG/package.json" "$DEST/package.json"
cp "$PKG/assets/stage3-descriptors" "$DEST/descriptors.bin"
cp "$PKG/assets/stage3-landmarks" "$DEST/landmarks.json"
cp "$PKG/assets/s-wall-colmap" "$DEST/jinshidong_s_wall_colmap.json"
cp "$ROUTES/route_bundle.json" "$DEST/route_bundle.json"
python3 - "$DEST/route_bundle.json" <<'PY'
from pathlib import Path
import json, sys
path = Path(sys.argv[1])
bundle = json.loads(path.read_text())
for row in bundle.get("routes", []):
    fixture = row.get("fixturePath", "")
    row["fixturePath"] = Path(fixture).name
path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n")
PY
cp "$ROUTES/jinshidong_lucky_baby.json" "$DEST/jinshidong_lucky_baby.json"
cp "$ROUTES/jinshidong_shui_tai_shen.json" "$DEST/jinshidong_shui_tai_shen.json"
cp "$ROUTES/jinshidong_mei_xiang_hao.json" "$DEST/jinshidong_mei_xiang_hao.json"
cp "$ROUTES/jinshidong_long_zhua_shou.json" "$DEST/jinshidong_long_zhua_shou.json"
echo "synced JinshidongLocalTest assets"
