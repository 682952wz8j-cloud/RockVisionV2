# Camera Image Convention (Gate 3A / 3B)

Status: binding for later SIFT / matching / PnP. This gate does **not** rotate pixels.

RockVision processes ARKit’s **native captured image**, not a UI-preview screenshot.

```text
ARSession
  → ARFrame
  → capturedImage (CVPixelBuffer)
  → OpenCVBridge
  → grayscale cv::Mat in native sensor pixels
```

## 1. Native captured image

| Item | Gate 3A policy |
|------|----------------|
| Source | `ARFrame.capturedImage` from the existing `ARSessionHost` |
| Typical size (iPhone 17 Pro, 2026-08-23) | **1920 × 1440** PixelBuffer / Y plane |
| Pixel format | **`420f`** (`kCVPixelFormatType_420YpCbCr8BiPlanarFullRange`). **Not BGRA.** |
| Plane used now | **plane 0 = Y (luma)** |
| `cv::Mat` | `CV_8UC1`, `rows = Y height`, `cols = Y width` |
| Row stride | `CVPixelBufferGetBytesPerRowOfPlane(..., 0)` (may be `> width`) |
| Copy | **zero-copy wrap** of the locked Y plane |
| Color conversion | none. Do not do YCbCr → RGB → gray |

Do not assume BGRA. Unsupported layouts return an error and do not crash.

## 2. Coordinate space for keypoints (Gate 3B)

SIFT may run on a downscaled copy. Canonical keypoint coordinates are always mapped back to **native captured-image pixels**:

```text
scaleX = processingWidth  / nativeWidth
scaleY = processingHeight / nativeHeight
x_native = x_processed / scaleX
y_native = y_processed / scaleY
```

- origin: top-left of the Y-plane / grayscale `cv::Mat`
- `+u` right, `+v` down
- units: native pixels at the captured Y-plane size (typically 1920 × 1440)
- resize: aspect-preserving fit, no crop, no upscale
- overlay: native → normalized → `ARFrame.displayTransform` → view

This is **not** UIKit view space and **not** a portrait-rotated preview.

`ARCamera.intrinsics` (`fx, fy, cx, cy`) stays the 1920 × 1440 / `imageResolution` calibration. Gate 3B does **not** write a second K for the processed size.

If those two resolutions differ, later gates must scale `K` explicitly before PnP. Do not silently scale.

## 3. Three orientations (keep them separate)

| Name | Meaning | This gate |
|------|---------|-----------|
| Native / sensor | PixelBuffer width × height as delivered by ARKit | **used** |
| UI portrait / landscape | `UIWindowScene.interfaceOrientation` | **recorded only** |
| Future SIFT processing | same as native unless a later gate documents a rotation | **native** |

Do **not** rotate pixel data so the debug preview “looks upright.”

If a later gate rotates the image, it must also transform:

1. keypoint coordinates
2. camera intrinsics (`fx, fy, cx, cy` and image size)

in the same documented step.

## 4. PixelBuffer / `cv::Mat` lifetime

```text
CVPixelBufferRetain (if processing asynchronously)
CVPixelBufferLockBaseAddress(..., ReadOnly)
  wrap Y plane as cv::Mat (zero-copy)
  compute diagnostics (or later: SIFT on a copy if needed)
  do not store the Mat
CVPixelBufferUnlockBaseAddress
CVPixelBufferRelease
```

A `cv::Mat` that points at PixelBuffer memory is valid **only while the buffer is locked**. Do not keep that Mat on a property, across threads, or after unlock.

ARKit may recycle `ARFrame.capturedImage` after the session callback returns. Asynchronous work must retain the buffer, not the whole `ARFrame`.

## 5. What this is not

- Not visual localization
- Not SIFT matching / COLMAP load / PnP
- Not an AVFoundation second camera
- Not a screen-space or UIImage pipeline
