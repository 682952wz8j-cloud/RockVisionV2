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
    case notRequested
}

enum FieldTestRunPlan: Equatable, Sendable {
    case full
    case single(SIFTSceneLabel)

    static let fullModeName = "full"
    static let singleModeName = "singleScene"

    var testMode: String {
        switch self {
        case .full: return Self.fullModeName
        case .single: return Self.singleModeName
        }
    }

    var requestedScene: String? {
        switch self {
        case .full: return nil
        case .single(let scene): return scene.rawValue
        }
    }

    var scenes: [SIFTSceneLabel] {
        switch self {
        case .full: return FieldTestPolicy.officialScenes
        case .single(let scene): return [scene]
        }
    }

    var firstScene: SIFTSceneLabel { scenes[0] }

    var modeLabel: String {
        switch self {
        case .full: return "Full A/B/C"
        case .single(let scene): return "Scene \(scene.rawValue) only"
        }
    }

    func includes(_ scene: SIFTSceneLabel) -> Bool {
        scenes.contains(scene)
    }

    static func from(testMode: String?, requestedScene: String?) -> FieldTestRunPlan {
        if testMode == singleModeName,
           let name = requestedScene,
           let scene = SIFTSceneLabel(rawValue: name),
           FieldTestPolicy.isOfficialScene(name) {
            return .single(scene)
        }
        return .full
    }

    func startInstruction() -> String {
        switch firstScene {
        case .A:
            return "走到目标建筑，拿稳，点 START A"
        case .B:
            return "走到低纹理表面，拿稳，点 START B"
        case .C:
            return "走到非目标高纹理场景，拿稳，点 START C"
        default:
            return "拿稳，点 START \(firstScene.rawValue)"
        }
    }
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
    var queryKeypoints: Int? = nil
    var referenceDescriptorCount: Int? = nil
    var rawDescriptorCandidates: Int? = nil
    var uniquePoint3DCandidates: Int? = nil
    var insufficientDistinctPoint3D: Int? = nil
    var ratioRejected: Int? = nil
    var acceptedAfterRatio: Int? = nil
    var acceptedUniquePoint3D: Int? = nil
    var duplicatePoint3DRejected: Int? = nil
    var bestDistanceMedian: Double? = nil
    var bestRatioMedian: Double? = nil
    var matchingLatencyMs: Double? = nil
    var stage3TotalMs: Double? = nil
    var diagnosticMatches: [DiagnosticMatch]? = nil
    var pnpCorrespondences: [PnPCorrespondence]? = nil
    var xyzMissingRejected: Int? = nil
    var inputCorrespondenceCount: Int? = nil
    var cameraSidecar: FieldTestCameraSidecar? = nil
    var pnpDiagnostic: PnPFrameResult? = nil
    var confirmation: ConfirmationTick? = nil
    var confirmationStats: ConfirmationStats? = nil
    var arkitSidecar: ARKitCameraTransformSidecar? = nil
    var alignment: AlignmentFrameResult? = nil
    var alignmentStats: AlignmentStats? = nil
    var wallDebugGeometry: WallAlignmentDebugGeometry? = nil
    var routeBinding: FieldTestRouteBindingSnapshot? = nil
    var routeRendering: FieldTestRouteRenderingSnapshot? = nil
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
    var acceptedUniquePoint3D: FieldTestMetricStats? = nil
    var matchingMs: FieldTestMetricStats? = nil
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
    var testMode: String
    var requestedScene: String?

    enum CodingKeys: String, CodingKey {
        case sessionID, createdAt, updatedAt, status, currentScene, currentPreset
        case cellStartedAt, openCVVersion, siftParameters, nativeWidth, nativeHeight
        case testMode, requestedScene
    }

    init(
        sessionID: String,
        createdAt: Date,
        updatedAt: Date,
        status: String,
        currentScene: String?,
        currentPreset: String?,
        cellStartedAt: Date?,
        openCVVersion: String,
        siftParameters: String,
        nativeWidth: Int,
        nativeHeight: Int,
        testMode: String,
        requestedScene: String?
    ) {
        self.sessionID = sessionID
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.status = status
        self.currentScene = currentScene
        self.currentPreset = currentPreset
        self.cellStartedAt = cellStartedAt
        self.openCVVersion = openCVVersion
        self.siftParameters = siftParameters
        self.nativeWidth = nativeWidth
        self.nativeHeight = nativeHeight
        self.testMode = testMode
        self.requestedScene = requestedScene
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sessionID = try c.decode(String.self, forKey: .sessionID)
        createdAt = try c.decode(Date.self, forKey: .createdAt)
        updatedAt = try c.decode(Date.self, forKey: .updatedAt)
        status = try c.decode(String.self, forKey: .status)
        currentScene = try c.decodeIfPresent(String.self, forKey: .currentScene)
        currentPreset = try c.decodeIfPresent(String.self, forKey: .currentPreset)
        cellStartedAt = try c.decodeIfPresent(Date.self, forKey: .cellStartedAt)
        openCVVersion = try c.decode(String.self, forKey: .openCVVersion)
        siftParameters = try c.decode(String.self, forKey: .siftParameters)
        nativeWidth = try c.decode(Int.self, forKey: .nativeWidth)
        nativeHeight = try c.decode(Int.self, forKey: .nativeHeight)
        testMode = try c.decodeIfPresent(String.self, forKey: .testMode) ?? FieldTestRunPlan.fullModeName
        requestedScene = try c.decodeIfPresent(String.self, forKey: .requestedScene)
    }
}

struct FieldTestSummary: Codable, Equatable, Sendable {
    var sessionID: String
    var updatedAt: Date
    var phase: String
    var cells: [FieldTestCellSummary]
    var testMode: String
    var requestedScene: String?

    enum CodingKeys: String, CodingKey {
        case sessionID, updatedAt, phase, cells, testMode, requestedScene
    }

    init(sessionID: String, updatedAt: Date, phase: String, cells: [FieldTestCellSummary], testMode: String, requestedScene: String?) {
        self.sessionID = sessionID
        self.updatedAt = updatedAt
        self.phase = phase
        self.cells = cells
        self.testMode = testMode
        self.requestedScene = requestedScene
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sessionID = try c.decode(String.self, forKey: .sessionID)
        updatedAt = try c.decode(Date.self, forKey: .updatedAt)
        phase = try c.decode(String.self, forKey: .phase)
        cells = try c.decode([FieldTestCellSummary].self, forKey: .cells)
        testMode = try c.decodeIfPresent(String.self, forKey: .testMode) ?? FieldTestRunPlan.fullModeName
        requestedScene = try c.decodeIfPresent(String.self, forKey: .requestedScene)
    }
}

enum FieldTestExportSchema {
    static let version = "gate5da.runtime.1"
    static let legacyGate4BRuntimeVersion = "gate4b.runtime.1"
    static let legacyRuntimeVersion = "gate4a.runtime.1"
    static let legacyOfflineVersion = "gate3d.export.1"
    static let provenanceOfflineBaseline = PnPConfig.offlineBaselineSession
    static let provenanceRuntimeBaseline = "gate4a_20260825_104607"
}

/// Current-frame Gate 5C binding observability for Field Test / Gate 5D-B.
struct FieldTestRouteBindingSnapshot: Codable, Equatable, Sendable {
    var routeId: String?
    var frozenRouteHashVerified: Bool
    var routeARWorldPointCount: Int
    var hasBoundRoute: Bool
}

/// Deterministic production render intent from current RouteRenderPlan (`wouldRender`).
/// Not AlignmentFrameResult.renderedRoute and not a RealityKit scene-graph reverse read.
struct FieldTestRouteRenderingSnapshot: Codable, Equatable, Sendable {
    var renderedRoute: Bool
    var visibleSegmentCount: Int
}

struct FieldTestConfirmationConstants: Codable, Equatable, Sendable {
    var note: String
    var confirmWindow: Int
    var adjacentRotationMaxDeg: Double
    var adjacentCWallMaxMeters: Double
    var adjacentRotationFlipGuardDeg: Double

    static let namedUncalibrated = FieldTestConfirmationConstants(
        note: "named uncalibrated constants; not calibration / not statistically optimized",
        confirmWindow: ConfirmationConfig.confirmWindow,
        adjacentRotationMaxDeg: ConfirmationConfig.adjacentRotationMaxDeg,
        adjacentCWallMaxMeters: ConfirmationConfig.adjacentCWallMaxMeters,
        adjacentRotationFlipGuardDeg: ConfirmationConfig.adjacentRotationFlipGuardDeg
    )
}

enum FieldTestStorageError: Error, LocalizedError, Equatable {
    case documentsUnavailable
    case probeMismatch
    case notReady
    case noSession
    case persistFailed(String)
    case exportFailed(String)

    var errorDescription: String? {
        switch self {
        case .documentsUnavailable:
            return "Documents directory unavailable"
        case .probeMismatch:
            return "Storage probe readback mismatch"
        case .notReady:
            return "Storage is not ready"
        case .noSession:
            return "No Field Test session to export"
        case .persistFailed(let message):
            return "Persist failed: \(message)"
        case .exportFailed(let message):
            return "Export failed: \(message)"
        }
    }
}

struct FieldTestAppIdentity: Equatable, Sendable {
    var version: String
    var build: String

    static var current: FieldTestAppIdentity {
        let info = Bundle.main.infoDictionary
        return FieldTestAppIdentity(
            version: info?["CFBundleShortVersionString"] as? String ?? "unknown",
            build: info?["CFBundleVersion"] as? String ?? "unknown"
        )
    }

    var display: String { "\(version) (\(build))" }
}

struct FieldTestExportFileEntry: Codable, Equatable, Sendable {
    var name: String
    var byteSize: Int
    var sha256: String
}

struct FieldTestExportManifest: Codable, Equatable, Sendable {
    var schemaVersion: String
    var sessionID: String
    var exportTime: Date
    var sessionStatus: String
    var sampleCount: Int
    var appVersion: String
    var appBuild: String
    var openCVVersion: String
    var testMode: String
    var requestedScene: String?
    var files: [FieldTestExportFileEntry]
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
            totalMs: FieldTestMetricStats.from(valid.map(\.totalLatencyMs)),
            acceptedUniquePoint3D: FieldTestMetricStats.from(valid.compactMap(\.acceptedUniquePoint3D).map(Double.init)),
            matchingMs: FieldTestMetricStats.from(valid.compactMap(\.matchingLatencyMs))
        )
    }

    static func notRequestedCell(scene: String, preset: SIFTProcessingPreset) -> FieldTestCellSummary {
        FieldTestCellSummary(
            scene: scene,
            presetLabel: preset.label,
            processingWidth: preset.targetWidth,
            processingHeight: preset.targetHeight,
            status: .notRequested,
            targetValidSamples: FieldTestPolicy.targetValidSamples,
            validCount: 0,
            invalidCount: 0,
            progressLabel: "notRequested",
            elapsedSeconds: 0,
            keypoints: nil,
            occupancy: nil,
            preprocessMs: nil,
            siftMs: nil,
            totalMs: nil,
            acceptedUniquePoint3D: nil,
            matchingMs: nil
        )
    }
}
