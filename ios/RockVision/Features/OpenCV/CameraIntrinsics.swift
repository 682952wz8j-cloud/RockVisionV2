import CoreGraphics
import Foundation
import simd

/// Read-only ARCamera intrinsics. This gate does not modify K.
struct CameraIntrinsicsSnapshot: Equatable, Sendable {
    var fx: Double
    var fy: Double
    var cx: Double
    var cy: Double
    /// Full 3×3 `ARCamera.intrinsics` in row-major layout. Do not rebuild a 960 K.
    var cameraMatrix: [[Double]]
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

    var imageResolutionMatchesCaptured: Bool {
        referenceWidth == capturedWidth && referenceHeight == capturedHeight
    }

    var capturedMatchesExpectedNative: Bool {
        capturedWidth == PnPConfig.expectedNativeWidth && capturedHeight == PnPConfig.expectedNativeHeight
    }

    var imageResolutionMatchesExpectedNative: Bool {
        referenceWidth == PnPConfig.expectedNativeWidth && referenceHeight == PnPConfig.expectedNativeHeight
    }

    /// Gate 3D PnP requires native (u,v) + same-frame native K. No silent scale.
    var pnpIntrinsicsReady: Bool {
        isValid && imageResolutionMatchesCaptured && capturedMatchesExpectedNative && imageResolutionMatchesExpectedNative
    }

    var summary: String {
        String(
            format: "fx=%.1f fy=%.1f cx=%.1f cy=%.1f Kref=%dx%d cap=%dx%d match=%@ pnpReady=%@",
            fx, fy, cx, cy, referenceWidth, referenceHeight, capturedWidth, capturedHeight,
            imageResolutionMatchesCaptured ? "yes" : "no",
            pnpIntrinsicsReady ? "yes" : "no"
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
        let matrix: [[Double]] = [
            [Double(cameraMatrix.columns.0.x), Double(cameraMatrix.columns.1.x), Double(cameraMatrix.columns.2.x)],
            [Double(cameraMatrix.columns.0.y), Double(cameraMatrix.columns.1.y), Double(cameraMatrix.columns.2.y)],
            [Double(cameraMatrix.columns.0.z), Double(cameraMatrix.columns.1.z), Double(cameraMatrix.columns.2.z)]
        ]
        return CameraIntrinsicsSnapshot(
            fx: Double(cameraMatrix.columns.0.x),
            fy: Double(cameraMatrix.columns.1.y),
            cx: Double(cameraMatrix.columns.2.x),
            cy: Double(cameraMatrix.columns.2.y),
            cameraMatrix: matrix,
            referenceWidth: Int(imageResolution.width.rounded()),
            referenceHeight: Int(imageResolution.height.rounded()),
            capturedWidth: capturedWidth,
            capturedHeight: capturedHeight
        )
    }
}
