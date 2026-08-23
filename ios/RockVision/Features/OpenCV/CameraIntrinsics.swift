import CoreGraphics
import Foundation
import simd

/// Read-only ARCamera intrinsics. This gate does not modify K.
struct CameraIntrinsicsSnapshot: Equatable, Sendable {
    var fx: Double
    var fy: Double
    var cx: Double
    var cy: Double
    /// Resolution `ARCamera.intrinsics` is defined against (`imageResolution`).
    var referenceWidth: Int
    var referenceHeight: Int
    /// `ARFrame.capturedImage` pixel size (native sensor buffer).
    var capturedWidth: Int
    var capturedHeight: Int

    var isFinite: Bool {
        fx.isFinite && fy.isFinite && cx.isFinite && cy.isFinite
    }

    var focalLengthsPositive: Bool {
        fx > 0 && fy > 0
    }

    var principalPointReasonable: Bool {
        guard referenceWidth > 0, referenceHeight > 0 else { return false }
        return cx > 0 && cy > 0 && cx < Double(referenceWidth) && cy < Double(referenceHeight)
    }

    var isValid: Bool {
        isFinite && focalLengthsPositive && principalPointReasonable
    }

    var summary: String {
        String(
            format: "fx=%.1f fy=%.1f cx=%.1f cy=%.1f Kref=%dx%d cap=%dx%d",
            fx, fy, cx, cy, referenceWidth, referenceHeight, capturedWidth, capturedHeight
        )
    }
}

enum CameraIntrinsicsValidator {
    static func make(
        cameraMatrix: simd_float3x3,
        imageResolution: CGSize,
        capturedWidth: Int,
        capturedHeight: Int
    ) -> CameraIntrinsicsSnapshot {
        CameraIntrinsicsSnapshot(
            fx: Double(cameraMatrix.columns.0.x),
            fy: Double(cameraMatrix.columns.1.y),
            cx: Double(cameraMatrix.columns.2.x),
            cy: Double(cameraMatrix.columns.2.y),
            referenceWidth: Int(imageResolution.width.rounded()),
            referenceHeight: Int(imageResolution.height.rounded()),
            capturedWidth: capturedWidth,
            capturedHeight: capturedHeight
        )
    }
}
