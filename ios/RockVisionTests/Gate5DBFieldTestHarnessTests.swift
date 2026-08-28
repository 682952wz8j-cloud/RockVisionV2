import XCTest
@testable import RockVision

final class Gate5DBFieldTestHarnessTests: XCTestCase {
    private var tempRoot: URL!

    override func setUp() {
        super.setUp()
        tempRoot = FileManager.default.temporaryDirectory.appendingPathComponent("gate5db-\(UUID().uuidString)", isDirectory: true)
        try? FileManager.default.createDirectory(at: tempRoot, withIntermediateDirectories: true)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: tempRoot)
        super.tearDown()
    }

    func testGate5DBCompletesSceneAWithoutStartingBOrC() {
        let controller = makeGate5DBController()
        var resetCount = 0
        controller.onResetConfirmation = { completion in
            resetCount += 1
            completion()
        }
        controller.selectPlan(.gate5DBPhysicalValidation)
        XCTAssertTrue(controller.plan.developmentValidationOnly)
        XCTAssertEqual(controller.plan.scenes, [.A])
        controller.startOfficialNext()
        XCTAssertEqual(resetCount, 1)
        ingestValid(controller, count: 20)
        waitBrief()
        XCTAssertEqual(controller.phase, .physicalValidationReady)
        XCTAssertFalse(controller.isSampling)
        XCTAssertNotEqual(controller.phase, .readyToStartNext(finished: .A, next: .B))
        XCTAssertNotEqual(controller.phase, .complete)
        XCTAssertEqual(resetCount, 1)
        controller.startOfficialNext()
        XCTAssertEqual(controller.phase, .physicalValidationReady)
        XCTAssertEqual(resetCount, 1)
        XCTAssertTrue(controller.canExport)
    }

    func testGate4BFullFlowStillAdvancesToSceneB() {
        let store = FieldTestStore(rootURL: tempRoot)
        let controller = FieldTestController(store: store, openCVVersion: "4.14.0", presets: [.low])
        XCTAssertEqual(controller.plan.testMode, "full")
        controller.startScene(.A)
        ingestValid(controller, count: 20)
        waitBrief()
        if case let .readyToStartNext(finished, next) = controller.phase {
            XCTAssertEqual(finished, .A)
            XCTAssertEqual(next, .B)
        } else {
            XCTFail("Gate 4B must still wait for START B, got \(controller.phase)")
        }
    }

    func testSceneACompleteStopsOfficialSampleIngestion() {
        let controller = makeGate5DBController()
        controller.selectPlan(.gate5DBPhysicalValidation)
        controller.startOfficialNext()
        ingestValid(controller, count: 20)
        waitBrief()
        let countAfterComplete = controller.persistedSampleCount
        XCTAssertEqual(countAfterComplete, 20)
        ingestValid(controller, count: 5, startID: 100)
        waitBrief()
        XCTAssertEqual(controller.persistedSampleCount, countAfterComplete)
        XCTAssertEqual(controller.phase, .physicalValidationReady)
    }

    func testSceneACompleteDoesNotResetConfirmationOrCreateNewSession() {
        let controller = makeGate5DBController()
        var resetCount = 0
        controller.onResetConfirmation = { completion in
            resetCount += 1
            completion()
        }
        controller.selectPlan(.gate5DBPhysicalValidation)
        controller.startOfficialNext()
        let sessionPath = controller.sessionPath
        ingestValid(controller, count: 20)
        waitBrief()
        XCTAssertEqual(resetCount, 1)
        XCTAssertEqual(controller.sessionPath, sessionPath)
        XCTAssertTrue(controller.canExport)
        XCTAssertFalse(controller.isSampling)
    }

    func testShareIsAvailableAfterSceneAButIsNotRequiredToKeepSession() {
        let controller = makeGate5DBController()
        controller.selectPlan(.gate5DBPhysicalValidation)
        controller.startOfficialNext()
        ingestValid(controller, count: 20)
        waitBrief()
        XCTAssertTrue(controller.canExport)
        let actions = Gate4BPhysicalValidationHUD.actions(
            hasResumableSession: false,
            phase: controller.phase,
            canExport: controller.canExport
        )
        XCTAssertTrue(actions.showShareResults)
        XCTAssertFalse(actions.showStartMeasurement)
        XCTAssertEqual(controller.phase, .physicalValidationReady)
    }

    func testBindingAndPlanStillEvaluateAfterSamplingStops() {
        let unbound = RuntimeRouteBinding.unbound
        XCTAssertFalse(RouteRenderPlan.evaluate(from: unbound).wouldRender)
        let points = (0..<11).map { i in [Double(i), 0.0, 1.0] }
        let bound = RuntimeRouteBinding(
            routeId: "route_test_01",
            hashVerified: true,
            hasBoundRoute: true,
            routeARWorldPointCount: 11,
            routeARWorldPoints: points,
            renderedRoute: false,
            reason: nil
        )
        let plan = RouteRenderPlan.evaluate(from: bound)
        XCTAssertTrue(plan.wouldRender)
        XCTAssertEqual(plan.segmentCount, 10)
        let lost = RouteRenderPlan.evaluate(from: .unbound)
        XCTAssertFalse(lost.wouldRender)
        let rebound = RouteRenderPlan.evaluate(from: bound)
        XCTAssertEqual(rebound.arWorldEndpoints, points)
        XCTAssertNotEqual(rebound.arWorldEndpoints, lost.arWorldEndpoints)
    }

    func testHarnessDoesNotCallSceneAdvanceOrInAppRecording() throws {
        let source = try readHostSource("RockVision/Features/FieldTest/FieldTestController.swift")
        XCTAssertTrue(source.contains("isGate5DBPhysicalValidation"))
        XCTAssertTrue(source.contains("enterPhysicalValidationReady"))
        XCTAssertTrue(source.contains("if plan.isGate5DBPhysicalValidation"))
        XCTAssertFalse(source.contains("AVAssetWriter"))
        XCTAssertFalse(source.contains("ReplayKit"))
        XCTAssertFalse(source.contains("RPScreenRecorder"))
        let panel = try readHostSource("RockVision/Features/FieldTest/FieldTestPanel.swift")
        XCTAssertTrue(panel.contains("Gate 5D-B test-only"))
        XCTAssertFalse(panel.contains("AVAssetWriter"))
        XCTAssertEqual(FieldTestExportSchema.version, "gate5da.runtime.1")
    }

    func testExportSchemaUnchangedForGate5DBHarness() {
        XCTAssertEqual(FieldTestExportSchema.version, "gate5da.runtime.1")
        XCTAssertEqual(FieldTestRunPlan.gate5DBPhysicalValidation.testMode, "gate5dbPhysicalValidation")
        XCTAssertTrue(FieldTestRunPlan.gate5DBPhysicalValidation.developmentValidationOnly)
    }

    // MARK: - Helpers

    private func makeGate5DBController() -> FieldTestController {
        FieldTestController(
            store: FieldTestStore(rootURL: tempRoot),
            openCVVersion: "4.14.0",
            presets: [.low]
        )
    }

    private func ingestValid(_ controller: FieldTestController, count: Int, startID: UInt64 = 1) {
        let result = SIFTFrameResult(
            frameID: 1,
            timestamp: 1,
            ok: true,
            status: "active",
            nativeImageWidth: 1920,
            nativeImageHeight: 1440,
            processingWidth: 960,
            processingHeight: 720,
            scaleX: 960.0 / 1920.0,
            scaleY: 720.0 / 1440.0,
            keypointCount: 80,
            descriptorCount: 80,
            descriptorDimension: 128,
            descriptorType: "CV_32F",
            descriptorRows: 80,
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
        for i in 0..<count {
            var frame = result
            frame.frameID = startID + UInt64(i)
            _ = controller.ingest(result: frame, tracking: "normal", skipped: 0, rateHz: 2, activePreset: .low)
        }
    }

    private func waitBrief() {
        let exp = expectation(description: "persist")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { exp.fulfill() }
        wait(for: [exp], timeout: 1.0)
    }

    private func readHostSource(_ relative: String) throws -> String {
        let path = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(relative)
            .path
        guard FileManager.default.isReadableFile(atPath: path) else {
            throw XCTSkip("host source tree not readable")
        }
        return try String(contentsOfFile: path, encoding: .utf8)
    }
}
