import Combine
import Foundation

/// Field-test state machine. Does not extract SIFT or classify physical scenes.
final class FieldTestController: ObservableObject {
    @Published private(set) var phase: FieldTestPhase = .readyToStart(.A)
    @Published private(set) var instruction: String = "走到目标建筑，拿稳，点 START A"
    @Published private(set) var progressLabel: String = "—"
    @Published private(set) var elapsedLabel: String = "—"
    @Published private(set) var sessionPath: String = "—"
    @Published private(set) var canShare = false
    @Published private(set) var shareURL: URL?
    @Published private(set) var summary: FieldTestSummary?
    @Published private(set) var hasResumableSession = false
    @Published private(set) var isSampling = false

    private let store: FieldTestStore
    private let openCVVersion: String
    private var handle: FieldTestSessionHandle?
    private var record: FieldTestSessionRecord?
    private var samples: [FieldTestSample] = []
    private var cellStatuses: [String: FieldTestCellStatus] = [:]
    private var cellStartedAt: Date?
    private var timeoutTimer: Timer?
    private let persistQueue = DispatchQueue(label: "com.rockvision.v2.fieldtest.persist")

    var locksEngineerControls: Bool { isSampling }
    var onApplyScene: ((String) -> Void)?
    var onApplyPreset: ((SIFTProcessingPreset) -> Void)?
    var onSetLocked: ((Bool) -> Void)?

    init(store: FieldTestStore, openCVVersion: String) {
        self.store = store
        self.openCVVersion = openCVVersion
        if let existing = store.latestSession(),
           let session = try? existing.loadSession(),
           session.status == "running" {
            hasResumableSession = true
            handle = existing
            record = session
            samples = (try? existing.loadSamples()) ?? []
            rebuildStatusesFromSamples()
            sessionPath = existing.directory.path
            instruction = "发现未完成测试。点 Resume 继续，或 New Session 重新开始。"
            phase = .idle
            refreshSummary(phaseName: "interrupted")
        }
    }

    convenience init() {
        let store = (try? FieldTestStore.documentsStore()) ?? FieldTestStore(rootURL: FileManager.default.temporaryDirectory.appendingPathComponent("FieldTests", isDirectory: true))
        self.init(store: store, openCVVersion: OpenCVBridge.openCVVersion())
    }

    func startScene(_ scene: SIFTSceneLabel) {
        guard FieldTestPolicy.officialScenes.contains(scene) else { return }
        if handle == nil || record?.status == "complete" {
            beginNewSession()
        }
        beginCell(scene: scene, preset: .native)
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
        guard let record else { return }
        hasResumableSession = false
        if let sceneName = record.currentScene,
           let scene = SIFTSceneLabel(rawValue: sceneName),
           FieldTestPolicy.isOfficialScene(sceneName),
           let presetName = record.currentPreset,
           let preset = SIFTProcessingPreset.allCases.first(where: { $0.label == presetName }) {
            beginCell(scene: scene, preset: preset, restartClock: record.cellStartedAt == nil)
        } else {
            phase = .readyToStart(.A)
            instruction = "走到目标建筑，拿稳，点 START A"
        }
    }

    func startNewSession() {
        samples = []
        cellStatuses = [:]
        handle = nil
        record = nil
        hasResumableSession = false
        canShare = false
        shareURL = nil
        beginNewSession()
        phase = .readyToStart(.A)
        instruction = "走到目标建筑，拿稳，点 START A"
        progressLabel = "—"
        refreshSummary(phaseName: "ready")
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
    }

    func ingest(result: SIFTFrameResult, tracking: String, skipped: Int, rateHz: Double, activePreset: SIFTProcessingPreset) {
        guard isSampling else { return }
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
                return
            }
        }
        guard case let .sampling(scene, preset) = phase else { return }
        guard result.processingWidth == preset.targetWidth
                || (preset == .native && result.processingWidth == result.nativeImageWidth) else {
            return
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
            achievedRateHz: rateHz
        )

        persistQueue.async { [weak self] in
            guard let self else { return }
            try? self.handle?.append(sample)
            DispatchQueue.main.async {
                self.samples.append(sample)
                self.evaluateCurrentCell()
            }
        }
    }

    func flush() {
        persistMeta(phaseName: phaseName)
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

    private func beginNewSession() {
        do {
            let created = try store.createSession(openCVVersion: openCVVersion)
            handle = created
            record = try created.loadSession()
            samples = []
            sessionPath = created.directory.path
        } catch {
            instruction = "无法创建测试目录：\(error.localizedDescription)"
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
            beginCell(scene: scene, preset: nextPreset)
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
            instruction = "现场测试完成。结果已保存，可以离开现场。"
            canShare = true
            shareURL = handle?.reportURL
            onSetLocked?(false)
            persistMeta(phaseName: "complete")
        }
    }

    private func nextPreset(after preset: SIFTProcessingPreset) -> SIFTProcessingPreset? {
        guard let idx = FieldTestPolicy.resolutionOrder.firstIndex(of: preset) else { return nil }
        let next = idx + 1
        return next < FieldTestPolicy.resolutionOrder.count ? FieldTestPolicy.resolutionOrder[next] : nil
    }

    private func nextScene(after scene: SIFTSceneLabel) -> SIFTSceneLabel? {
        guard let idx = FieldTestPolicy.officialScenes.firstIndex(of: scene) else { return nil }
        let next = idx + 1
        return next < FieldTestPolicy.officialScenes.count ? FieldTestPolicy.officialScenes[next] : nil
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

    private func refreshSummary(phaseName: String) {
        guard let id = handle?.sessionID else { return }
        var cells: [FieldTestCellSummary] = []
        for scene in FieldTestPolicy.officialScenes {
            for preset in FieldTestPolicy.resolutionOrder {
                let cellSamples = samples.filter { $0.scene == scene.rawValue && $0.presetLabel == preset.label }
                let key = Self.cellKey(scene: scene, preset: preset)
                let status: FieldTestCellStatus
                if case let .sampling(activeScene, activePreset) = phase, activeScene == scene, activePreset == preset {
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
        let sum = FieldTestSummary(sessionID: id, updatedAt: Date(), phase: phaseName, cells: cells)
        summary = sum
        persistQueue.async { [weak self] in
            guard let self, let handle = self.handle, let record = self.record else { return }
            try? handle.writeSummary(sum)
            try? handle.writeReport(session: record, summary: sum, samples: self.samples)
        }
    }

    private static func cellKey(scene: SIFTSceneLabel, preset: SIFTProcessingPreset) -> String {
        "\(scene.rawValue)|\(preset.label)"
    }

    private func rebuildStatusesFromSamples() {
        cellStatuses = [:]
        for scene in FieldTestPolicy.officialScenes {
            for preset in FieldTestPolicy.resolutionOrder {
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
        persistQueue.async { [weak self] in
            guard let self, let handle = self.handle, var record = self.record else { return }
            record.updatedAt = Date()
            try? handle.writeSession(record)
        }
    }
}

protocol FieldTestSampleSink: AnyObject {
    func ingest(result: SIFTFrameResult, tracking: String, skipped: Int, rateHz: Double, activePreset: SIFTProcessingPreset)
}

extension FieldTestController: FieldTestSampleSink {}
