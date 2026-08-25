import XCTest
@testable import RockVision

final class FieldTestStoreTests: XCTestCase {
    private var tempRoot: URL!

    override func setUpWithError() throws {
        tempRoot = FileManager.default.temporaryDirectory.appendingPathComponent("FieldTest-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: tempRoot, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tempRoot)
    }

    func testValidSampleFilter() {
        XCTAssertTrue(FieldTestPolicy.isValidSample(ok: true, tracking: "normal", descriptorsFinite: true, rowsMatchKeypoints: true))
        XCTAssertFalse(FieldTestPolicy.isValidSample(ok: true, tracking: "limited(initializing)", descriptorsFinite: true, rowsMatchKeypoints: true))
        XCTAssertFalse(FieldTestPolicy.isValidSample(ok: false, tracking: "normal", descriptorsFinite: true, rowsMatchKeypoints: true))
        XCTAssertFalse(FieldTestPolicy.isValidSample(ok: true, tracking: "normal", descriptorsFinite: false, rowsMatchKeypoints: true))
        XCTAssertFalse(FieldTestPolicy.isValidSample(ok: true, tracking: "normal", descriptorsFinite: true, rowsMatchKeypoints: false))
        XCTAssertFalse(FieldTestPolicy.isOfficialScene("unlabeled"))
        XCTAssertTrue(FieldTestPolicy.isOfficialScene("A"))
    }

    func testLaunchGateDoesNotChangeSampleValidity() {
        XCTAssertTrue(FieldTestPolicy.isValidSample(ok: true, tracking: "normal", descriptorsFinite: true, rowsMatchKeypoints: true))
        XCTAssertEqual(
            FieldTestLaunchGate.blockReason(
                storageReady: true,
                tracking: "normal",
                matchingStatus: "active",
                presetLabel: SIFTProcessingPreset.low.label,
                processingLabel: "960 × 720"
            ),
            nil
        )
        XCTAssertNotNil(
            FieldTestLaunchGate.blockReason(
                storageReady: true,
                tracking: "limited(initializing)",
                matchingStatus: "active",
                presetLabel: SIFTProcessingPreset.low.label,
                processingLabel: "960 × 720"
            )
        )
        XCTAssertNotNil(
            FieldTestLaunchGate.blockReason(
                storageReady: true,
                tracking: "normal",
                matchingStatus: "inactive",
                presetLabel: SIFTProcessingPreset.low.label,
                processingLabel: "960 × 720"
            )
        )
        XCTAssertNotNil(
            FieldTestLaunchGate.blockReason(
                storageReady: true,
                tracking: "normal",
                matchingStatus: "active",
                presetLabel: SIFTProcessingPreset.native.label,
                processingLabel: "1920 × 1440"
            )
        )
        XCTAssertTrue(FieldTestPolicy.isValidSample(ok: true, tracking: "normal", descriptorsFinite: true, rowsMatchKeypoints: true))
    }

    func testTwentySampleAndNinetySecondPolicy() {
        XCTAssertEqual(FieldTestPolicy.cellStatus(validCount: 19, elapsed: 89), nil)
        XCTAssertEqual(FieldTestPolicy.cellStatus(validCount: 20, elapsed: 10), .complete)
        XCTAssertEqual(FieldTestPolicy.cellStatus(validCount: 7, elapsed: 90), .incomplete)
        XCTAssertEqual(FieldTestPolicy.cellStatus(validCount: 19, elapsed: 90), .incomplete)
        XCTAssertEqual(FieldTestPolicy.cellStatus(validCount: 0, elapsed: 90), .incomplete)
        XCTAssertNil(FieldTestPolicy.cellStatus(validCount: 10, elapsed: 40))
    }

    func testSummaryUsesOnlyValidSamples() {
        var samples = (0..<5).map { makeSample(scene: "A", preset: .native, valid: true, keypoints: 100 + $0, pre: 1, sift: 10, total: 11) }
        samples.append(makeSample(scene: "A", preset: .native, valid: false, keypoints: 9999, pre: 50, sift: 500, total: 550))
        let summary = FieldTestStatistics.summarizeCell(scene: "A", preset: .native, samples: samples, status: .incomplete, elapsed: 90)
        XCTAssertEqual(summary.validCount, 5)
        XCTAssertEqual(summary.invalidCount, 1)
        XCTAssertEqual(summary.progressLabel, "5/20")
        XCTAssertEqual(summary.status, .incomplete)
        XCTAssertEqual(summary.keypoints?.max, 104)
        XCTAssertEqual(summary.siftMs?.max, 10)
    }

    func testLatencyCopiedVerbatimNotInflatedByPersistence() {
        let result = makeSample(scene: "A", preset: .low, valid: true, keypoints: 12, pre: 0.27, sift: 61.08, total: 61.35)
        XCTAssertEqual(result.preprocessLatencyMs, 0.27, accuracy: 1e-12)
        XCTAssertEqual(result.siftLatencyMs, 61.08, accuracy: 1e-12)
        XCTAssertEqual(result.totalLatencyMs, 61.35, accuracy: 1e-12)
        XCTAssertEqual(result.totalLatencyMs, result.preprocessLatencyMs + result.siftLatencyMs, accuracy: 1e-9)
    }

    func testStoreSurvivesRelaunchAndDoesNotRequireSceneGuessing() throws {
        let store = FieldTestStore(rootURL: tempRoot)
        let handle = try store.createSession(openCVVersion: "4.14.0")
        try handle.append(makeSample(scene: "A", preset: .native, valid: true, keypoints: 200, pre: 0, sift: 80, total: 80))
        try handle.append(makeSample(scene: "A", preset: .native, valid: false, keypoints: 1, pre: 0, sift: 80, total: 80, tracking: "limited(initializing)"))

        let reloaded = FieldTestStore(rootURL: tempRoot)
        let latest = try XCTUnwrap(try reloaded.latestSession())
        let samples = try latest.loadSamples()
        XCTAssertEqual(samples.count, 2)
        XCTAssertEqual(samples[0].scene, "A")
        XCTAssertTrue(samples[0].valid)
        XCTAssertFalse(samples[1].valid)
        XCTAssertEqual(try latest.loadSession().siftParameters, SIFTParameterRecord.summary)

        XCTAssertTrue(handle.sessionID.hasPrefix("gate4b_"))

        let second = try store.createSession(openCVVersion: "4.14.0")
        XCTAssertNotEqual(second.sessionID, handle.sessionID)
        XCTAssertEqual(try handle.loadSamples().count, 2)
        XCTAssertTrue(handle.sessionID.hasPrefix("gate4b_"))
    }

    func testControllerDoesNotRecordUntilUserStartsOfficialScene() {
        let store = FieldTestStore(rootURL: tempRoot)
        let controller = FieldTestController(store: store, openCVVersion: "4.14.0")
        let result = dummyResult(width: 1920, height: 1440, keypoints: 100)
        controller.ingest(result: result, tracking: "normal", skipped: 0, rateHz: 2, activePreset: .native)
        XCTAssertEqual(controller.phase, .readyToStart(.A))
        XCTAssertNil(controller.summary)
    }

    func testControllerCollectsTwentyValidThenAdvancesResolution() {
        let store = FieldTestStore(rootURL: tempRoot)
        let controller = FieldTestController(store: store, openCVVersion: "4.14.0")
        var applied: [SIFTProcessingPreset] = []
        controller.onApplyPreset = { applied.append($0) }
        controller.startScene(.A)
        XCTAssertEqual(controller.phase, .waitingTracking(scene: .A, preset: .native))

        let result = dummyResult(width: 1920, height: 1440, keypoints: 250)
        for i in 0..<20 {
            var frame = result
            frame.frameID = UInt64(i + 1)
            controller.ingest(result: frame, tracking: "normal", skipped: i, rateHz: 2, activePreset: .native)
        }
        let advanced = expectation(description: "persist then advance")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            if case let .waitingTracking(scene, preset) = controller.phase {
                XCTAssertEqual(scene, .A)
                XCTAssertEqual(preset, .medium)
            } else if case let .sampling(scene, preset) = controller.phase {
                XCTAssertEqual(scene, .A)
                XCTAssertEqual(preset, .medium)
            } else {
                XCTFail("expected next resolution, got \(controller.phase)")
            }
            XCTAssertEqual(controller.progressLabel, "0/20")
            XCTAssertTrue(applied.contains(.medium))
            advanced.fulfill()
        }
        wait(for: [advanced], timeout: 1.0)
    }

    func testInvalidTrackingDoesNotCountTowardTwenty() {
        let store = FieldTestStore(rootURL: tempRoot)
        let controller = FieldTestController(store: store, openCVVersion: "4.14.0")
        controller.startScene(.A)
        let result = dummyResult(width: 1920, height: 1440, keypoints: 250)
        controller.ingest(result: result, tracking: "limited(initializing)", skipped: 0, rateHz: 1, activePreset: .native)
        let done = expectation(description: "invalid ignored for counting")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            if case .waitingTracking = controller.phase {
                XCTAssertEqual(controller.progressLabel, "0/20")
            } else if case .sampling = controller.phase {
                XCTAssertEqual(controller.progressLabel, "0/20")
            }
            done.fulfill()
        }
        wait(for: [done], timeout: 1.0)
    }

    func testRelaunchReloadsSamples() throws {
        let store = FieldTestStore(rootURL: tempRoot)
        let first = FieldTestController(store: store, openCVVersion: "4.14.0")
        first.startScene(.A)
        let result = dummyResult(width: 1920, height: 1440, keypoints: 80)
        first.ingest(result: result, tracking: "normal", skipped: 3, rateHz: 1.9, activePreset: .native)
        let written = expectation(description: "written")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            written.fulfill()
        }
        wait(for: [written], timeout: 1.0)

        let second = FieldTestController(store: store, openCVVersion: "4.14.0")
        XCTAssertTrue(second.hasResumableSession)
        XCTAssertFalse(second.sessionPath == "—")
    }

    func testStorageProbeWriteReadDelete() throws {
        let store = FieldTestStore(rootURL: tempRoot)
        try store.probeStorage()
        let leftover = try FileManager.default.contentsOfDirectory(at: tempRoot, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("storage_probe_") }
        XCTAssertTrue(leftover.isEmpty)
        XCTAssertFalse(leftover.contains { $0.pathExtension == "keep" })
    }

    func testStorageProbeFailureBlocksStart() throws {
        let fileRoot = tempRoot.appendingPathComponent("not-a-dir")
        try Data("x".utf8).write(to: fileRoot)
        let store = FieldTestStore(rootURL: fileRoot)
        let controller = FieldTestController(store: store, openCVVersion: "4.14.0")
        XCTAssertFalse(controller.storageReady)
        XCTAssertFalse(controller.canStartTest)
        XCTAssertTrue(controller.storageLabel.contains("Failed"))
        controller.startScene(.A)
        XCTAssertEqual(controller.phase, .idle)
        XCTAssertFalse(controller.canExport)
    }

    func testPartialRunningSessionExportZIP() throws {
        let staging = tempRoot.appendingPathComponent("zip-staging", isDirectory: true)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
        let store = FieldTestStore(rootURL: tempRoot.appendingPathComponent("official", isDirectory: true))
        let controller = FieldTestController(
            store: store,
            openCVVersion: "4.14.0",
            identity: FieldTestAppIdentity(version: "2.0.0", build: "1"),
            zipStagingRoot: staging
        )
        XCTAssertTrue(controller.storageReady)
        controller.startScene(.A)
        let result = dummyResult(width: 1920, height: 1440, keypoints: 321)
        for i in 0..<3 {
            var frame = result
            frame.frameID = UInt64(i + 1)
            controller.ingest(result: frame, tracking: "normal", skipped: 0, rateHz: 2, activePreset: .native)
        }
        let ingested = expectation(description: "samples persisted")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { ingested.fulfill() }
        wait(for: [ingested], timeout: 1.0)
        controller.drainPersist()
        XCTAssertEqual(controller.persistedSampleCount, 3)
        XCTAssertTrue(controller.canExport)
        XCTAssertTrue(controller.exportLabel.contains("Available"))

        controller.shareCurrentResults()
        let zip = try XCTUnwrap(controller.shareZIPURL)
        XCTAssertTrue(zip.path.contains("zip-staging") || zip.path.contains("FieldTestExport") || zip.path.hasPrefix(staging.path))
        XCTAssertFalse(zip.path.hasPrefix(store.rootURL.path))

        let unpacked = try FieldTestZip.unpack(zip)
        for name in FieldTestExport.requiredNames {
            XCTAssertNotNil(unpacked[name], "missing \(name)")
        }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let manifest = try decoder.decode(FieldTestExportManifest.self, from: try XCTUnwrap(unpacked["manifest.json"]))
        XCTAssertEqual(manifest.schemaVersion, FieldTestExportSchema.version)
        XCTAssertEqual(manifest.sampleCount, 3)
        XCTAssertEqual(manifest.sessionStatus, "running")
        XCTAssertEqual(manifest.openCVVersion, "4.14.0")
        XCTAssertEqual(manifest.appVersion, "2.0.0")
        XCTAssertEqual(manifest.appBuild, "1")
        XCTAssertEqual(manifest.files.count, 4)
        XCTAssertTrue(manifest.files.contains { $0.name == "samples.jsonl" && $0.byteSize > 0 && !$0.sha256.isEmpty })

        let samplesText = String(data: try XCTUnwrap(unpacked["samples.jsonl"]), encoding: .utf8) ?? ""
        XCTAssertTrue(samplesText.contains("\"scene\":\"A\""))
        XCTAssertTrue(samplesText.contains("321") || samplesText.contains("\"keypointCount\":321"))

        let session = try decoder.decode(FieldTestSessionRecord.self, from: try XCTUnwrap(unpacked["session.json"]))
        XCTAssertEqual(session.status, "running")
        XCTAssertEqual(session.openCVVersion, "4.14.0")

        let summary = try decoder.decode(FieldTestSummary.self, from: try XCTUnwrap(unpacked["summary.json"]))
        XCTAssertEqual(summary.sessionID, session.sessionID)
        XCTAssertTrue(summary.cells.contains { $0.scene == "A" && $0.validCount == 3 })
        XCTAssertFalse(summary.cells.contains { $0.status == .complete })

        let officialFiles = try FileManager.default.contentsOfDirectory(at: URL(fileURLWithPath: controller.sessionPath), includingPropertiesForKeys: nil)
        XCTAssertTrue(officialFiles.contains { $0.lastPathComponent == "samples.jsonl" })
        XCTAssertTrue(officialFiles.contains { $0.lastPathComponent == "report.json" })
        XCTAssertFalse(officialFiles.contains { $0.pathExtension == "zip" })
    }

    func testPasteSummaryIsHumanReadableNotRawJSON() {
        let store = FieldTestStore(rootURL: tempRoot)
        let controller = FieldTestController(
            store: store,
            openCVVersion: "4.14.0",
            identity: FieldTestAppIdentity(version: "2.0.0", build: "1")
        )
        controller.startScene(.A)
        let text = controller.copySummary()
        XCTAssertTrue(text.contains("RockVision Gate 4B Field Test"))
        XCTAssertTrue(text.contains("schema: gate4b.runtime.1"))
        XCTAssertTrue(text.contains("status:"))
        XCTAssertTrue(text.contains("OpenCV: 4.14.0"))
        XCTAssertFalse(text.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("{"))
        XCTAssertFalse(text.contains("\"sessionID\""))
    }

    func testDeviceDocumentsOfficialExportSmoke() throws {
        #if targetEnvironment(simulator)
        throw XCTSkip("requires a physical iPhone Documents directory")
        #else
        let store = try FieldTestStore.documentsStore()
        try store.probeStorage()
        let leftover = try FileManager.default.contentsOfDirectory(at: store.rootURL, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("storage_probe_") }
        XCTAssertTrue(leftover.isEmpty)

        let staging = FileManager.default.temporaryDirectory.appendingPathComponent("device-export-\(UUID().uuidString)", isDirectory: true)
        let controller = FieldTestController(
            store: store,
            openCVVersion: "4.14.0",
            identity: FieldTestAppIdentity(version: "2.0.0", build: "1"),
            zipStagingRoot: staging
        )
        XCTAssertTrue(controller.storageReady)
        controller.startScene(.A)
        var frame = dummyResult(width: 1920, height: 1440, keypoints: 111)
        frame.frameID = 42
        controller.ingest(result: frame, tracking: "normal", skipped: 0, rateHz: 2, activePreset: .native)
        let ingested = expectation(description: "device sample")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { ingested.fulfill() }
        wait(for: [ingested], timeout: 1.0)
        controller.drainPersist()
        controller.shareCurrentResults()
        let zip = try XCTUnwrap(controller.shareZIPURL)
        XCTAssertFalse(zip.path.hasPrefix(store.rootURL.path))
        let unpacked = try FieldTestZip.unpack(zip)
        for name in FieldTestExport.requiredNames {
            XCTAssertNotNil(unpacked[name], "missing \(name)")
        }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let manifest = try decoder.decode(FieldTestExportManifest.self, from: try XCTUnwrap(unpacked["manifest.json"]))
        XCTAssertEqual(manifest.sampleCount, 1)
        XCTAssertEqual(manifest.sessionStatus, "running")
        #endif
    }

    func testAbortedSessionCanExport() throws {
        let staging = tempRoot.appendingPathComponent("abort-zip", isDirectory: true)
        let store = FieldTestStore(rootURL: tempRoot.appendingPathComponent("abort-official", isDirectory: true))
        let controller = FieldTestController(
            store: store,
            openCVVersion: "4.14.0",
            identity: FieldTestAppIdentity(version: "2.0.0", build: "1"),
            zipStagingRoot: staging
        )
        controller.startScene(.A)
        controller.abort()
        XCTAssertTrue(controller.canExport)
        controller.shareCurrentResults()
        let zip = try XCTUnwrap(controller.shareZIPURL)
        let unpacked = try FieldTestZip.unpack(zip)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let manifest = try decoder.decode(FieldTestExportManifest.self, from: try XCTUnwrap(unpacked["manifest.json"]))
        XCTAssertEqual(manifest.sessionStatus, "aborted")
        XCTAssertNotNil(unpacked["samples.jsonl"])
        XCTAssertNotNil(unpacked["report.json"])
    }

    func testConvenienceInitDoesNotUseTemporaryDirectoryForOfficialStore() throws {
        let docs = try FieldTestStore.documentsDirectory()
        XCTAssertFalse(docs.path.contains("/tmp/") && docs.lastPathComponent == "FieldTests")
        let store = try FieldTestStore.documentsStore()
        XCTAssertTrue(store.rootURL.path.hasPrefix(docs.path))
        XCTAssertEqual(store.rootURL.lastPathComponent, "FieldTests")
    }

    func testSceneBOnlyStartsBWithoutA() {
        let store = FieldTestStore(rootURL: tempRoot)
        let controller = FieldTestController(store: store, openCVVersion: "4.14.0")
        XCTAssertEqual(controller.phase, .readyToStart(.A))
        controller.selectPlan(.single(.B))
        XCTAssertEqual(controller.plan.testMode, "singleScene")
        XCTAssertEqual(controller.plan.requestedScene, "B")
        XCTAssertEqual(controller.phase, .readyToStart(.B))
        controller.startOfficialNext()
        XCTAssertEqual(controller.phase, .waitingTracking(scene: .B, preset: .native))
        controller.startScene(.A)
        if case let .waitingTracking(scene, _) = controller.phase {
            XCTAssertEqual(scene, .B)
        } else {
            XCTFail("A must not replace B-only sampling")
        }
    }

    func testSceneBOnlyCompletesWithoutACSamplesAndExportsSingleScene() throws {
        let staging = tempRoot.appendingPathComponent("b-only-zip", isDirectory: true)
        let official = tempRoot.appendingPathComponent("b-only-official", isDirectory: true)
        let store = FieldTestStore(rootURL: official)
        let previous = try store.createSession(openCVVersion: "4.14.0", plan: .full)
        var prior = try previous.loadSession()
        prior.status = "complete"
        try previous.writeSession(prior)
        try previous.append(makeSample(scene: "A", preset: .native, valid: true, keypoints: 99, pre: 0, sift: 10, total: 10))
        let priorID = previous.sessionID

        let controller = FieldTestController(
            store: store,
            openCVVersion: "4.14.0",
            identity: FieldTestAppIdentity(version: "2.0.0", build: "1"),
            zipStagingRoot: staging
        )
        controller.selectPlan(.single(.B))
        controller.startScene(.B)
        XCTAssertNotEqual(controller.sessionPath, previous.directory.path)

        ingestValid(controller, preset: .native, width: 1920, height: 1440, count: 20, startID: 1)
        waitBrief()
        ingestValid(controller, preset: .medium, width: 1280, height: 960, count: 20, startID: 21)
        waitBrief()
        ingestValid(controller, preset: .low, width: 960, height: 720, count: 20, startID: 41)
        waitBrief()
        controller.drainPersist()

        XCTAssertEqual(controller.phase, .complete)
        XCTAssertEqual(controller.persistedSampleCount, 60)
        let written = try String(contentsOf: URL(fileURLWithPath: controller.sessionPath).appendingPathComponent("samples.jsonl"), encoding: .utf8)
        XCTAssertFalse(written.contains("\"scene\":\"A\""))
        XCTAssertFalse(written.contains("\"scene\":\"C\""))
        XCTAssertTrue(written.contains("\"scene\":\"B\""))
        let cells = try XCTUnwrap(controller.summary?.cells)
        XCTAssertTrue(cells.contains { $0.scene == "A" && $0.status == .notRequested && $0.progressLabel == "notRequested" })
        XCTAssertTrue(cells.contains { $0.scene == "C" && $0.status == .notRequested })
        XCTAssertFalse(cells.contains { $0.scene == "A" && $0.status == .pending })
        XCTAssertFalse(cells.contains { $0.scene == "B" && $0.status == .incomplete })
        XCTAssertEqual(cells.filter { $0.scene == "B" && $0.status == .complete }.count, 3)

        controller.shareCurrentResults()
        let zip = try XCTUnwrap(controller.shareZIPURL)
        let unpacked = try FieldTestZip.unpack(zip)
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let manifest = try decoder.decode(FieldTestExportManifest.self, from: try XCTUnwrap(unpacked["manifest.json"]))
        XCTAssertEqual(manifest.testMode, "singleScene")
        XCTAssertEqual(manifest.requestedScene, "B")
        XCTAssertEqual(manifest.sessionStatus, "complete")
        XCTAssertEqual(manifest.sampleCount, 60)
        let session = try decoder.decode(FieldTestSessionRecord.self, from: try XCTUnwrap(unpacked["session.json"]))
        XCTAssertEqual(session.testMode, "singleScene")
        XCTAssertEqual(session.requestedScene, "B")
        let summary = try decoder.decode(FieldTestSummary.self, from: try XCTUnwrap(unpacked["summary.json"]))
        XCTAssertEqual(summary.testMode, "singleScene")
        XCTAssertEqual(summary.requestedScene, "B")
        let samplesText = String(data: try XCTUnwrap(unpacked["samples.jsonl"]), encoding: .utf8) ?? ""
        XCTAssertFalse(samplesText.contains("\"scene\":\"A\""))
        XCTAssertFalse(samplesText.contains("\"scene\":\"C\""))
        XCTAssertTrue(samplesText.contains("\"scene\":\"B\""))

        let priorSamples = try previous.loadSamples()
        XCTAssertEqual(priorSamples.count, 1)
        XCTAssertEqual(priorSamples[0].scene, "A")
        XCTAssertEqual(try previous.loadSession().sessionID, priorID)
        XCTAssertEqual(try previous.loadSession().status, "complete")
    }

    func testFullABCWorkflowStillStartsAtAAndAdvancesToB() {
        let store = FieldTestStore(rootURL: tempRoot)
        let controller = FieldTestController(store: store, openCVVersion: "4.14.0")
        XCTAssertEqual(controller.plan.testMode, "full")
        XCTAssertNil(controller.plan.requestedScene)
        controller.startScene(.A)
        ingestValid(controller, preset: .native, width: 1920, height: 1440, count: 20, startID: 1)
        waitBrief()
        ingestValid(controller, preset: .medium, width: 1280, height: 960, count: 20, startID: 21)
        waitBrief()
        ingestValid(controller, preset: .low, width: 960, height: 720, count: 20, startID: 41)
        waitBrief()
        if case let .readyToStartNext(finished, next) = controller.phase {
            XCTAssertEqual(finished, .A)
            XCTAssertEqual(next, .B)
        } else {
            XCTFail("full workflow should wait for START B, got \(controller.phase)")
        }
        XCTAssertNotEqual(controller.phase, .complete)
    }

    func testGate3CAppPresetsAre960OnlyAndDoNotAdvanceResolution() {
        XCTAssertEqual(FieldTestPolicy.resolutionOrder, [.native, .medium, .low])
        let store = FieldTestStore(rootURL: tempRoot)
        let controller = FieldTestController(store: store, openCVVersion: "4.14.0", presets: [.low])
        controller.startScene(.A)
        XCTAssertEqual(controller.phase, .waitingTracking(scene: .A, preset: .low))
        ingestValid(controller, preset: .low, width: 960, height: 720, count: 20, startID: 1)
        waitBrief()
        if case let .readyToStartNext(finished, next) = controller.phase {
            XCTAssertEqual(finished, .A)
            XCTAssertEqual(next, .B)
        } else {
            XCTFail("960-only Field Test should finish Scene A after one cell, got \(controller.phase)")
        }
        let cells = controller.summary?.cells ?? []
        XCTAssertTrue(cells.contains { $0.scene == "A" && $0.presetLabel == SIFTProcessingPreset.low.label && $0.status == .complete })
        XCTAssertTrue(cells.contains { $0.scene == "A" && $0.presetLabel == SIFTProcessingPreset.native.label && $0.status == .notRequested })
        XCTAssertTrue(cells.contains { $0.scene == "A" && $0.presetLabel == SIFTProcessingPreset.medium.label && $0.status == .notRequested })
    }

    func testMatchingDiagnosticsPersistAndOldSamplesDecode() throws {
        let store = FieldTestStore(rootURL: tempRoot)
        let controller = FieldTestController(store: store, openCVVersion: "4.14.0")
        controller.startScene(.A)
        var frame = dummyResult(width: 1920, height: 1440, keypoints: 80)
        frame.frameID = 9
        let matching = MatchingFrameResult(
            status: "active",
            queryKeypoints: 80,
            referenceDescriptorCount: 47207,
            rawDescriptorCandidates: 100,
            uniquePoint3DCandidates: 40,
            insufficientDistinctPoint3D: 2,
            ratioRejected: 10,
            acceptedAfterRatio: 12,
            acceptedUniquePoint3D: 11,
            duplicatePoint3DRejected: 1,
            candidateKTruncatedQueries: 0,
            bestDistanceMedian: 0.21,
            bestRatioMedian: 0.55,
            matchingLatencyMs: 33.5,
            stage3TotalMs: 73.7,
            diagnosticMatches: [
                DiagnosticMatch(
                    queryXY: [10, 20],
                    distance: 0.2,
                    ratio: 0.5,
                    point3DID: 99,
                    referenceImageID: 4,
                    referenceImageName: "DJI_TEST.JPG",
                    referenceXY: [12, 34]
                )
            ],
            pnpCorrespondences: [
                PnPCorrespondence(
                    queryIndex: 0,
                    queryXYNative: [10, 20],
                    point3DID: 99,
                    referenceRow: 4,
                    colmapXYZ: [1, 2, 3],
                    ratio: 0.5,
                    descriptorDistance: 0.2,
                    queryCoordinateSpace: "nativeCapturedImage"
                )
            ],
            xyzMissingRejected: 0,
            inputCorrespondenceCount: 1
        )
        let pnp = RuntimePnP.evaluate(matching: matching, camera: nativeCamera(), sim3: nil)
        XCTAssertEqual(pnp.status, "insufficientCorrespondences")
        controller.ingest(result: frame, tracking: "normal", skipped: 0, rateHz: 2, activePreset: .native, matching: matching, camera: nativeCamera(), pnp: pnp)
        waitBrief()
        controller.drainPersist()
        let samples = try FieldTestStore(rootURL: tempRoot).latestSession()?.loadSamples() ?? []
        XCTAssertEqual(samples.count, 1)
        XCTAssertEqual(samples[0].acceptedUniquePoint3D, 11)
        XCTAssertEqual(samples[0].matchingLatencyMs, 33.5)
        XCTAssertEqual(samples[0].stage3TotalMs, 73.7)
        XCTAssertEqual(samples[0].diagnosticMatches?.count, 1)
        XCTAssertEqual(samples[0].diagnosticMatches?.first?.point3DID, 99)
        XCTAssertEqual(samples[0].totalLatencyMs, 40.2, accuracy: 1e-12)
        XCTAssertEqual(samples[0].pnpCorrespondences?.count, 1)
        XCTAssertEqual(samples[0].pnpCorrespondences?.first?.queryCoordinateSpace, "nativeCapturedImage")
        XCTAssertEqual(samples[0].inputCorrespondenceCount, 1)
        XCTAssertEqual(samples[0].cameraSidecar?.queryCoordinateSpace, "nativeCapturedImage")
        XCTAssertEqual(samples[0].cameraSidecar?.distortionModel, "zeros")
        XCTAssertEqual(samples[0].cameraSidecar?.capturedWidth, 1920)
        XCTAssertEqual(samples[0].cameraSidecar?.imageResolutionWidth, 1920)
        XCTAssertTrue(samples[0].cameraSidecar?.pnpIntrinsicsReady == true)
        XCTAssertEqual(try XCTUnwrap(samples[0].cameraSidecar?.cameraMatrix[0][0]), 1450, accuracy: 0.01)
        XCTAssertEqual(samples[0].pnpDiagnostic?.status, "insufficientCorrespondences")
        XCTAssertEqual(samples[0].pnpDiagnostic?.localizationState, "idle")
        XCTAssertFalse(samples[0].pnpDiagnostic?.candidateQualified == true)
        XCTAssertEqual(samples[0].pnpDiagnostic?.inputCorrespondenceCount, 1)

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let legacy = """
        {"recordedAt":"2026-08-24T04:00:00Z","frameID":1,"timestamp":1,"scene":"A","processingWidth":960,"processingHeight":720,"presetLabel":"960×720","keypointCount":12,"occupiedCells":12,"occupancyRatio":1,"preprocessLatencyMs":0.2,"siftLatencyMs":40,"totalLatencyMs":40.2,"tracking":"normal","valid":true,"descriptorRows":12,"descriptorDimension":128,"descriptorsFinite":true,"rowsMatchKeypoints":true,"skippedFrames":0,"achievedRateHz":2}
        """.data(using: .utf8)!
        let old = try decoder.decode(FieldTestSample.self, from: legacy)
        XCTAssertNil(old.acceptedUniquePoint3D)
        XCTAssertNil(old.diagnosticMatches)
        XCTAssertNil(old.pnpCorrespondences)
        XCTAssertNil(old.cameraSidecar)
        XCTAssertNil(old.pnpDiagnostic)
        XCTAssertNil(old.confirmation)
        XCTAssertNil(old.arkitSidecar)
        XCTAssertEqual(old.keypointCount, 12)
        XCTAssertTrue(old.valid)
        XCTAssertEqual(FieldTestExportSchema.version, "gate4b.runtime.1")
        XCTAssertEqual(FieldTestExportSchema.legacyRuntimeVersion, "gate4a.runtime.1")
        XCTAssertEqual(FieldTestExportSchema.legacyOfflineVersion, "gate3d.export.1")
        XCTAssertEqual(FieldTestExportSchema.provenanceRuntimeBaseline, "gate4a_20260825_104607")
    }

    private func nativeCamera() -> CameraIntrinsicsSnapshot {
        CameraIntrinsicsSnapshot(
            fx: 1450,
            fy: 1450,
            cx: 960,
            cy: 720,
            cameraMatrix: PnPSyntheticFixture.cameraMatrix,
            referenceWidth: 1920,
            referenceHeight: 1440,
            capturedWidth: 1920,
            capturedHeight: 1440
        )
    }

    private func ingestValid(
        _ controller: FieldTestController,
        preset: SIFTProcessingPreset,
        width: Int,
        height: Int,
        count: Int,
        startID: UInt64
    ) {
        let result = dummyResult(width: width, height: height, keypoints: 80)
        for i in 0..<count {
            var frame = result
            frame.frameID = startID + UInt64(i)
            controller.ingest(result: frame, tracking: "normal", skipped: 0, rateHz: 2, activePreset: preset)
        }
    }

    private func waitBrief() {
        let exp = expectation(description: "persist")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { exp.fulfill() }
        wait(for: [exp], timeout: 1.0)
    }

    private func makeSample(
        scene: String,
        preset: SIFTProcessingPreset,
        valid: Bool,
        keypoints: Int,
        pre: Double,
        sift: Double,
        total: Double,
        tracking: String = "normal"
    ) -> FieldTestSample {
        FieldTestSample(
            recordedAt: Date(),
            frameID: 1,
            timestamp: 1,
            scene: scene,
            processingWidth: preset.targetWidth,
            processingHeight: preset.targetHeight,
            presetLabel: preset.label,
            keypointCount: keypoints,
            occupiedCells: valid ? 12 : 1,
            occupancyRatio: valid ? 1 : 0.08,
            preprocessLatencyMs: pre,
            siftLatencyMs: sift,
            totalLatencyMs: total,
            tracking: tracking,
            valid: valid,
            invalidReason: valid ? nil : "tracking=\(tracking)",
            descriptorRows: keypoints,
            descriptorDimension: 128,
            descriptorsFinite: true,
            rowsMatchKeypoints: true,
            skippedFrames: 0,
            achievedRateHz: 2
        )
    }

    private func dummyResult(width: Int, height: Int, keypoints: Int) -> SIFTFrameResult {
        SIFTFrameResult(
            frameID: 1,
            timestamp: 1,
            ok: true,
            status: "active",
            nativeImageWidth: 1920,
            nativeImageHeight: 1440,
            processingWidth: width,
            processingHeight: height,
            scaleX: Double(width) / 1920.0,
            scaleY: Double(height) / 1440.0,
            keypointCount: keypoints,
            descriptorCount: keypoints,
            descriptorDimension: 128,
            descriptorType: "CV_32F",
            descriptorRows: keypoints,
            descriptorCols: 128,
            descriptorsFinite: true,
            rowsMatchKeypoints: true,
            preprocessLatencyMs: 0.2,
            siftLatencyMs: 40,
            totalLatencyMs: 40.2,
            gridCounts: Array(repeating: 1, count: 12),
            occupiedCells: 12,
            occupancyRatio: 1,
            keypointsNative: [],
            overlayNative: [],
            error: nil
        )
    }
}
