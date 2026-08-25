import CoreGraphics
import Foundation

/// One-frame SIFT diagnostics. Descriptors are not retained after validation.
struct SIFTFrameResult: Equatable, Sendable {
    var frameID: UInt64
    var timestamp: TimeInterval
    var ok: Bool
    var status: String

    var nativeImageWidth: Int
    var nativeImageHeight: Int
    var processingWidth: Int
    var processingHeight: Int
    var scaleX: Double
    var scaleY: Double

    var keypointCount: Int
    var descriptorCount: Int
    var descriptorDimension: Int
    var descriptorType: String
    var descriptorRows: Int
    var descriptorCols: Int
    var descriptorsFinite: Bool
    var rowsMatchKeypoints: Bool

    var preprocessLatencyMs: Double
    var siftLatencyMs: Double
    var totalLatencyMs: Double

    var gridCounts: [Int]
    var occupiedCells: Int
    var occupancyRatio: Double

    /// Native captured-image coordinates (canonical). Overlay may sample these.
    var keypointsNative: [CGPoint]
    var overlayNative: [CGPoint]

    var error: String?

    static func empty(frameID: UInt64, timestamp: TimeInterval, error: String?) -> SIFTFrameResult {
        SIFTFrameResult(
            frameID: frameID,
            timestamp: timestamp,
            ok: false,
            status: "inactive",
            nativeImageWidth: 0,
            nativeImageHeight: 0,
            processingWidth: 0,
            processingHeight: 0,
            scaleX: 0,
            scaleY: 0,
            keypointCount: 0,
            descriptorCount: 0,
            descriptorDimension: 0,
            descriptorType: "—",
            descriptorRows: 0,
            descriptorCols: 0,
            descriptorsFinite: true,
            rowsMatchKeypoints: true,
            preprocessLatencyMs: 0,
            siftLatencyMs: 0,
            totalLatencyMs: 0,
            gridCounts: Array(repeating: 0, count: SIFTGrid.cellCount),
            occupiedCells: 0,
            occupancyRatio: 0,
            keypointsNative: [],
            overlayNative: [],
            error: error
        )
    }

    var processingLabel: String {
        "\(processingWidth) × \(processingHeight)"
    }

    var descriptorLabel: String {
        "\(descriptorRows) × \(descriptorDimension)"
    }

    var gridLabel: String {
        "\(occupiedCells) / \(SIFTGrid.cellCount)"
    }
}

struct SIFTRuntimeSnapshot: Equatable, Sendable {
    var status: String = "inactive"
    var processing: String = "—"
    var keypoints: String = "—"
    var descriptors: String = "—"
    var grid: String = "—"
    var preprocessMs: String = "—"
    var siftMs: String = "—"
    var totalMs: String = "—"
    var rateHz: String = "—"
    var skipped: Int = 0
    var presetLabel: String = SIFTProcessingPreset.low.label
    var requestedRateHz: String = "2.0"
    var scene: String = "unlabeled"
    var showKeypoints: Bool = true
    var overlayViewPoints: [CGPoint] = []
}

struct SIFTParameterRecord: Equatable, Sendable {
    static let nfeatures = 0
    static let nOctaveLayers = 3
    static let contrastThreshold = 0.04
    static let edgeThreshold = 10.0
    static let sigma = 1.6
    static var summary: String {
        "nfeatures=\(nfeatures) nOctaveLayers=\(nOctaveLayers) contrastThreshold=\(contrastThreshold) edgeThreshold=\(edgeThreshold) sigma=\(sigma)"
    }
}
