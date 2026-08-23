#!/bin/zsh
# Rebuild the pinned OpenCV iOS XCFramework. Do not float the tag.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
export PATH="${HOME}/Library/Python/3.9/bin:/usr/bin:/bin:${PATH}"
export IPHONEOS_DEPLOYMENT_TARGET=13.0
SRC="${ROOT}/ios/Vendor/OpenCV/opencv"
OUT="${ROOT}/ios/Vendor/OpenCV/build"
TAG="4.14.0"
COMMIT="0654a42e19215ef25b1d367d822f3c630447e7c7"

if [[ ! -d "${SRC}/.git" ]]; then
  git clone --branch "${TAG}" --depth 1 https://github.com/opencv/opencv.git "${SRC}"
fi
git -C "${SRC}" fetch --depth 1 origin tag "${TAG}" || true
git -C "${SRC}" checkout "${COMMIT}"
# Official script requires git branch --show-current (detached tag fails).
if [[ -z "$(git -C "${SRC}" branch --show-current)" ]]; then
  git -C "${SRC}" switch -c "rockvision-pin-${TAG}"
fi

python3 "${SRC}/platforms/apple/build_xcframework.py" \
  --out "${OUT}" \
  --iphoneos_archs arm64 \
  --iphonesimulator_archs arm64 \
  --build_only_specified_archs \
  --framework_name opencv2 \
  --without objc \
  --without video \
  --without videoio \
  --without highgui \
  --without dnn \
  --without ml \
  --without objdetect \
  --without photo \
  --without stitching \
  --without gapi \
  --without python3 \
  --without java \
  --without js \
  --without ts \
  --without world \
  --without imgcodecs \
  --disable-swift \
  --iphoneos_deployment_target 13.0

rm -rf "${ROOT}/ios/Vendor/OpenCV/opencv2.xcframework"
cp -R "${OUT}/opencv2.xcframework" "${ROOT}/ios/Vendor/OpenCV/opencv2.xcframework"
echo "Installed ${ROOT}/ios/Vendor/OpenCV/opencv2.xcframework"
