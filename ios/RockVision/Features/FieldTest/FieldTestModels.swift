import Foundation

enum FieldTestPolicy {
    static let targetValidSamples = 20
    static let timeoutSeconds: TimeInterval = 90
    static let officialScenes: [SIFTSceneLabel] = [.A, .B, .C]
    static let resolutionOrder: [SIFTProcessingPreset] = [.native, .medium, .low]

    static func isOfficialScene(_ scene: String) -> Bool {
        officialScenes.contains { $0.rawValue == scene }
    }

    static func isValidSample(ok: Bool, tracking: String, descriptorsFinite: Bool, rowsMatchKeypoints: Bool) -> Bool {
        ok && tracking == "normal" && descriptorsFinite && rowsMatchKeypoints
    }

    static func cellStatus(validCount: Int, elapsed: TimeInterval) -> FieldTestCellStatus? {
        if validCount >= targetValidSamples {
            return .complete
        }
        if elapsed >= timeoutSeconds {
            return .incomplete
        }
        return nil
    }
}

enum FieldTestCellStatus: String, Codable, Sendable {
    case pending
    case running
    case complete
    case incomplete
}

enum FieldTestPhase: Equatable, Sendable {
    case idle
    case readyToStart(SIFTSceneLabel)
    case waitingTracking(scene: SIFTSceneLabel, preset: SIFTProcessingPreset)
    case sampling(scene: SIFTSceneLabel, preset: SIFTProcessingPreset)
    case readyToStartNext(finished: SIFTSceneLabel, next: SIFTSceneLabel)
    case complete
}

struct FieldTestSample: Codable, Equatable, Sendable {
    var recordedAt: Date
    var frameID: UInt64
    var timestamp: TimeInterval
    var scene: String
    var processingWidth: Int
    var processingHeight: Int
    var presetLabel: String
    var keypointCount: Int
    var occupiedCells: Int
    var occupancyRatio: Double
    var preprocessLatencyMs: Double
    var siftLatencyMs: Double
    var totalLatencyMs: Double
    var tracking: String
    var valid: Bool
    var invalidReason: String?
    var descriptorRows: Int
    var descriptorDimension: Int
    var descriptorsFinite: Bool
    var rowsMatchKeypoints: Bool
    var skippedFrames: Int
    var achievedRateHz: Double
}

struct FieldTestMetricStats: Codable, Equatable, Sendable {
    var min: Double
    var median: Double
    var p90: Double
    var max: Double

    static func from(_ values: [Double]) -> FieldTestMetricStats? {
        guard let minV = values.min(),
              let maxV = values.max(),
              let median = SIFTStatistics.percentile(values, 50),
              let p90 = SIFTStatistics.percentile(values, 90)
        else { return nil }
        return FieldTestMetricStats(min: minV, median: median, p90: p90, max: maxV)
    }

    static func fromInts(_ values: [Int]) -> FieldTestMetricStats? {
        from(values.map(Double.init))
    }
}

struct FieldTestCellSummary: Codable, Equatable, Sendable {
    var scene: String
    var presetLabel: String
    var processingWidth: Int
    var processingHeight: Int
    var status: FieldTestCellStatus
    var targetValidSamples: Int
    var validCount: Int
    var invalidCount: Int
    var progressLabel: String
    var elapsedSeconds: Double
    var keypoints: FieldTestMetricStats?
    var occupancy: FieldTestMetricStats?
    var preprocessMs: FieldTestMetricStats?
    var siftMs: FieldTestMetricStats?
    var totalMs: FieldTestMetricStats?
}

struct FieldTestSessionRecord: Codable, Equatable, Sendable {
    var sessionID: String
    var createdAt: Date
    var updatedAt: Date
    var status: String
    var currentScene: String?
    var currentPreset: String?
    var cellStartedAt: Date?
    var openCVVersion: String
    var siftParameters: String
    var nativeWidth: Int
    var nativeHeight: Int
}

struct FieldTestSummary: Codable, Equatable, Sendable {
    var sessionID: String
    var updatedAt: Date
    var phase: String
    var cells: [FieldTestCellSummary]
}

enum FieldTestStatistics {
    static func summarizeCell(
        scene: String,
        preset: SIFTProcessingPreset,
        samples: [FieldTestSample],
        status: FieldTestCellStatus,
        elapsed: TimeInterval
    ) -> FieldTestCellSummary {
        let valid = samples.filter(\.valid)
        let invalid = samples.filter { !$0.valid }
        return FieldTestCellSummary(
            scene: scene,
            presetLabel: preset.label,
            processingWidth: preset.targetWidth,
            processingHeight: preset.targetHeight,
            status: status,
            targetValidSamples: FieldTestPolicy.targetValidSamples,
            validCount: valid.count,
            invalidCount: invalid.count,
            progressLabel: "\(valid.count)/\(FieldTestPolicy.targetValidSamples)",
            elapsedSeconds: elapsed,
            keypoints: FieldTestMetricStats.fromInts(valid.map(\.keypointCount)),
            occupancy: FieldTestMetricStats.from(valid.map(\.occupancyRatio)),
            preprocessMs: FieldTestMetricStats.from(valid.map(\.preprocessLatencyMs)),
            siftMs: FieldTestMetricStats.from(valid.map(\.siftLatencyMs)),
            totalMs: FieldTestMetricStats.from(valid.map(\.totalLatencyMs))
        )
    }
}
