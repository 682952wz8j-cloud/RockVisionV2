# OpenCV iOS XCFramework build (Gate 3A)

Pinned. Do not float to a newer OpenCV automatically.

## Selection (2026-08-23)

Current stable **OpenCV 4.x** at Gate 3A: **4.14.0** (2026-07-19).
OpenCV 5.0.0 exists; this project stays on 4.x as specified.

| Item | Value |
|------|--------|
| Source | https://github.com/opencv/opencv |
| Version | 4.14.0 |
| Git tag | `4.14.0` |
| Source commit | `0654a42e19215ef25b1d367d822f3c630447e7c7` |
| Tool | official `platforms/apple/build_xcframework.py` |
| Device | iPhoneOS `arm64` |
| Simulator | iOS Simulator `arm64` |
| Contrib / nonfree / xfeatures2d | **off** |
| Required modules | `core`, `imgproc`, `features2d`, `calib3d` (plus dependency `flann`) |
| Explicitly disabled | objc, video, videoio, highgui, dnn, ml, objdetect, photo, stitching, gapi, python3, java, js, ts, world, imgcodecs, Swift wrappers |
| CMake | 3.18.5+ required by the Apple script; this build used CMake 4.4.2 (pip) |
| Xcode | 26.6 (build 17F113), iOS SDK 26.5 |
| Deployment target (OpenCV) | 13.0 |
| Output (canonical) | `ios/Vendor/OpenCV/opencv2.xcframework` |
| Artifact SHA-256 | `ec10b74646b0cd51e3897c3ddbcfeb3c0ab3ba931ca374aaa9a6b19efd3c780a` (zip of `opencv2.xcframework`) |

Verified at selection:

- Apple XCFramework tooling present (`platforms/apple/build_xcframework.py`)
- iPhone `arm64` and Simulator `arm64` supported
- `cv::SIFT::create()` in main `features2d` (no contrib)
- `cv::solvePnPRansac()` in `calib3d`

Do **not** download or drop in the GitHub “ios-framework.zip” prebuilt.

## Reproduce

```text
# cmake >= 3.18.5 must be on PATH
export PATH="$HOME/Library/Python/3.9/bin:$PATH"

git clone --branch 4.14.0 --depth 1 https://github.com/opencv/opencv.git ios/Vendor/OpenCV/opencv
# detached tags break the official script (git branch --show-current).
git -C ios/Vendor/OpenCV/opencv switch -c rockvision-pin-4.14.0
test "$(git -C ios/Vendor/OpenCV/opencv rev-parse HEAD)" = 0654a42e19215ef25b1d367d822f3c630447e7c7

# or: ios/Vendor/OpenCV/build_opencv_xcframework.sh
python3 ios/Vendor/OpenCV/opencv/platforms/apple/build_xcframework.py \
  --out ios/Vendor/OpenCV/build \
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

cp -R ios/Vendor/OpenCV/build/opencv2.xcframework ios/Vendor/OpenCV/opencv2.xcframework
ditto -c -k --keepParent ios/Vendor/OpenCV/opencv2.xcframework /tmp/opencv2.xcframework.zip
shasum -a 256 /tmp/opencv2.xcframework.zip
```

Write tag, commit, command, archs, modules, Xcode/OS, and the zip SHA-256 into `ios/Vendor/OpenCV/VERSION.txt`.
Write the commit into `ios/Vendor/OpenCV/SOURCE_COMMIT.txt`.

The OpenCV git clone, `ios/Vendor/OpenCV/build/`, and
`ios/Vendor/OpenCV/opencv2.xcframework` are gitignored. After clone,
rebuild with `ios/Vendor/OpenCV/build_opencv_xcframework.sh` and verify
the zip SHA-256 in `VERSION.txt`. Pin files (`VERSION.txt`,
`SOURCE_COMMIT.txt`, the build script, `opencv2.xcframework.sha256`) are
the source of truth.

Without a local XCFramework, Xcode cannot link the `RockVision` app or
tests. That is expected on a clean clone.

## Xcode linkage

App target `RockVision`:

- `opencv2.xcframework` (Frameworks)
- `libc++`, `Accelerate`, `CoreVideo`, `CoreMedia`, `ARKit`, `RealityKit`
- C++17, Objective-C++ for `Bridge/OpenCV/*.mm`
- Bridging header `RockVision/RockVision-Bridging-Header.h`
- Swift must not `#include <opencv2/...>`

## Runtime policy

This XCFramework is used only through `OpenCVBridge`.
Gate 3A runtime: PixelBuffer → grayscale Mat + stats.
`cv::SIFT::create()` is compile/link-checked (object created, **no extract**).
`cv::solvePnPRansac` is compile/link-checked (symbol forced, **not called** with points).
