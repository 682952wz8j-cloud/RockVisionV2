#!/bin/sh
# Copy the frozen Gate 3C baseline_2px artifact into the iOS development fixture.
# Binaries stay gitignored. This is not a Wall Package.
set -euo pipefail

ROOT="$(CDPATH= cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/offline/work/wall_jiulongfeng_01/reference_matching/baseline_2px"
DEST="$ROOT/ios/RockVision/Resources/DevelopmentFixture"
MANIFEST="$DEST/manifest.json"

if [ ! -f "$SRC/descriptors.bin" ] || [ ! -f "$SRC/landmarks.json" ]; then
  echo "missing frozen artifact at $SRC" >&2
  exit 1
fi
if [ ! -f "$MANIFEST" ]; then
  echo "missing $MANIFEST" >&2
  exit 1
fi

mkdir -p "$DEST"
cp -c "$SRC/descriptors.bin" "$DEST/descriptors.bin"
cp -c "$SRC/landmarks.json" "$DEST/landmarks.json"

python3 - "$DEST" "$MANIFEST" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

dest = Path(sys.argv[1])
manifest = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
checks = {
    "descriptors.bin": (manifest["descriptorsSha256"], manifest["descriptorsBytes"]),
    "landmarks.json": (manifest["landmarksSha256"], manifest["landmarksBytes"]),
}
for name, (digest, size) in checks.items():
    path = dest / name
    actual_size = path.stat().st_size
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_size != size:
        raise SystemExit(f"{name} size {actual_size} != {size}")
    if actual != digest:
        raise SystemExit(f"{name} SHA-256 {actual} != {digest}")
    print(f"{name} ok bytes={actual_size} sha256={actual}")
print("development fixture installed")
PY
