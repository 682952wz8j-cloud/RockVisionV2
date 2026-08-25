#!/usr/bin/env bash
# Build Mac OpenCV 4.14.0 Python bindings from the iOS pinned source commit.
# Does not use pip opencv-python. Does not use the system cv2 5.x.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${ROOT}/ios/Vendor/OpenCV/opencv"
PIN_COMMIT="$(tr -d '[:space:]' < "${ROOT}/ios/Vendor/OpenCV/SOURCE_COMMIT.txt")"
PIN_VERSION="$(awk -F': ' '/^version:/{print $2}' "${ROOT}/ios/Vendor/OpenCV/VERSION.txt" | tr -d '[:space:]')"
VENDOR="${ROOT}/offline/vendor/opencv414"
BUILD="${VENDOR}/build"
INSTALL="${VENDOR}/install"
PYTHON_DST="${VENDOR}/python"
CMAKE="${CMAKE:-${HOME}/Library/Python/3.9/bin/cmake}"
PYTHON="${PYTHON:-/usr/bin/python3}"
JOBS="${JOBS:-8}"

if [[ ! -x "${CMAKE}" ]]; then
  echo "STOP: cmake not found at ${CMAKE}" >&2
  exit 1
fi
if [[ ! -d "${SRC}/.git" ]]; then
  echo "STOP: pinned OpenCV source missing at ${SRC}" >&2
  exit 1
fi

HEAD="$(git -C "${SRC}" rev-parse HEAD)"
if [[ "${HEAD}" != "${PIN_COMMIT}" ]]; then
  echo "STOP: OpenCV source HEAD ${HEAD} != pin ${PIN_COMMIT}" >&2
  exit 1
fi
if [[ "${PIN_COMMIT}" != "0654a42e19215ef25b1d367d822f3c630447e7c7" ]]; then
  echo "STOP: unexpected pin commit ${PIN_COMMIT}" >&2
  exit 1
fi
if [[ "${PIN_VERSION}" != "4.14.0" ]]; then
  echo "STOP: unexpected pin version ${PIN_VERSION}" >&2
  exit 1
fi

mkdir -p "${BUILD}" "${INSTALL}" "${PYTHON_DST}"
NUMPY_INC="$("${PYTHON}" -c 'import numpy; print(numpy.get_include())')"

"${CMAKE}" -S "${SRC}" -B "${BUILD}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${INSTALL}" \
  -DCMAKE_INSTALL_RPATH="@loader_path/../../install/lib;@loader_path" \
  -DCMAKE_BUILD_RPATH="${INSTALL}/lib" \
  -DBUILD_SHARED_LIBS=ON \
  -DBUILD_TESTS=OFF \
  -DBUILD_PERF_TESTS=OFF \
  -DBUILD_EXAMPLES=OFF \
  -DBUILD_DOCS=OFF \
  -DBUILD_opencv_apps=OFF \
  -DBUILD_opencv_python2=OFF \
  -DBUILD_opencv_python3=ON \
  -DBUILD_opencv_java=OFF \
  -DBUILD_opencv_js=OFF \
  -DBUILD_opencv_objc=OFF \
  -DBUILD_opencv_world=OFF \
  -DBUILD_opencv_dnn=OFF \
  -DBUILD_opencv_ml=OFF \
  -DBUILD_opencv_objdetect=OFF \
  -DBUILD_opencv_photo=OFF \
  -DBUILD_opencv_stitching=OFF \
  -DBUILD_opencv_video=OFF \
  -DBUILD_opencv_videoio=OFF \
  -DBUILD_opencv_gapi=OFF \
  -DBUILD_opencv_highgui=OFF \
  -DBUILD_opencv_calib3d=ON \
  -DBUILD_opencv_flann=ON \
  -DBUILD_opencv_features2d=ON \
  -DBUILD_opencv_imgcodecs=ON \
  -DBUILD_opencv_imgproc=ON \
  -DBUILD_opencv_core=ON \
  -DWITH_CUDA=OFF \
  -DWITH_OPENCL=OFF \
  -DWITH_FFMPEG=OFF \
  -DWITH_GSTREAMER=OFF \
  -DWITH_GTK=OFF \
  -DWITH_QT=OFF \
  -DWITH_VTK=OFF \
  -DWITH_PROTOBUF=OFF \
  -DWITH_WEBP=OFF \
  -DWITH_TIFF=OFF \
  -DWITH_OPENEXR=OFF \
  -DWITH_JASPER=OFF \
  -DWITH_PNG=ON \
  -DWITH_JPEG=ON \
  -DBUILD_JPEG=ON \
  -DBUILD_PNG=ON \
  -DBUILD_ZLIB=ON \
  -DWITH_1394=OFF \
  -DWITH_ITT=OFF \
  -DWITH_IPP=OFF \
  -DWITH_TBB=OFF \
  -DWITH_EIGEN=OFF \
  -DWITH_LAPACK=OFF \
  -DWITH_ADE=OFF \
  -DPYTHON3_EXECUTABLE="${PYTHON}" \
  -DPYTHON3_NUMPY_INCLUDE_DIRS="${NUMPY_INC}" \
  -DOPENCV_PYTHON3_INSTALL_PATH="${PYTHON_DST}"

"${CMAKE}" --build "${BUILD}" --parallel "${JOBS}"
"${CMAKE}" --install "${BUILD}"

BIN="${VENDOR}/bin"
mkdir -p "${BIN}"
clang++ -std=c++17 \
  -I "${INSTALL}/include/opencv4" \
  "${ROOT}/offline/reference_matching/sift_extract.cpp" \
  -L "${INSTALL}/lib" \
  -lopencv_core -lopencv_imgproc -lopencv_imgcodecs -lopencv_features2d \
  -Wl,-rpath,"${INSTALL}/lib" \
  -o "${BIN}/rv_sift_extract"

clang++ -std=c++17 \
  -I "${INSTALL}/include/opencv4" \
  "${ROOT}/offline/pnp/pnp.cpp" \
  -L "${INSTALL}/lib" \
  -lopencv_core -lopencv_calib3d -lopencv_imgproc -lopencv_features2d -lopencv_flann \
  -Wl,-rpath,"${INSTALL}/lib" \
  -o "${BIN}/rv_pnp"

VERSION_OUT="$("${BIN}/rv_sift_extract" --version)"
echo "${VERSION_OUT}"
"${PYTHON}" - << PY
import json, subprocess
from pathlib import Path
version = subprocess.check_output(["${BIN}/rv_sift_extract", "--version"], text=True)
cv = None
for line in version.splitlines():
    if line.startswith("cvVersion="):
        cv = line.split("=", 1)[1].strip()
payload = {
    "cvVersion": cv,
    "sourceCommit": "${HEAD}",
    "sourceTag": "4.14.0",
    "sourcePath": "${SRC}",
    "cli": "${BIN}/rv_sift_extract",
    "installPrefix": "${INSTALL}",
    "binding": "mac-cli-linked-to-pinned-dylibs",
    "versionOutput": version,
}
(Path("${VENDOR}") / "PROVENANCE.json").write_text(json.dumps(payload, indent=2) + "\n")
print(json.dumps(payload, indent=2))
if cv != "4.14.0":
    raise SystemExit(f"STOP: CLI cvVersion={cv}")
print("Mac OpenCV 4.14.0 CLI provenance written")
PY
