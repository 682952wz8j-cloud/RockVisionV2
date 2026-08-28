import Combine
import Foundation
import UIKit

/// Field-test state machine. Does not extract SIFT or classify physical scenes.
final class FieldTestController: ObservableObject {
    @Published private(set) var phase: FieldTestPhase = .readyToStart(.A)
    @Published private(set) var instruction: String = "走到目标建筑，拿稳，点 START A"
    @Published private(set) var progressLabel: String = "—"
    @Published private(set) var elapsedLabel: String = "—"
    @Published private(set) var sessionPath: String = "—"
    @Published private(set) var summary: FieldTestSummary?
    @Published private(set) var hasResumableSession = false
    @Published private(set) var isSampling = false
    @Published private(set) var storageReady = false
    @Published private(set) var storageLabel = "Storage: Probing"
    @Published private(set) var lastSaveLabel = "Last save: —"
    @Published private(set) var persistedSamplesLabel = "Persisted samples: —"
    @Published private(set) var exportLabel = "Export: Unavailable"
    @Published private(set) var persistErrorLabel: String?
    @Published private(set) var copyFeedback: String?
    @Published var shareZIPURL: URL?
    @Published var isSharePresented = false
    @Published private(set) var persistedSampleCount = 0
    @Published private(set) var plan: FieldTestRunPlan = .full

    private let store: FieldTestStore
    private let openCVVersion: String
    private let identity: FieldTestAppIdentity
    private let zipStagingRoot: URL
    private var handle: FieldTestSessionHandle?
    private var record: FieldTestSessionRecord?
    private var samples: [FieldTestSample] = []
    private var cellStatuses: [String: FieldTestCellStatus] = [:]
    private var cellStartedAt: Date?
    private var timeoutTimer: Timer?
    private let persistQueue = DispatchQueue(label: "com.rockvision.v2.fieldtest.persist")
    private let presets: [SIFTProcessingPreset]

    var locksEngineerControls: Bool { isSampling }
    var canStartTest: Bool { storageReady }
    var canChangeMode: Bool { storageReady && !isSampling && handle == nil && !hasResumableSession }
    var canExport: Bool { storageReady && handle != nil }
    var canCopySummary: Bool { handle != nil && record != nil }
    var onApplyScene: ((String) -> Void)?
    var onApplyPreset: ((SIFTProcessingPreset) -> Void)?
    var onSetLocked: ((Bool) -> Void)?
    var onResetConfirmation: ((@escaping () -> Void) -> Void)?

    init(
        store: FieldTestStore,
        openCVVersion: String,
        identity: FieldTestAppIdentity = .current,
        zipStagingRoot: URL = FileManager.default.temporaryDirectory.appendingPathComponent("FieldTestExport", isDirectory: true),
        presets: [SIFTProcessingPreset] = FieldTestPolicy.resolutionOrder
    ) {
        self.store = store
        self.openCVVersion = openCVVersion
        self.identity = identity
        self.zipStagingRoot = zipStagingRoot
        self.presets = presets.isEmpty ? [.low] : presets
        enterFieldTest()
    }

    convenience init() {
        let store: FieldTestStore
        if let docs = try? FieldTestStore.documentsDirectory() {
            store = FieldTestStore(rootURL: docs.appendingPathComponent("FieldTests", isDirectory: true))
        } else {
            store = FieldTestStore(rootURL: URL(fileURLWithPath: "/var/empty/RockVisionNoDocuments/FieldTests", isDirectory: true))
        }
        self.init(store: store, openCVVersion: OpenCVBridge.openCVVersion(), presets: [.low])
    }

    func enterFieldTest() {
        do {
            try store.probeStorage()
            storageReady = true
            storageLabel = "Storage: Ready"
            persistErrorLabel = nil
            if handle == nil {
                try restoreInterruptedSessionIfNeeded()
            }
            refreshExportAvailability()
        } catch {
            storageReady = false
            storageLabel = "Storage: Failed"
            persistErrorLabel = error.localizedDescription
            instruction = "Storage 不可用，不能开始测试。\(error.localizedDescription)"
            phase = .idle
            refreshExportAvailability()
        }
    }

    func selectPlan(_ plan: FieldTestRunPlan) {
        guard canChangeMode else { return }
        self.plan = plan
        applyReadyInstruction()
    }

    func startScene(_ scene: SIFTSceneLabel) {
        guard FieldTestPolicy.officialScenes.contains(scene) else { return }
        guard plan.includes(scene) else { return }
        guard storageReady else {
            instruction = "Storage 未就绪，不能开始测试。"
            return
        }
        if handle == nil || record?.status == "complete" {
            beginNewSession()
        }
        guard handle != nil, record != nil else { return }
        beginCellAfterConfirmationReset(scene: scene, preset: presets[0])
    }

    func startOfficialNext() {
        switch phase {
        case .readyToStart(let scene), .readyToStartNext(_, let scene):
            startScene(scene)
        default:
            break
        }
    }

    func resume() {
        guard storageReady else {
            instruction = "Storage 未就绪，不能开始测试。"
            return
        }
        guard let record else { return }
        hasResumableSession = false
        if let sceneName = record.currentScene,
           let scene = SIFTSceneLabel(rawValue: sceneName),
           plan.includes(scene),
           let presetName = record.currentPreset,
           let preset = SIFTProcessingPreset.allCases.first(where: { $0.label == presetName }) {
            beginCellAfterConfirmationReset(scene: scene, preset: preset, restartClock: record.cellStartedAt == nil)
        } else {
            applyReadyInstruction()
        }
        refreshExportAvailability()
    }

    func startNewSession() {
        guard storageReady else {
            instruction = "Storage 未就绪，不能开始测试。"
            return
        }
        samples = []
        cellStatuses = [:]
        handle = nil
        record = nil
        hasResumableSession = false
        shareZIPURL = nil
        persistedSampleCount = 0
        plan = .full
        applyReadyInstruction()
        progressLabel = "—"
        summary = nil
        isSampling = false
        onResetConfirmation?({ })
        refreshExportAvailability()
    }

    func abort() {
        isSampling = false
        stopTimer()
        record?.status = "aborted"
        record?.updatedAt = Date()
        persistMeta(phaseName: "aborted")
        onSetLocked?(false)
        phase = .idle
        instruction = "已中止。点 New Session 开始新的现场测试。"
        refreshExportAvailability()
    }

    @discardableResult
    func ingest(
        result: SIFTFrameResult,
        tracking: String,
        skipped: Int,
        rateHz: Double,
        activePreset: SIFTProcessingPreset,
        matching: MatchingFrameResult? = nil,
        camera: CameraIntrinsicsSnapshot? = nil,
        pnp: PnPFrameResult? = nil,
        confirmation: ConfirmationTick? = nil,
        confirmationStats: ConfirmationStats? = nil,
        arkitSidecar: ARKitCameraTransformSidecar? = nil,
        alignment: AlignmentFrameResult? = nil,
        alignmentStats: AlignmentStats? = nil,
        wallDebugGeometry: WallAlignmentDebugGeometry? = nil,
        routeBinding: RuntimeRouteBinding? = nil,
        routeRenderPlan: RouteRenderPlan? = nil
    ) -> Bool {
        guard isSampling else { return false }
        if case let .waitingTracking(scene, preset) = phase {
            if tracking == "normal" {
                if Thread.isMainThread {
                    enterSampling(scene: scene, preset: preset)
                } else {
                    DispatchQueue.main.sync {
                        self.enterSampling(scene: scene, preset: preset)
                    }
                }
            } else {
                return false
            }
        }
        guard case let .sampling(scene, preset) = phase else { return false }
        guard result.processingWidth == preset.targetWidth
                || (preset == .native && result.processingWidth == result.nativeImageWidth) else {
            return false
        }

        let valid = FieldTestPolicy.isValidSample(
            ok: result.ok,
            tracking: tracking,
            descriptorsFinite: result.descriptorsFinite,
            rowsMatchKeypoints: result.rowsMatchKeypoints
        )
        var reason: String?
        if !valid {
            if tracking != "normal" { reason = "tracking=\(tracking)" }
            else if !result.ok { reason = result.error ?? "sift not ok" }
            else if !result.descriptorsFinite { reason = "non-finite descriptors" }
            else if !result.rowsMatchKeypoints { reason = "descriptor rows mismatch" }
        }

        let persistMatching = matching?.status == "active"
        let cameraSidecar = camera.map {
            PnPSidecarBuilder.cameraSidecar(result: result, camera: $0, openCVVersion: openCVVersion)
        }
        let sample = FieldTestSample(
            recordedAt: Date(),
            frameID: result.frameID,
            timestamp: result.timestamp,
            scene: scene.rawValue,
            processingWidth: result.processingWidth,
            processingHeight: result.processingHeight,
            presetLabel: preset.label,
            keypointCount: result.keypointCount,
            occupiedCells: result.occupiedCells,
            occupancyRatio: result.occupancyRatio,
            preprocessLatencyMs: result.preprocessLatencyMs,
            siftLatencyMs: result.siftLatencyMs,
            totalLatencyMs: result.totalLatencyMs,
            tracking: tracking,
            valid: valid,
            invalidReason: reason,
            descriptorRows: result.descriptorRows,
            descriptorDimension: result.descriptorDimension,
            descriptorsFinite: result.descriptorsFinite,
            rowsMatchKeypoints: result.rowsMatchKeypoints,
            skippedFrames: skipped,
            achievedRateHz: rateHz,
            queryKeypoints: persistMatching ? matching?.queryKeypoints : nil,
            referenceDescriptorCount: persistMatching ? matching?.referenceDescriptorCount : nil,
            rawDescriptorCandidates: persistMatching ? matching?.rawDescriptorCandidates : nil,
            uniquePoint3DCandidates: persistMatching ? matching?.uniquePoint3DCandidates : nil,
            insufficientDistinctPoint3D: persistMatching ? matching?.insufficientDistinctPoint3D : nil,
            ratioRejected: persistMatching ? matching?.ratioRejected : nil,
            acceptedAfterRatio: persistMatching ? matching?.acceptedAfterRatio : nil,
            acceptedUniquePoint3D: persistMatching ? matching?.acceptedUniquePoint3D : nil,
            duplicatePoint3DRejected: persistMatching ? matching?.duplicatePoint3DRejected : nil,
            bestDistanceMedian: persistMatching ? matching?.bestDistanceMedian : nil,
            bestRatioMedian: persistMatching ? matching?.bestRatioMedian : nil,
            matchingLatencyMs: persistMatching ? matching?.matchingLatencyMs : nil,
            stage3TotalMs: persistMatching ? matching?.stage3TotalMs : nil,
            diagnosticMatches: persistMatching ? matching?.diagnosticMatches : nil,
            pnpCorrespondences: persistMatching ? matching?.pnpCorrespondences : nil,
            xyzMissingRejected: persistMatching ? matching?.xyzMissingRejected : nil,
            inputCorrespondenceCount: persistMatching ? matching?.inputCorrespondenceCount : nil,
            cameraSidecar: cameraSidecar,
            pnpDiagnostic: persistMatching ? pnp : nil,
            confirmation: persistMatching ? confirmation : nil,
            confirmationStats: persistMatching ? confirmationStats : nil,
            arkitSidecar: persistMatching ? arkitSidecar : nil,
            alignment: persistMatching ? alignment : nil,
            alignmentStats: persistMatching ? alignmentStats : nil,
            wallDebugGeometry: persistMatching ? wallDebugGeometry : nil,
            routeBinding: persistMatching ? routeBinding.map {
                FieldTestRouteBindingSnapshot(
                    routeId: $0.routeId,
                    frozenRouteHashVerified: $0.hashVerified,
                    routeARWorldPointCount: $0.routeARWorldPointCount,
                    hasBoundRoute: $0.hasBoundRoute
                )
            } : nil,
            routeRendering: persistMatching ? routeRenderPlan.map {
                FieldTestRouteRenderingSnapshot(
                    renderedRoute: $0.wouldRender,
                    visibleSegmentCount: $0.segmentCount
                )
            } : nil
        )

        persistQueue.async { [weak self] in
            guard let self else { return }
            do {
                guard let handle = self.handle else {
                    throw FieldTestStorageError.noSession
                }
                try handle.append(sample)
                DispatchQueue.main.async {
                    self.samples.append(sample)
                    self.markPersistSuccess(persistedCount: self.samples.count)
                    self.evaluateCurrentCell()
                    self.refreshExportAvailability()
                }
            } catch {
                DispatchQueue.main.async {
                    self.samples.append(sample)
                    self.markPersistFailure(error)
                    self.evaluateCurrentCell()
                }
            }
        }
        return true
    }

    func flush() {
        persistMeta(phaseName: phaseName)
    }

    func drainPersist() {
        persistQueue.sync {}
    }

    /// Flush official files then build a ZIP in tmp staging. Share that ZIP.
    func shareCurrentResults() {
        guard storageReady else {
            persistErrorLabel = FieldTestStorageError.notReady.localizedDescription
            return
        }
        guard let handle, var session = record else {
            persistErrorLabel = FieldTestStorageError.noSession.localizedDescription
            return
        }
        drainPersist()
        session.updatedAt = Date()
        let sum = makeSummary(phaseName: phaseName)
        summary = sum
        record = session
        do {
            let zip = try persistQueue.sync {
                try self.store.exportZIP(
                    handle: handle,
                    session: session,
                    summary: sum,
                    samples: self.samples,
                    identity: self.identity,
                    stagingRoot: self.zipStagingRoot
                )
            }
            markPersistSuccess(persistedCount: samples.count)
            shareZIPURL = zip
            isSharePresented = true
            refreshExportAvailability()
        } catch {
            markPersistFailure(error)
        }
    }

    func copySummary() -> String {
        guard let session = record else { return "" }
        let text = FieldTestExport.pasteSummary(
            session: session,
            summary: summary ?? makeSummary(phaseName: phaseName),
            samples: samples,
            identity: identity
        )
        UIPasteboard.general.string = text
        copyFeedback = "Summary copied"
        return text
    }

    var currentSceneForProcessor: String? {
        switch phase {
        case .waitingTracking(let scene, _), .sampling(let scene, _):
            return scene.rawValue
        default:
            return nil
        }
    }

    var currentPresetForProcessor: SIFTProcessingPreset? {
        switch phase {
        case .waitingTracking(_, let preset), .sampling(_, let preset):
            return preset
        default:
            return nil
        }
    }

    private func restoreInterruptedSessionIfNeeded() throws {
        guard let existing = try store.latestSession() else { return }
        let session = try existing.loadSession()
        guard session.status == "running" else { return }
        hasResumableSession = true
        handle = existing
        record = session
        samples = try existing.loadSamples()
        persistedSampleCount = samples.count
        plan = FieldTestRunPlan.from(testMode: session.testMode, requestedScene: session.requestedScene)
        rebuildStatusesFromSamples()
        sessionPath = existing.directory.path
        instruction = "发现未完成测试。点 Resume 继续，或 New Session 重新开始。"
        phase = .idle
        refreshSummary(phaseName: "interrupted")
        lastSaveLabel = "Last save: session restored"
        persistedSamplesLabel = "Persisted samples: \(samples.count)"
    }

    private func beginNewSession() {
        do {
            let created = try store.createSession(openCVVersion: openCVVersion, plan: plan)
            handle = created
            record = try created.loadSession()
            samples = []
            persistedSampleCount = 0
            sessionPath = created.directory.path
            markPersistSuccess(persistedCount: 0)
        } catch {
            handle = nil
            record = nil
            markPersistFailure(error)
            instruction = "无法创建测试目录：\(error.localizedDescription)"
        }
    }

    private func beginCellAfterConfirmationReset(
        scene: SIFTSceneLabel,
        preset: SIFTProcessingPreset,
        restartClock: Bool = true
    ) {
        isSampling = false
        guard let prepare = onResetConfirmation else {
            beginCell(scene: scene, preset: preset, restartClock: restartClock)
            return
        }
        prepare { [weak self] in
            guard let self else { return }
            let work = {
                self.beginCell(scene: scene, preset: preset, restartClock: restartClock)
            }
            if Thread.isMainThread {
                work()
            } else {
                DispatchQueue.main.async(execute: work)
            }
        }
    }

    private func beginCell(scene: SIFTSceneLabel, preset: SIFTProcessingPreset, restartClock: Bool = true) {
        isSampling = true
        if restartClock {
            cellStartedAt = Date()
        } else {
            cellStartedAt = record?.cellStartedAt ?? Date()
        }
        record?.currentScene = scene.rawValue
        record?.currentPreset = preset.label
        record?.cellStartedAt = cellStartedAt
        record?.status = "running"
        record?.updatedAt = Date()
        onSetLocked?(true)
        onApplyScene?(scene.rawValue)
        onApplyPreset?(preset)
        phase = .waitingTracking(scene: scene, preset: preset)
        instruction = "拿稳 — 等待 ARKit normal — Scene \(scene.rawValue) — \(preset.label)"
        progressLabel = "0/\(FieldTestPolicy.targetValidSamples)"
        persistMeta(phaseName: "waitingTracking")
        startTimer()
        refreshExportAvailability()
        let alreadyValid = samples.filter { $0.scene == scene.rawValue && $0.presetLabel == preset.label && $0.valid }.count
        if FieldTestPolicy.cellStatus(validCount: alreadyValid, elapsed: 0) == .complete {
            finishCell(scene: scene, preset: preset, status: .complete)
        }
    }

    private func enterSampling(scene: SIFTSceneLabel, preset: SIFTProcessingPreset) {
        guard case .waitingTracking(scene, preset) = phase else { return }
        if cellStartedAt == nil { cellStartedAt = Date() }
        phase = .sampling(scene: scene, preset: preset)
        instruction = "拿稳 — Scene \(scene.rawValue) — \(preset.label)"
        persistMeta(phaseName: "sampling")
        evaluateCurrentCell()
    }

    private func evaluateCurrentCell() {
        guard case let .sampling(scene, preset) = phase, let started = cellStartedAt else { return }
        let elapsed = Date().timeIntervalSince(started)
        elapsedLabel = String(format: "%.0fs / %.0fs", elapsed, FieldTestPolicy.timeoutSeconds)
        let cellSamples = samples.filter { $0.scene == scene.rawValue && $0.presetLabel == preset.label }
        let validCount = cellSamples.filter(\.valid).count
        progressLabel = "\(validCount)/\(FieldTestPolicy.targetValidSamples)"
        refreshSummary(phaseName: "sampling")
        guard let status = FieldTestPolicy.cellStatus(validCount: validCount, elapsed: elapsed) else { return }
        finishCell(scene: scene, preset: preset, status: status)
    }

    private func finishCell(scene: SIFTSceneLabel, preset: SIFTProcessingPreset, status: FieldTestCellStatus) {
        stopTimer()
        cellStatuses[Self.cellKey(scene: scene, preset: preset)] = status
        refreshSummary(phaseName: status.rawValue)
        persistMeta(phaseName: status.rawValue)
        if let nextPreset = nextPreset(after: preset) {
            isSampling = false
            beginCellAfterConfirmationReset(scene: scene, preset: nextPreset)
            return
        }
        isSampling = false
        if let nextScene = nextScene(after: scene) {
            phase = .readyToStartNext(finished: scene, next: nextScene)
            instruction = instructionAfter(finished: scene, next: nextScene)
            persistMeta(phaseName: "readyToStartNext")
        } else {
            record?.status = "complete"
            record?.currentScene = nil
            record?.currentPreset = nil
            record?.cellStartedAt = nil
            phase = .complete
            instruction = "现场测试完成。结果已保存。点 Share Current Results 传回 ZIP。"
            onSetLocked?(false)
            persistMeta(phaseName: "complete")
        }
        refreshExportAvailability()
    }

    private func nextPreset(after preset: SIFTProcessingPreset) -> SIFTProcessingPreset? {
        guard let idx = presets.firstIndex(of: preset) else { return nil }
        let next = idx + 1
        return next < presets.count ? presets[next] : nil
    }

    private func nextScene(after scene: SIFTSceneLabel) -> SIFTSceneLabel? {
        guard let idx = plan.scenes.firstIndex(of: scene) else { return nil }
        let next = idx + 1
        return next < plan.scenes.count ? plan.scenes[next] : nil
    }

    private func applyReadyInstruction() {
        phase = .readyToStart(plan.firstScene)
        instruction = plan.startInstruction()
    }

    private func instructionAfter(finished: SIFTSceneLabel, next: SIFTSceneLabel) -> String {
        switch next {
        case .B:
            return "Scene \(finished.rawValue) 已保存。走到低纹理表面，拿稳，点 START B"
        case .C:
            return "Scene \(finished.rawValue) 已保存。走到非目标高纹理场景，拿稳，点 START C"
        default:
            return "Scene \(finished.rawValue) 已保存。点 START \(next.rawValue)"
        }
    }

    private func startTimer() {
        stopTimer()
        timeoutTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.evaluateCurrentCellIfSampling()
        }
    }

    private func evaluateCurrentCellIfSampling() {
        if case .waitingTracking(let scene, let preset) = phase {
            let elapsed = Date().timeIntervalSince(cellStartedAt ?? Date())
            elapsedLabel = String(format: "%.0fs / %.0fs", elapsed, FieldTestPolicy.timeoutSeconds)
            if elapsed >= FieldTestPolicy.timeoutSeconds {
                phase = .sampling(scene: scene, preset: preset)
                finishCell(scene: scene, preset: preset, status: .incomplete)
            }
            return
        }
        evaluateCurrentCell()
    }

    private func stopTimer() {
        timeoutTimer?.invalidate()
        timeoutTimer = nil
    }

    private var phaseName: String {
        switch phase {
        case .idle: return "idle"
        case .readyToStart: return "ready"
        case .waitingTracking: return "waitingTracking"
        case .sampling: return "sampling"
        case .readyToStartNext: return "readyToStartNext"
        case .complete: return "complete"
        }
    }

    private func makeSummary(phaseName: String) -> FieldTestSummary {
        let id = handle?.sessionID ?? "none"
        var cells: [FieldTestCellSummary] = []
        for scene in FieldTestPolicy.officialScenes {
            for preset in FieldTestPolicy.resolutionOrder {
                if !plan.includes(scene) || !presets.contains(preset) {
                    cells.append(FieldTestStatistics.notRequestedCell(scene: scene.rawValue, preset: preset))
                    continue
                }
                let cellSamples = samples.filter { $0.scene == scene.rawValue && $0.presetLabel == preset.label }
                let key = Self.cellKey(scene: scene, preset: preset)
                let status: FieldTestCellStatus
                if case let .sampling(activeScene, activePreset) = phase, activeScene == scene, activePreset == preset {
                    status = .running
                } else if case let .waitingTracking(activeScene, activePreset) = phase, activeScene == scene, activePreset == preset {
                    status = .running
                } else if let stored = cellStatuses[key] {
                    status = stored
                } else {
                    status = .pending
                }
                let elapsed: TimeInterval
                if case let .sampling(activeScene, activePreset) = phase, activeScene == scene, activePreset == preset {
                    elapsed = Date().timeIntervalSince(cellStartedAt ?? Date())
                } else {
                    elapsed = 0
                }
                cells.append(FieldTestStatistics.summarizeCell(scene: scene.rawValue, preset: preset, samples: cellSamples, status: status, elapsed: elapsed))
            }
        }
        return FieldTestSummary(
            sessionID: id,
            updatedAt: Date(),
            phase: phaseName,
            cells: cells,
            testMode: plan.testMode,
            requestedScene: plan.requestedScene
        )
    }

    private func refreshSummary(phaseName: String) {
        guard handle?.sessionID != nil else { return }
        let sum = makeSummary(phaseName: phaseName)
        summary = sum
        persistOfficial(summary: sum)
    }

    private static func cellKey(scene: SIFTSceneLabel, preset: SIFTProcessingPreset) -> String {
        "\(scene.rawValue)|\(preset.label)"
    }

    private func rebuildStatusesFromSamples() {
        cellStatuses = [:]
        for scene in plan.scenes {
            for preset in presets {
                let cellSamples = samples.filter { $0.scene == scene.rawValue && $0.presetLabel == preset.label }
                let valid = cellSamples.filter(\.valid).count
                if valid >= FieldTestPolicy.targetValidSamples {
                    cellStatuses[Self.cellKey(scene: scene, preset: preset)] = .complete
                } else if !cellSamples.isEmpty {
                    cellStatuses[Self.cellKey(scene: scene, preset: preset)] = .incomplete
                }
            }
        }
    }

    private func persistMeta(phaseName: String) {
        record?.updatedAt = Date()
        refreshSummary(phaseName: phaseName)
    }

    private func persistOfficial(summary: FieldTestSummary) {
        guard let handle, var record = record else { return }
        record.updatedAt = Date()
        let samples = samples
        persistQueue.async { [weak self] in
            guard let self else { return }
            do {
                try handle.writeSummary(summary)
                try handle.writeSession(record)
                try handle.writeReport(session: record, summary: summary, samples: samples)
                DispatchQueue.main.async {
                    self.markPersistSuccess(persistedCount: samples.count)
                }
            } catch {
                DispatchQueue.main.async {
                    self.markPersistFailure(error)
                }
            }
        }
    }

    private func markPersistSuccess(persistedCount: Int) {
        persistedSampleCount = persistedCount
        lastSaveLabel = "Last save: \(Self.clock.string(from: Date()))"
        persistedSamplesLabel = "Persisted samples: \(persistedCount)"
        persistErrorLabel = nil
    }

    private func markPersistFailure(_ error: Error) {
        persistErrorLabel = error.localizedDescription
        lastSaveLabel = "Last save: FAILED"
    }

    private func refreshExportAvailability() {
        if !storageReady {
            exportLabel = "Export: Unavailable"
        } else if handle == nil {
            exportLabel = "Export: Unavailable"
        } else {
            let status = record?.status ?? "unknown"
            exportLabel = "Export: Available (\(status))"
        }
    }

    private static let clock: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return formatter
    }()
}

protocol FieldTestSampleSink: AnyObject {
    func ingest(
        result: SIFTFrameResult,
        tracking: String,
        skipped: Int,
        rateHz: Double,
        activePreset: SIFTProcessingPreset,
        matching: MatchingFrameResult?,
        camera: CameraIntrinsicsSnapshot?,
        pnp: PnPFrameResult?,
        confirmation: ConfirmationTick?,
        confirmationStats: ConfirmationStats?,
        arkitSidecar: ARKitCameraTransformSidecar?,
        alignment: AlignmentFrameResult?,
        alignmentStats: AlignmentStats?,
        wallDebugGeometry: WallAlignmentDebugGeometry?,
        routeBinding: RuntimeRouteBinding?,
        routeRenderPlan: RouteRenderPlan?
    ) -> Bool
}

extension FieldTestController: FieldTestSampleSink {}
