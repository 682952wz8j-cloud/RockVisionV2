import XCTest
@testable import RockVision

/// Regression for gate3e_20260825_065523 frame 13: in-flight process on the OpenCV
/// serial queue must not record a pre-reset confirmation lifetime into a new session.
final class FieldConfirmationSessionBarrierTests: XCTestCase {
    func testFirstRecordedSampleDoesNotInheritPreResetWindowOrCounters() {
        var engine = LocalizationConfirmation()
        var barrier = FieldConfirmationSessionBarrier()
        seedPreSessionLifetime(&engine)

        barrier.noteResetCompletedOnProcessingQueue()
        XCTAssertTrue(barrier.needsFreshEngine)

        barrier.prepareCandidateIngest(&engine)
        let first = engine.ingest(qualified(frameID: 14, yawDeg: 0, wall: [0, 0, 0], tvec: [0, 0, 6]))
        barrier.noteFieldDecision(recorded: true, engine: &engine)

        XCTAssertEqual(first.localizationState, "confirming")
        XCTAssertEqual(first.windowCount, 1)
        XCTAssertEqual(first.windowFrameIDs, [14])
        XCTAssertNil(first.confirmedT_opencvCam_colmap)
        XCTAssertNil(engine.stats.firstLocalizedSequence)
        XCTAssertEqual(engine.stats.pnpEvaluations, 1)
        XCTAssertEqual(engine.stats.qualifiedCount, 1)
        XCTAssertEqual(engine.stats.currentStreak, 1)
        XCTAssertFalse(barrier.needsFreshEngine)
    }

    func testUnrecordedInFlightAfterResetIsDiscardedAndDoesNotStartSessionLifetime() {
        var engine = LocalizationConfirmation()
        var barrier = FieldConfirmationSessionBarrier()
        seedPreSessionLifetime(&engine)

        barrier.noteResetCompletedOnProcessingQueue()
        barrier.prepareCandidateIngest(&engine)
        let discarded = engine.ingest(qualified(frameID: 13, yawDeg: 0, wall: [0.2, 0, 0], tvec: [0.2, 0, 6]))
        XCTAssertEqual(discarded.windowCount, 1)
        XCTAssertEqual(discarded.windowFrameIDs, [13])
        barrier.noteFieldDecision(recorded: false, engine: &engine)
        XCTAssertTrue(barrier.needsFreshEngine)
        XCTAssertEqual(engine.localizationState, "idle")
        XCTAssertEqual(engine.stats.pnpEvaluations, 0)

        barrier.prepareCandidateIngest(&engine)
        let first = engine.ingest(qualified(frameID: 14, yawDeg: 0, wall: [0, 0, 0], tvec: [0, 0, 6]))
        barrier.noteFieldDecision(recorded: true, engine: &engine)
        XCTAssertEqual(first.windowFrameIDs, [14])
        XCTAssertEqual(engine.stats.pnpEvaluations, 1)
        XCTAssertNil(engine.stats.firstLocalizedSequence)
    }

    func testSerialQueueInFlightOldEngineIsNotRecordedWhenSamplingStartsAfterReset() {
        let queue = DispatchQueue(label: "com.rockvision.v2.opencv.test")
        var engine = LocalizationConfirmation()
        var barrier = FieldConfirmationSessionBarrier()
        var sampling = false
        var recorded: [(frameID: UInt64, tick: ConfirmationTick, stats: ConfirmationStats)] = []

        seedPreSessionLifetime(&engine)
        XCTAssertEqual(engine.localizationState, "localized")
        XCTAssertEqual(engine.stats.firstLocalizedSequence, [6, 7, 8])

        queue.async {
            barrier.prepareCandidateIngest(&engine)
            let tick = engine.ingest(self.qualified(frameID: 13, yawDeg: 1.2, wall: [0.12, 0, 0], tvec: [0.12, 0, 6]))
            let stats = engine.stats
            if sampling {
                recorded.append((13, tick, stats))
                barrier.noteFieldDecision(recorded: true, engine: &engine)
            } else {
                barrier.noteFieldDecision(recorded: false, engine: &engine)
            }
        }
        queue.async {
            engine.reset()
            barrier.noteResetCompletedOnProcessingQueue()
            sampling = true
        }
        queue.sync {}

        XCTAssertTrue(recorded.isEmpty, "in-flight frame 13 must not enter the new session")
        XCTAssertTrue(barrier.needsFreshEngine)
        XCTAssertEqual(engine.localizationState, "idle")

        queue.async {
            barrier.prepareCandidateIngest(&engine)
            let tick = engine.ingest(self.qualified(frameID: 14, yawDeg: 0, wall: [0, 0, 0], tvec: [0, 0, 6]))
            let stats = engine.stats
            XCTAssertTrue(sampling)
            recorded.append((14, tick, stats))
            barrier.noteFieldDecision(recorded: true, engine: &engine)
        }
        queue.sync {}

        XCTAssertEqual(recorded.count, 1)
        XCTAssertEqual(recorded[0].frameID, 14)
        XCTAssertEqual(recorded[0].tick.windowFrameIDs, [14])
        XCTAssertEqual(recorded[0].tick.windowCount, 1)
        XCTAssertEqual(recorded[0].stats.pnpEvaluations, 1)
        XCTAssertEqual(recorded[0].stats.qualifiedCount, 1)
        XCTAssertNil(recorded[0].stats.firstLocalizedSequence)
        XCTAssertFalse(recorded[0].tick.windowFrameIDs.contains(11))
        XCTAssertFalse(recorded[0].tick.windowFrameIDs.contains(12))
        XCTAssertFalse(recorded[0].tick.windowFrameIDs.contains(13))
    }

    func testOldOrderingWouldHaveRecordedFrame13WithForeignWindow() {
        var engine = LocalizationConfirmation()
        seedPreSessionLifetime(&engine)
        let sampling = true
        var recorded: ConfirmationTick?

        let tick = engine.ingest(qualified(frameID: 13, yawDeg: 1.2, wall: [0.12, 0, 0], tvec: [0.12, 0, 6]))
        if sampling {
            recorded = tick
        }

        let observed = try! XCTUnwrap(recorded)
        XCTAssertEqual(observed.localizationState, "localized")
        XCTAssertEqual(observed.windowFrameIDs, [11, 12, 13])
        XCTAssertEqual(engine.stats.firstLocalizedSequence, [6, 7, 8])
        XCTAssertEqual(engine.stats.pnpEvaluations, 8)
    }

    func testStartSceneWaitsForResetCompletionBeforeSampling() {
        let store = FieldTestStore(rootURL: FileManager.default.temporaryDirectory.appendingPathComponent("barrier-\(UUID().uuidString)", isDirectory: true))
        let controller = FieldTestController(store: store, openCVVersion: "4.14.0", presets: [.low])
        let started = expectation(description: "reset completion")
        var samplingBeforeCompletion = true
        controller.onResetConfirmation = { completion in
            samplingBeforeCompletion = controller.isSampling
            DispatchQueue.main.async {
                completion()
                started.fulfill()
            }
        }
        controller.startScene(.A)
        XCTAssertFalse(controller.isSampling)
        XCTAssertFalse(samplingBeforeCompletion)
        wait(for: [started], timeout: 1.0)
        XCTAssertTrue(controller.isSampling)
    }

    private func seedPreSessionLifetime(_ engine: inout LocalizationConfirmation) {
        for i in 0..<7 {
            let id = UInt64(6 + i)
            _ = engine.ingest(
                qualified(
                    frameID: id,
                    yawDeg: Double(i) * 0.4,
                    wall: [Double(i) * 0.02, 0, 0],
                    tvec: [Double(i) * 0.02, 0, 6]
                )
            )
        }
        XCTAssertEqual(engine.localizationState, "localized")
        XCTAssertEqual(engine.stats.pnpEvaluations, 7)
        XCTAssertEqual(engine.stats.firstLocalizedSequence, [6, 7, 8])
    }

    private func qualified(frameID: UInt64, yawDeg: Double, wall: [Double], tvec: [Double]) -> PnPFrameResult {
        let r = yawDeg * .pi / 180.0
        let c = cos(r)
        let s = sin(r)
        let R = [[c, 0, s], [0, 1.0, 0], [-s, 0, c]]
        var result = PnPFrameResult.inactive(reason: "candidate")
        result.status = "candidate"
        result.attempted = true
        result.ransacAttempted = true
        result.ransacSuccess = true
        result.refineAttempted = true
        result.refineOk = true
        result.refineQualityOk = true
        result.refineQualityFlag = "ok"
        result.candidateQualified = true
        result.inputCorrespondenceCount = 40
        result.uniquePoint3DCount = 40
        result.inlierCount = 30
        result.inlierRatio = 0.75
        result.frameID = frameID
        result.positiveDepthRatioRefined = 1.0
        result.rotationMatrix = R
        result.tvecRefined = tvec
        result.rvecRefined = [0, r, 0]
        result.T_opencvCam_colmap = [
            [R[0][0], R[0][1], R[0][2], tvec[0]],
            [R[1][0], R[1][1], R[1][2], tvec[1]],
            [R[2][0], R[2][1], R[2][2], tvec[2]],
            [0, 0, 0, 1]
        ]
        result.C_wall = wall
        result.C_colmap = wall
        result.medianInlierDepthCam = 2.0
        result.medianInlierDepthMeters = 2.0 * 3.19764417024824
        return result
    }
}
