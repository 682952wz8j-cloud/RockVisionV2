import Foundation

/// Frozen Gate 3D PnP / RANSAC baseline. Named constants, not magic numbers.
enum PnPConfig {
    static let useExtrinsicGuess = false
    static let iterationsCount = 100
    static let reprojectionErrorNativePx = 8.0
    static let confidence = 0.99
    static let flagsName = "SOLVEPNP_EPNP"
    /// OpenCV `cv::SOLVEPNP_EPNP`. Gate 3D choice, not claimed as the API default.
    static let flagsValue = 1
    static let distortionModel = "zeros"
    static let queryCoordinateSpace = "nativeCapturedImage"
    static let expectedNativeWidth = 1920
    static let expectedNativeHeight = 1440
    static let associationRadiusPx = 2.0
    static let opencvVersion = "4.14.0"
    static let poseName = "T_opencvCam_colmap"
    static let poseConvention = "X_cam = R * X_colmap + t"
    static let cameraCenterConvention = "C_colmap = -R^T * t"
    static let minCorrespondences = 4
    static let refineReprojWorsePx = 1.0
    static let refineCheiralityDrop = 0.05
    static let localizationState = "idle"
    static let observationDepthLabel = "observation-depth sanity"
    static let cColmapUnits = "colmapReconstruction"
    static let cWallUnits = "meters"
    static let depthCamUnits = "colmapReconstruction"
    static let depthMetersUnits = "meters"
    static let offlineBaselineSession = "gate3b_20260824_163435"
    /// Validated Sim(3) scale. Used only for C_wall / observation-depth meters. Not a PnP input.
    static let expectedSim3Scale = 3.19764417024824
}

/// Shared noiseless fixture for convention round-trip tests.
enum PnPSyntheticFixture {
    static let nativeWidth = 1920
    static let nativeHeight = 1440
    static let fx = 1450.0
    static let fy = 1450.0
    static let cx = 960.0
    static let cy = 720.0
    static let rvec = [0.12, -0.18, 0.07]
    static let tvec = [0.4, -0.3, 6.5]
    static let processingScale = 960.0 / 1920.0

    static var cameraMatrix: [[Double]] {
        [
            [fx, 0, cx],
            [0, fy, cy],
            [0, 0, 1]
        ]
    }

    static var distCoeffs: [Double] { [0, 0, 0, 0, 0] }

    static var objectPoints: [[Double]] {
        var points: [[Double]] = []
        for iy in 0..<5 {
            for ix in 0..<5 {
                let x = -1.6 + 0.8 * Double(ix)
                let y = -1.6 + 0.8 * Double(iy)
                points.append([x, y, 0])
            }
        }
        points.append([-0.4, 0.2, 0.35])
        points.append([0.5, -0.6, 0.4])
        points.append([0.0, 0.0, 0.25])
        return points
    }
}
