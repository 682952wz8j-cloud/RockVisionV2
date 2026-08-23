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
        let latest = try XCTUnwrap(reloaded.latestSession())
        let samples = try latest.loadSamples()
        XCTAssertEqual(samples.count, 2)
        XCTAssertEqual(samples[0].scene, "A")
        XCTAssertTrue(samples[0].valid)
        XCTAssertFalse(samples[1].valid)
        XCTAssertEqual(try latest.loadSession().siftParameters, SIFTParameterRecord.summary)

        let second = try store.createSession(openCVVersion: "4.14.0")
        XCTAssertNotEqual(second.sessionID, handle.sessionID)
        XCTAssertEqual(try handle.loadSamples().count, 2)
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
