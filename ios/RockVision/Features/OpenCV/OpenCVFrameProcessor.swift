import ARKit
import Foundation
import os
import simd
import UIKit

/// Consumes ARFrames on a single serial queue. SIFT + matching + same-frame PnP,
/// then confirmation, then productionAlignment only if localized.
/// No second PnP / alignment timer, queue, or backlog.
///
/// ARKit stays full-rate. Processing is requested at 2 Hz and skip if busy.
final class OpenCVFrameProcessor: NSObject, ObservableObject, ARFrameConsumer {
    @Published private(set) var snapshot = OpenCVRuntimeSnapshot()
    @Published private(set) var siftSnapshot = SIFTRuntimeSnapshot()
    @Published private(set) var matchingSnapshot = MatchingRuntimeSnapshot()
    @Published private(set) var referenceAssetProvenance = ReferenceAssetProvenance.unavailable
    @Published private(set) var pnpSnapshot = PnPRuntimeSnapshot()
    @Published private(set) var confirmationSnapshot = ConfirmationRuntimeSnapshot()
    @Published private(set) var alignmentSnapshot = AlignmentRuntimeSnapshot()
    @Published private(set) var wallDebugSnapshot = WallDebugRuntimeSnapshot()
    @Published private(set) var wallDebugGeometry = WallAlignmentDebugGeometry.hidden
    @Published private(set) var runtimeRouteBinding = RuntimeRouteBinding.unbound
    @Published private(set) var routeRenderPlan = RouteRenderPlan.empty

    private let queue = DispatchQueue(label: "com.rockvision.v2.opencv", qos: .userInitiated)
    private let lock = NSLock()
    private let requestedInterval: TimeInterval = 0.50
    private var isProcessing = false
    private var lastAcceptedAt = Date.distantPast
    private var didLogCalibration = false
    private var didLogVersion = false
    private var didLogSIFTParams = false
    private let log = Logger(subsystem: "com.rockvision.v2", category: "OpenCV")

    private var skippedFrames = 0
    private var processedFrames = 0
    private var nextFrameID: UInt64 = 1
    private var startedAt = Date()
    private var currentPreset: SIFTProcessingPreset = .low
    private var showKeypoints = true
    private var viewSize: CGSize = .zero
    private var interfaceOrientation: UIInterfaceOrientation = .portrait
    private var cycleStartedAt = Date()
    private let cycleSeconds: TimeInterval = 20
    private var autoCycle = false
    private var currentScene = SIFTSceneLabel.unlabeled.rawValue
    private var didDumpSixty = false
    private var fieldTestLocked = false
    weak var fieldSink: FieldTestSampleSink?

    private var buckets: [SIFTProcessingPreset: ResolutionAccumulator] = [
        .native: ResolutionAccumulator(),
        .medium: ResolutionAccumulator(),
        .low: ResolutionAccumulator(),
    ]
    private var sceneBuckets: [String: [SIFTProcessingPreset: ResolutionAccumulator]] = [:]
    private var referenceDatabase: ReferenceDatabase?
    private enum ReferenceSourceMode: Sendable, Equatable {
        case bundleDevelopmentFixture
        case cloudCurrentJiulongfengDevR000001
    }

    /// Default on fresh launch: Bundle DevelopmentFixture.
    private var desiredReferenceSourceMode: ReferenceSourceMode = .bundleDevelopmentFixture
    private var loadedReferenceSourceMode: ReferenceSourceMode?
    private var debugCloudAssetServiceOverride: CloudAssetService?
    private var matchingStatus = "inactive"
    private var sim3: ValidatedSim3?
    private var measurementFixture: Gate4BMeasurementFixture?
    private var verifiedFrozenRoute: VerifiedFrozenRoute?
    private var confirmationEngine = LocalizationConfirmation()
    private var alignmentRuntime = ProductionAlignmentRuntime()
    private var fieldConfirmationBarrier = FieldConfirmationSessionBarrier()

    override init() {
        super.init()
        var initial = OpenCVRuntimeSnapshot()
        initial.version = OpenCVBridge.openCVVersion()
        initial.status = "inactive"
        snapshot = initial
        var sift = SIFTRuntimeSnapshot()
        sift.presetLabel = currentPreset.label
        sift.requestedRateHz = "2.0"
        sift.scene = currentScene
        siftSnapshot = sift
        startedAt = Date()
        cycleStartedAt = Date()
    }

    func updateViewContext(size: CGSize, orientation: UIInterfaceOrientation) {
        lock.lock()
        viewSize = size
        interfaceOrientation = orientation
        lock.unlock()
    }

    func cyclePreset() {
        setPreset(SIFTProcessingPreset(rawValue: (currentPreset.rawValue + 1) % SIFTProcessingPreset.allCases.count) ?? .native)
    }

    func setFieldTestLocked(_ locked: Bool) {
        lock.lock()
        fieldTestLocked = locked
        if locked {
            autoCycle = false
        }
        lock.unlock()
    }

    func applyFieldTestPreset(_ preset: SIFTProcessingPreset) {
        lock.lock()
        currentPreset = preset
        autoCycle = false
        let label = currentPreset.label
        lock.unlock()
        DispatchQueue.main.async {
            var next = self.siftSnapshot
            next.presetLabel = label
            self.siftSnapshot = next
        }
    }

    func applyFieldTestScene(_ scene: String) {
        guard SIFTSceneLabel(rawValue: scene) != nil else { return }
        lock.lock()
        currentScene = scene
        lock.unlock()
        DispatchQueue.main.async {
            var next = self.siftSnapshot
            next.scene = scene
            self.siftSnapshot = next
        }
    }

    func setPreset(_ preset: SIFTProcessingPreset) {
        lock.lock()
        if fieldTestLocked {
            lock.unlock()
            return
        }
        currentPreset = preset
        autoCycle = false
        let label = currentPreset.label
        lock.unlock()
        print("SIFT: manual preset \(label)")
        DispatchQueue.main.async {
            var next = self.siftSnapshot
            next.presetLabel = label
            self.siftSnapshot = next
        }
    }

    func cycleScene() {
        let labels = SIFTSceneLabel.allCases
        let idx = labels.firstIndex(where: { $0.rawValue == currentScene }) ?? 0
        setScene(labels[(idx + 1) % labels.count].rawValue)
    }

    func setScene(_ scene: String) {
        guard SIFTSceneLabel(rawValue: scene) != nil else { return }
        lock.lock()
        if fieldTestLocked {
            lock.unlock()
            return
        }
        currentScene = scene
        let preset = currentPreset
        dumpBucketLocked(preset, scene: scene)
        lock.unlock()
        print("SIFT: scene \(scene)")
        DispatchQueue.main.async {
            var next = self.siftSnapshot
            next.scene = scene
            self.siftSnapshot = next
        }
    }

    /// Reset confirmation on the existing OpenCV serial queue, then invoke `completion`.
    /// In-flight process blocks queued before this call run first (old engine) and must
    /// not be recorded: Field Test sampling starts only in `completion`.
    func resetConfirmation(completion: (() -> Void)? = nil) {
        queue.async { [weak self] in
            guard let self else {
                DispatchQueue.main.async { completion?() }
                return
            }
            self.confirmationEngine.reset()
            self.alignmentRuntime.reset()
            self.fieldConfirmationBarrier.noteResetCompletedOnProcessingQueue()
            DispatchQueue.main.async {
                self.confirmationSnapshot = ConfirmationRuntimeSnapshot()
                self.alignmentSnapshot = AlignmentRuntimeSnapshot()
                self.wallDebugSnapshot = WallDebugRuntimeSnapshot()
                self.wallDebugGeometry = .hidden
                self.runtimeRouteBinding = .unbound
                self.routeRenderPlan = .empty
                completion?()
            }
        }
    }

    func toggleKeypointOverlay() {
        lock.lock()
        showKeypoints.toggle()
        let visible = showKeypoints
        lock.unlock()
        DispatchQueue.main.async {
            var next = self.siftSnapshot
            next.showKeypoints = visible
            if !visible {
                next.overlayViewPoints = []
            }
            self.siftSnapshot = next
        }
    }

    func consumeARFrame(_ frame: ARFrame) {
        lock.lock()
        if autoCycle, Date().timeIntervalSince(cycleStartedAt) >= cycleSeconds {
            let previous = currentPreset
            currentPreset = SIFTProcessingPreset(rawValue: (currentPreset.rawValue + 1) % SIFTProcessingPreset.allCases.count) ?? .native
            cycleStartedAt = Date()
            dumpBucketLocked(previous)
        }
        let now = Date()
        if isProcessing || now.timeIntervalSince(lastAcceptedAt) < requestedInterval {
            skippedFrames += 1
            lock.unlock()
            return
        }
        isProcessing = true
        lastAcceptedAt = now
        let preset = currentPreset
        let size = viewSize
        let orientation = interfaceOrientation
        let showDots = showKeypoints
        let scene = currentScene
        lock.unlock()

        let buffer = frame.capturedImage
        let cameraMatrix = frame.camera.intrinsics
        let imageResolution = frame.camera.imageResolution
        let capturedWidth = CVPixelBufferGetWidth(buffer)
        let capturedHeight = CVPixelBufferGetHeight(buffer)
        let displayTransform = size.width > 1 && size.height > 1
            ? frame.displayTransform(for: orientation, viewportSize: size)
            : nil
        let timestamp = frame.timestamp
        let tracking = Self.trackingLabel(frame.camera.trackingState)
        let arkitSidecar = Self.sameARFrameSidecar(frame.camera.transform, timestamp: timestamp)

        queue.async { [weak self] in
            guard let self else { return }
            self.ensureFixtureLoaded()
            let diagnostics = OpenCVBridge.processPixelBuffer(buffer)
            let siftObj = OpenCVBridge.extractSIFT(
                from: buffer,
                targetWidth: Int32(preset.targetWidth),
                targetHeight: Int32(preset.targetHeight),
                overlayCap: showDots ? 200 : 0
            )

            let matching = self.matchIfNeeded(siftObj: siftObj, preset: preset)

            let intrinsics = CameraIntrinsicsValidator.make(
                cameraMatrix: cameraMatrix,
                imageResolution: imageResolution,
                capturedWidth: capturedWidth,
                capturedHeight: capturedHeight
            )

            let result = self.makeResult(siftObj, timestamp: timestamp)
            let stampedSidecar = arkitSidecar.stamped(frameID: result.frameID, timestamp: result.timestamp)
            let pnp: PnPFrameResult
            let confirmationTick: ConfirmationTick?
            let confirmationStats: ConfirmationStats?
            let alignmentResult: AlignmentFrameResult
            let alignmentStats: AlignmentStats?
            if matching.status == "active" {
                pnp = RuntimePnP.evaluate(
                    matching: matching,
                    camera: intrinsics,
                    sim3: self.sim3,
                    frameID: result.frameID,
                    timestamp: result.timestamp
                )
                self.fieldConfirmationBarrier.prepareCandidateIngest(&self.confirmationEngine)
                if self.fieldConfirmationBarrier.needsFreshEngine {
                    self.alignmentRuntime.reset()
                }
                let tick = self.confirmationEngine.ingest(pnp)
                confirmationTick = tick
                confirmationStats = self.confirmationEngine.stats
                alignmentResult = self.alignmentRuntime.update(
                    confirmation: tick,
                    pnp: pnp,
                    arkit: stampedSidecar,
                    sim3: self.sim3
                )
                alignmentStats = self.alignmentRuntime.stats
            } else {
                pnp = .inactive(reason: matching.status)
                confirmationTick = nil
                confirmationStats = nil
                alignmentResult = self.alignmentRuntime.noteNoCandidate()
                alignmentStats = nil
            }
            let overlay = showDots ? self.viewPoints(from: result.overlayNative, nativeWidth: result.nativeImageWidth, nativeHeight: result.nativeImageHeight, transform: displayTransform, viewSize: size) : []

            self.lock.lock()
            self.isProcessing = false
            self.processedFrames += 1
            let processed = self.processedFrames
            let skipped = self.skippedFrames
            let elapsed = Date().timeIntervalSince(self.startedAt)
            let rate = elapsed > 0 ? Double(processed) / elapsed : 0
            if result.ok {
                self.buckets[preset, default: ResolutionAccumulator()].add(result)
                if scene != "unlabeled" {
                    var byPreset = self.sceneBuckets[scene, default: [:]]
                    var acc = byPreset[preset, default: ResolutionAccumulator()]
                    acc.add(result)
                    byPreset[preset] = acc
                    self.sceneBuckets[scene] = byPreset
                }
            }
            if !self.didDumpSixty, elapsed >= 60 {
                self.didDumpSixty = true
                self.dumpAllBucketsLocked()
                print("SIFTStability: 60s processed=\(processed) skipped=\(skipped) rate=\(String(format: "%.2f", rate))")
            }
            let shouldLogCalibration = !self.didLogCalibration && intrinsics.isValid
            if shouldLogCalibration { self.didLogCalibration = true }
            let shouldLogVersion = !self.didLogVersion
            if shouldLogVersion { self.didLogVersion = true }
            let shouldLogParams = !self.didLogSIFTParams
            if shouldLogParams { self.didLogSIFTParams = true }
            self.lock.unlock()

            if shouldLogVersion {
                print("OpenCVBridge: version=\(OpenCVBridge.openCVVersion())")
            }
            if shouldLogCalibration {
                print("OpenCVBridge: calibration \(intrinsics.summary)")
            }
            if shouldLogParams {
                print("SIFT params: \(SIFTParameterRecord.summary)")
            }
            if processed == 1 || processed % 5 == 0 {
                print(
                    "SIFTBench: scene=\(scene) res=\(result.processingLabel) kp=\(result.keypointCount) desc=\(result.descriptorLabel) grid=\(result.gridLabel) finite=\(result.descriptorsFinite) match=\(result.rowsMatchKeypoints) pre=\(String(format: "%.2f", result.preprocessLatencyMs)) sift=\(String(format: "%.2f", result.siftLatencyMs)) total=\(String(format: "%.2f", result.totalLatencyMs)) accepted=\(matching.acceptedAfterRatio) unique3D=\(matching.acceptedUniquePoint3D) matchMs=\(String(format: "%.2f", matching.matchingLatencyMs)) stage3=\(String(format: "%.2f", matching.stage3TotalMs)) pnp=\(pnp.status) pnpIn=\(pnp.inputCorrespondenceCount) inliers=\(pnp.inlierCount) cand=\(pnp.candidateQualified) rate=\(String(format: "%.2f", rate)) skipped=\(skipped)"
                )
            }

            let routeBindingForSample = RuntimeRouteBinding.evaluate(
                verifiedRoute: self.verifiedFrozenRoute,
                alignment: alignmentResult
            )
            let routePlanForSample = RouteRenderPlan.evaluate(from: routeBindingForSample)
            // Persistence / field-test bookkeeping is after SIFT timing and must not
            // mutate preprocess/sift/total latency on the result.
            let recorded = self.fieldSink?.ingest(
                result: result,
                tracking: tracking,
                skipped: skipped,
                rateHz: rate,
                activePreset: preset,
                matching: matching,
                camera: intrinsics,
                pnp: matching.status == "active" ? pnp : nil,
                confirmation: confirmationTick,
                confirmationStats: confirmationStats,
                arkitSidecar: matching.status == "active" ? stampedSidecar : nil,
                alignment: matching.status == "active" ? alignmentResult : nil,
                alignmentStats: matching.status == "active" ? alignmentStats : nil,
                wallDebugGeometry: matching.status == "active"
                    ? WallAlignmentDebugGeometry.evaluate(
                        alignment: alignmentResult,
                        measurementFixture: self.measurementFixture,
                        currentWallID: self.referenceDatabase?.wallId
                    )
                    : nil,
                routeBinding: matching.status == "active" ? routeBindingForSample : nil,
                routeRenderPlan: matching.status == "active" ? routePlanForSample : nil
            ) ?? false
            if matching.status == "active" {
                self.fieldConfirmationBarrier.noteFieldDecision(
                    recorded: recorded,
                    engine: &self.confirmationEngine
                )
                if self.fieldConfirmationBarrier.needsFreshEngine {
                    self.alignmentRuntime.reset()
                }
            }
            let confirmationHUDIdle = matching.status == "active"
                && !recorded
                && self.fieldConfirmationBarrier.needsFreshEngine
            let debugGeometry = confirmationHUDIdle
                ? WallAlignmentDebugGeometry.hidden
                : WallAlignmentDebugGeometry.evaluate(
                    alignment: alignmentResult,
                    measurementFixture: self.measurementFixture,
                    currentWallID: self.referenceDatabase?.wallId
                )
            let routeBinding = confirmationHUDIdle
                ? RuntimeRouteBinding.unbound
                : routeBindingForSample
            let routePlan = confirmationHUDIdle
                ? RouteRenderPlan.empty
                : routePlanForSample

            DispatchQueue.main.async {
                var next = self.snapshot
                next.status = diagnostics?.status ?? "inactive"
                next.version = OpenCVBridge.openCVVersion()
                next.input = diagnostics?.inputDescription ?? "—"
                if let diagnostics, diagnostics.ok {
                    next.matSize = "\(diagnostics.cols) × \(diagnostics.rows)"
                    next.mean = String(format: "%.1f", diagnostics.meanIntensity)
                    next.latencyMs = String(format: "%.2f", diagnostics.latencyMilliseconds)
                }
                next.pixelFormat = diagnostics?.pixelFormat ?? "—"
                next.nativeImageSize = "\(capturedWidth) × \(capturedHeight)"
                next.intrinsicsValid = intrinsics.isValid
                next.sampleCount = processed
                self.snapshot = next

                var sift = self.siftSnapshot
                sift.status = result.ok ? "active" : (result.error ?? "inactive")
                sift.processing = result.processingLabel
                sift.keypoints = result.ok ? "\(result.keypointCount)" : "—"
                sift.descriptors = result.ok ? result.descriptorLabel : "—"
                sift.grid = result.ok ? result.gridLabel : "—"
                sift.preprocessMs = result.ok ? String(format: "%.2f", result.preprocessLatencyMs) : "—"
                sift.siftMs = result.ok ? String(format: "%.2f", result.siftLatencyMs) : "—"
                sift.totalMs = result.ok ? String(format: "%.2f", result.totalLatencyMs) : "—"
                sift.rateHz = String(format: "%.2f", rate)
                sift.skipped = skipped
                sift.presetLabel = preset.label
                sift.requestedRateHz = "2.0"
                sift.scene = scene
                sift.showKeypoints = showDots
                sift.overlayViewPoints = overlay
                self.siftSnapshot = sift

                var matchingSnap = self.matchingSnapshot
                matchingSnap.status = matching.status
                matchingSnap.queryKeypoints = matching.status == "active" ? "\(matching.queryKeypoints)" : "—"
                matchingSnap.acceptedAfterRatio = matching.status == "active" ? "\(matching.acceptedAfterRatio)" : "—"
                matchingSnap.acceptedUniquePoint3D = matching.status == "active" ? "\(matching.acceptedUniquePoint3D)" : "—"
                matchingSnap.ratioRejected = matching.status == "active" ? "\(matching.ratioRejected)" : "—"
                matchingSnap.insufficientDistinctPoint3D = matching.status == "active" ? "\(matching.insufficientDistinctPoint3D)" : "—"
                matchingSnap.matchingMs = matching.status == "active" ? String(format: "%.2f", matching.matchingLatencyMs) : "—"
                matchingSnap.stage3Ms = matching.status == "active" ? String(format: "%.2f", matching.stage3TotalMs) : "—"
                matchingSnap.referenceRows = matching.referenceDescriptorCount > 0 ? "\(matching.referenceDescriptorCount)" : "—"
                self.matchingSnapshot = matchingSnap
                self.pnpSnapshot = RuntimePnP.snapshot(from: pnp)
                if confirmationHUDIdle {
                    self.confirmationSnapshot = ConfirmationRuntimeSnapshot()
                    self.alignmentSnapshot = AlignmentRuntimeSnapshot()
                    self.wallDebugSnapshot = WallDebugRuntimeSnapshot()
                    self.wallDebugGeometry = .hidden
                    self.runtimeRouteBinding = .unbound
                    self.routeRenderPlan = .empty
                } else {
                    if let confirmationTick {
                        self.confirmationSnapshot = ConfirmationSnapshot.make(confirmationTick)
                    }
                    self.alignmentSnapshot = AlignmentSnapshot.make(alignmentResult)
                    self.wallDebugGeometry = debugGeometry
                    self.wallDebugSnapshot = WallDebugSnapshot.make(debugGeometry)
                    self.runtimeRouteBinding = routeBinding
                    self.routeRenderPlan = routePlan
                }
            }
        }
    }

    private static func sameARFrameSidecar(
        _ transform: simd_float4x4,
        timestamp: TimeInterval
    ) -> ARKitCameraTransformSidecar {
        let columns: [[Double]] = (0..<4).map { col in
            (0..<4).map { row in Double(transform[col][row]) }
        }
        return .capture(columnMajor4x4: columns, timestamp: timestamp)
    }

    func dumpAllBuckets() {
        lock.lock()
        dumpAllBucketsLocked()
        lock.unlock()
    }

    private func ensureFixtureLoaded() {
        let mode = desiredReferenceSourceMode
        guard loadedReferenceSourceMode != mode else { return }
        loadedReferenceSourceMode = mode

        do {
            let loaded: LoadedReferenceAssets
            switch mode {
            case .bundleDevelopmentFixture:
                loaded = try ReferenceAssetSession.load(.developmentFixture())
            case .cloudCurrentJiulongfengDevR000001:
                let expectedWallId = "wall_jiulongfeng_01_dev"
                let expectedReleaseId = "r000001"

                let service: CloudAssetService
                if let override = debugCloudAssetServiceOverride {
                    service = override
                } else {
                    service = try CloudAssetService.default()
                }
                loaded = try ReferenceAssetSession.load(.cloudValidatedRelease(wallId: expectedWallId, service: service))

                // Fail-closed: CURRENT identity must match this exact release.
                guard loaded.provenance.wallId == expectedWallId,
                      loaded.provenance.releaseId == expectedReleaseId else {
                    throw ReferenceAssetError.integrityRejected("cloud CURRENT identity mismatch (expected \(expectedWallId)/\(expectedReleaseId), got \(loaded.provenance.wallId)/\(loaded.provenance.releaseId))")
                }
            }

            referenceDatabase = loaded.database
            referenceAssetProvenance = loaded.provenance
            matchingStatus = "active"
            print("Matching: loaded reference source=\(loaded.provenance.source) wall=\(loaded.provenance.wallId) release=\(loaded.provenance.releaseId) rows=\(loaded.database.descriptorCount) unique3D=\(Set(loaded.database.point3dIds).count) notAWallPackage=\(loaded.database.notAWallPackage)")
        } catch {
            referenceDatabase = nil
            referenceAssetProvenance = .unavailable
            matchingStatus = (error as? LocalizedError)?.errorDescription ?? String(describing: error)
            print("Matching: inactive \(matchingStatus)")
        }
        sim3 = ValidatedSim3Loader.loadFromBundle(.main)
        measurementFixture = Gate4BMeasurementFixture.loadFromBundle(.main)
        verifiedFrozenRoute = VerifiedFrozenRoute.loadFromBundle(.main)
        if let sim3 {
            print("PnP: loaded S_wall_colmap status=\(sim3.status) scale=\(sim3.scale) metric-only")
        } else {
            print("PnP: S_wall_colmap missing; C_wall / observation-depth meters unavailable")
        }
    }

    // MARK: - DEBUG-only reference source selection

    /// Development-only: allow explicit source selection between Bundle fixture and
    /// Cloud CURRENT (wall_jiulongfeng_01_dev / r000001).
    func selectReferenceSourceBundleDevelopmentFixture() {
        lock.lock()
        desiredReferenceSourceMode = .bundleDevelopmentFixture
        loadedReferenceSourceMode = nil
        referenceDatabase = nil
        referenceAssetProvenance = .unavailable
        matchingStatus = "inactive (select Bundle fixture)"
        lock.unlock()
    }

    /// Development-only: select Cloud CURRENT with strict identity enforcement.
    func selectReferenceSourceCloudCurrentJiulongfengDevR000001() {
        lock.lock()
        desiredReferenceSourceMode = .cloudCurrentJiulongfengDevR000001
        loadedReferenceSourceMode = nil
        referenceDatabase = nil
        referenceAssetProvenance = .unavailable
        matchingStatus = "inactive (select Cloud CURRENT)"
        lock.unlock()
    }

    #if DEBUG
    func debugSetCloudAssetServiceOverrideForSelection(_ service: CloudAssetService?) {
        lock.lock()
        debugCloudAssetServiceOverride = service
        lock.unlock()
    }

    /// Force load using the currently selected reference mode.
    /// Intended for unit tests only.
    func debugForceReferenceSourceLoadForTesting() {
        ensureFixtureLoaded()
    }

    var debugDesiredReferenceSourceMode: String {
        switch desiredReferenceSourceMode {
        case .bundleDevelopmentFixture: return "bundleDevelopmentFixture"
        case .cloudCurrentJiulongfengDevR000001: return "cloudCurrentJiulongfengDevR000001"
        }
    }
    #endif

    private func matchIfNeeded(siftObj: OpenCVSIFTResult?, preset: SIFTProcessingPreset) -> MatchingFrameResult {
        let siftTotal = siftObj?.totalMilliseconds ?? 0
        guard preset == .low else {
            return .inactive(reason: "960×720 only", siftTotalMs: siftTotal)
        }
        guard let database = referenceDatabase else {
            return .inactive(reason: matchingStatus, siftTotalMs: siftTotal)
        }
        guard let siftObj, siftObj.ok else {
            return .inactive(reason: siftObj?.error ?? "sift not ok", siftTotalMs: siftTotal)
        }
        let nativeX = siftObj.nativeX.map(\.doubleValue)
        let nativeY = siftObj.nativeY.map(\.doubleValue)
        return RuntimeMatcher.match(
            queryDescriptors: siftObj.descriptorData,
            descriptorRows: Int(siftObj.descriptorRows),
            descriptorCols: Int(siftObj.descriptorCols),
            descriptorsFinite: siftObj.descriptorsFinite,
            nativeX: nativeX,
            nativeY: nativeY,
            database: database,
            siftTotalMs: siftTotal
        )
    }

    private func dumpAllBucketsLocked() {
        for preset in SIFTProcessingPreset.allCases {
            dumpBucketLocked(preset)
        }
        for scene in ["A", "B", "C"] {
            guard let byPreset = sceneBuckets[scene] else { continue }
            for preset in SIFTProcessingPreset.allCases {
                guard let bucket = byPreset[preset], !bucket.keypoints.isEmpty else { continue }
                print(bucket.summary(label: preset.label, scene: scene))
            }
        }
    }

    private func dumpBucketLocked(_ preset: SIFTProcessingPreset, scene: String? = nil) {
        guard let bucket = buckets[preset] else { return }
        print(bucket.summary(label: preset.label, scene: scene))
    }

    private func makeResult(_ obj: OpenCVSIFTResult?, timestamp: TimeInterval) -> SIFTFrameResult {
        let frameID: UInt64
        lock.lock()
        frameID = nextFrameID
        nextFrameID += 1
        lock.unlock()
        guard let obj else {
            return .empty(frameID: frameID, timestamp: timestamp, error: "nil SIFT result")
        }
        let xs = obj.nativeX.map(\.doubleValue)
        let ys = obj.nativeY.map(\.doubleValue)
        let points = zip(xs, ys).map { CGPoint(x: $0, y: $1) }
        let overlay = zip(obj.overlayNativeX.map(\.doubleValue), obj.overlayNativeY.map(\.doubleValue)).map { CGPoint(x: $0, y: $1) }
        let grid = SIFTGrid.occupancy(
            nativePoints: points,
            nativeWidth: Int(obj.nativeWidth),
            nativeHeight: Int(obj.nativeHeight)
        )
        return SIFTFrameResult(
            frameID: frameID,
            timestamp: timestamp,
            ok: obj.ok,
            status: obj.status,
            nativeImageWidth: Int(obj.nativeWidth),
            nativeImageHeight: Int(obj.nativeHeight),
            processingWidth: Int(obj.processingWidth),
            processingHeight: Int(obj.processingHeight),
            scaleX: obj.scaleX,
            scaleY: obj.scaleY,
            keypointCount: Int(obj.keypointCount),
            descriptorCount: Int(obj.descriptorRows),
            descriptorDimension: Int(obj.descriptorCols),
            descriptorType: obj.descriptorTypeName,
            descriptorRows: Int(obj.descriptorRows),
            descriptorCols: Int(obj.descriptorCols),
            descriptorsFinite: obj.descriptorsFinite,
            rowsMatchKeypoints: obj.rowsMatchKeypoints,
            preprocessLatencyMs: obj.preprocessMilliseconds,
            siftLatencyMs: obj.siftMilliseconds,
            totalLatencyMs: obj.totalMilliseconds,
            gridCounts: grid.counts,
            occupiedCells: grid.occupied,
            occupancyRatio: grid.ratio,
            keypointsNative: [],
            overlayNative: overlay,
            error: obj.error
        )
    }

    private func viewPoints(
        from native: [CGPoint],
        nativeWidth: Int,
        nativeHeight: Int,
        transform: CGAffineTransform?,
        viewSize: CGSize
    ) -> [CGPoint] {
        guard nativeWidth > 0, nativeHeight > 0, viewSize.width > 1, viewSize.height > 1 else { return [] }
        return native.map { point in
            var normalized = CGPoint(x: point.x / CGFloat(nativeWidth), y: point.y / CGFloat(nativeHeight))
            if let transform {
                normalized = normalized.applying(transform)
            }
            return CGPoint(x: normalized.x * viewSize.width, y: normalized.y * viewSize.height)
        }
    }

    private static func trackingLabel(_ state: ARCamera.TrackingState) -> String {
        switch state {
        case .notAvailable:
            return "notAvailable"
        case .normal:
            return "normal"
        case .limited(let reason):
            switch reason {
            case .initializing: return "limited(initializing)"
            case .excessiveMotion: return "limited(excessiveMotion)"
            case .insufficientFeatures: return "limited(insufficientFeatures)"
            case .relocalizing: return "limited(relocalizing)"
            @unknown default: return "limited(unknown)"
            }
        }
    }
}

struct ResolutionAccumulator {
    var keypoints: [Int] = []
    var occupancy: [Double] = []
    var preprocess: [Double] = []
    var sift: [Double] = []
    var total: [Double] = []

    mutating func add(_ result: SIFTFrameResult) {
        keypoints.append(result.keypointCount)
        occupancy.append(result.occupancyRatio)
        preprocess.append(result.preprocessLatencyMs)
        sift.append(result.siftLatencyMs)
        total.append(result.totalLatencyMs)
        if keypoints.count > 200 {
            keypoints.removeFirst(keypoints.count - 200)
            occupancy.removeFirst(occupancy.count - 200)
            preprocess.removeFirst(preprocess.count - 200)
            sift.removeFirst(sift.count - 200)
            total.removeFirst(total.count - 200)
        }
    }

    func summary(label: String) -> String {
        func fmt(_ values: [Double]) -> String {
            let minV = values.min().map { String(format: "%.2f", $0) } ?? "—"
            let med = SIFTStatistics.percentile(values, 50).map { String(format: "%.2f", $0) } ?? "—"
            let p90 = SIFTStatistics.percentile(values, 90).map { String(format: "%.2f", $0) } ?? "—"
            let maxV = values.max().map { String(format: "%.2f", $0) } ?? "—"
            return "min=\(minV) med=\(med) p90=\(p90) max=\(maxV)"
        }
        func fmtI(_ values: [Int]) -> String {
            let minV = values.min().map(String.init) ?? "—"
            let med = SIFTStatistics.percentile(values, 50).map(String.init) ?? "—"
            let p90 = SIFTStatistics.percentile(values, 90).map(String.init) ?? "—"
            let maxV = values.max().map(String.init) ?? "—"
            return "min=\(minV) med=\(med) p90=\(p90) max=\(maxV) n=\(values.count)"
        }
        let occMed = SIFTStatistics.percentile(occupancy, 50).map { String(format: "%.2f", $0) } ?? "—"
        return "SIFTSummary \(label) kp[\(fmtI(keypoints))] occ_med=\(occMed) pre[\(fmt(preprocess))] sift[\(fmt(sift))] total[\(fmt(total))]"
    }

    func summary(label: String, scene: String?) -> String {
        if let scene, scene != "unlabeled" {
            return "SIFTSceneSummary scene=\(scene) " + summary(label: label)
        }
        return summary(label: label)
    }
}

/// Gate 3A grayscale diagnostics. Localization is not derived from this.
struct OpenCVRuntimeSnapshot: Equatable, Sendable {
    var status: String = "inactive"
    var version: String = "—"
    var input: String = "—"
    var matSize: String = "—"
    var mean: String = "—"
    var latencyMs: String = "—"
    var pixelFormat: String = "—"
    var zeroCopy: Bool = false
    var uiOrientation: String = "—"
    var nativeImageSize: String = "—"
    var intrinsicsValid: Bool = false
    var droppedBusy: Bool = false
    var sampleCount: Int = 0
    var minIntensity: Double = 0
    var maxIntensity: Double = 0
}
