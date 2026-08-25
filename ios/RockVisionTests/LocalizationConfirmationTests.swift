import XCTest
@testable import RockVision

final class LocalizationConfirmationTests: XCTestCase {
    func testDefaultStateIsIdle() {
        let engine = LocalizationConfirmation()
        XCTAssertEqual(engine.localizationState, ConfirmationConfig.localizationIdle)
        XCTAssertEqual(ConfirmationConfig.confirmWindow, 3)
        XCTAssertEqual(ConfirmationConfig.adjacentRotationMaxDeg, 8.0)
        XCTAssertEqual(ConfirmationConfig.adjacentCWallMaxMeters, 0.50)
        XCTAssertEqual(ConfirmationConfig.adjacentRotationFlipGuardDeg, 90.0)
        XCTAssertEqual(ConfirmationConfig.poseName, "T_opencvCam_colmap")
    }

    func testThreeStableQualifiedFramesLocalizeToLastRefinedPose() {
        var engine = LocalizationConfirmation()
        let t1 = ingest(&engine, frameID: 11, yawDeg: 0, wall: [1.00, 2.00, 3.00], tvec: [0.10, 0.20, 6.00])
        XCTAssertEqual(t1.localizationState, "confirming")
        XCTAssertEqual(t1.windowCount, 1)
        XCTAssertNil(t1.confirmedT_opencvCam_colmap)
        XCTAssertFalse(t1.hasT_ARWorld_Wall)

        let t2 = ingest(&engine, frameID: 12, yawDeg: 1.5, wall: [1.05, 2.00, 3.00], tvec: [0.20, 0.20, 6.00])
        XCTAssertEqual(t2.localizationState, "confirming")
        XCTAssertEqual(t2.windowCount, 2)
        XCTAssertNil(t2.confirmedT_opencvCam_colmap)

        let last = ConfirmationFixture.qualified(frameID: 13, yawDeg: 2.5, wall: [1.10, 2.02, 3.00], tvec: [0.31, 0.22, 6.05])
        let t3 = engine.ingest(last)
        XCTAssertEqual(t3.localizationState, "localized")
        XCTAssertEqual(t3.windowCount, 3)
        XCTAssertTrue(t3.enteredLocalized)
        XCTAssertEqual(t3.confirmedFrameID, 13)
        XCTAssertEqual(t3.confirmedTimestamp, 13)
        XCTAssertEqual(t3.currentFrameID, 13)
        XCTAssertEqual(t3.currentTimestamp, 13)
        XCTAssertEqual(t3.confirmedT_opencvCam_colmap, last.T_opencvCam_colmap)
        XCTAssertEqual(t3.confirmedEqualsLatestRefined, true)
        XCTAssertEqual(t3.windowFrameIDs, [11, 12, 13])
        XCTAssertFalse(t3.hasT_ARWorld_Wall)
    }

    func testUnqualifiedMidWindowResetsToIdleAndCannotStartWindow() {
        var engine = LocalizationConfirmation()
        _ = ingest(&engine, frameID: 1, yawDeg: 0, wall: [0, 0, 0], tvec: [0, 0, 6])
        _ = ingest(&engine, frameID: 2, yawDeg: 1, wall: [0.05, 0, 0], tvec: [0.05, 0, 6])
        XCTAssertEqual(engine.localizationState, "confirming")

        var bad = ConfirmationFixture.qualified(frameID: 3, yawDeg: 1.2, wall: [0.08, 0, 0], tvec: [0.08, 0, 6])
        bad.candidateQualified = false
        let tick = engine.ingest(bad)
        XCTAssertEqual(tick.localizationState, "idle")
        XCTAssertEqual(tick.windowCount, 0)
        XCTAssertEqual(tick.resetReason, "unqualified")
        XCTAssertNil(tick.confirmedT_opencvCam_colmap)
        XCTAssertFalse(tick.restartedFromBreakingFrame)
        XCTAssertEqual(engine.localizationState, "idle")
    }

    func testQualifiedInconsistentCWallRestartsAsWindowStart() {
        var engine = LocalizationConfirmation()
        _ = ingest(&engine, frameID: 1, yawDeg: 0, wall: [0, 0, 0], tvec: [0, 0, 6])
        _ = ingest(&engine, frameID: 2, yawDeg: 1, wall: [0.10, 0, 0], tvec: [0.10, 0, 6])
        let tick = ingest(&engine, frameID: 3, yawDeg: 1.2, wall: [0.70, 0, 0], tvec: [0.70, 0, 6])
        XCTAssertEqual(tick.localizationState, "confirming")
        XCTAssertEqual(tick.windowCount, 1)
        XCTAssertEqual(tick.windowFrameIDs, [3])
        XCTAssertEqual(tick.resetReason, "adjacent C_wall")
        XCTAssertTrue(tick.restartedFromBreakingFrame)
        XCTAssertNil(tick.confirmedT_opencvCam_colmap)
        XCTAssertGreaterThanOrEqual(try XCTUnwrap(tick.adjacentCWallMeters), ConfirmationConfig.adjacentCWallMaxMeters)
    }

    func testAdjacentRotationFailureDoesNotKeepOldWindow() {
        var engine = LocalizationConfirmation()
        _ = ingest(&engine, frameID: 1, yawDeg: 0, wall: [0, 0, 0], tvec: [0, 0, 6])
        let tick = ingest(&engine, frameID: 2, yawDeg: 8.1, wall: [0.05, 0, 0], tvec: [0.05, 0, 6])
        XCTAssertEqual(tick.localizationState, "confirming")
        XCTAssertEqual(tick.windowCount, 1)
        XCTAssertEqual(tick.windowFrameIDs, [2])
        XCTAssertEqual(tick.resetReason, "adjacent rotation")
        XCTAssertGreaterThanOrEqual(try XCTUnwrap(tick.adjacentRotationDeg), ConfirmationConfig.adjacentRotationMaxDeg)
        XCTAssertLessThan(try XCTUnwrap(tick.adjacentRotationDeg), ConfirmationConfig.adjacentRotationFlipGuardDeg)
    }

    func testAntiFlipRejects180DegreeFlip() {
        var engine = LocalizationConfirmation()
        _ = ingest(&engine, frameID: 1, yawDeg: 0, wall: [0, 0, 0], tvec: [0, 0, 6])
        let tick = ingest(&engine, frameID: 2, yawDeg: 180, wall: [0.05, 0, 0], tvec: [0.05, 0, 6])
        XCTAssertNotEqual(tick.localizationState, "localized")
        XCTAssertEqual(tick.windowCount, 1)
        XCTAssertEqual(tick.resetReason, "anti-flip")
        XCTAssertGreaterThan(try XCTUnwrap(tick.adjacentRotationDeg), 90)
    }

    func testLocalizedRollingUpdatesConfirmedPoseToLatest() {
        var engine = LocalizationConfirmation()
        localizeThree(&engine)
        let fourth = ConfirmationFixture.qualified(frameID: 24, yawDeg: 3.0, wall: [1.14, 2.02, 3.01], tvec: [0.44, 0.22, 6.08])
        let tick = engine.ingest(fourth)
        XCTAssertEqual(tick.localizationState, "localized")
        XCTAssertEqual(tick.windowCount, 3)
        XCTAssertEqual(tick.windowFrameIDs, [22, 23, 24])
        XCTAssertEqual(tick.confirmedFrameID, 24)
        XCTAssertEqual(tick.confirmedT_opencvCam_colmap, fourth.T_opencvCam_colmap)
        XCTAssertFalse(tick.enteredLocalized)
        XCTAssertEqual(engine.stats.acceptedAfterFirstLocalized, 1)
    }

    func testLocalizedUnqualifiedImmediatelyIdleAndClearsPose() {
        var engine = LocalizationConfirmation()
        localizeThree(&engine)
        var bad = ConfirmationFixture.qualified(frameID: 24, yawDeg: 3.0, wall: [1.14, 2.02, 3.01], tvec: [0.44, 0.22, 6.08])
        bad.candidateQualified = false
        let tick = engine.ingest(bad)
        XCTAssertEqual(tick.localizationState, "idle")
        XCTAssertEqual(tick.windowCount, 0)
        XCTAssertTrue(tick.lostLocalized)
        XCTAssertNil(tick.confirmedT_opencvCam_colmap)
        XCTAssertEqual(tick.resetReason, "unqualified")
        XCTAssertEqual(engine.stats.localizedLossCount, 1)
    }

    func testLocalizedConsistencyFailRestartsFromBreakingFrame() {
        var engine = LocalizationConfirmation()
        localizeThree(&engine)
        let tick = ingest(&engine, frameID: 24, yawDeg: 3.0, wall: [1.80, 2.02, 3.01], tvec: [1.10, 0.22, 6.08])
        XCTAssertEqual(tick.localizationState, "confirming")
        XCTAssertEqual(tick.windowCount, 1)
        XCTAssertEqual(tick.windowFrameIDs, [24])
        XCTAssertTrue(tick.lostLocalized)
        XCTAssertTrue(tick.restartedFromBreakingFrame)
        XCTAssertNil(tick.confirmedT_opencvCam_colmap)
        XCTAssertEqual(tick.resetReason, "adjacent C_wall")
    }

    func testConfirmedPoseIsNotWindowAverage() throws {
        var engine = LocalizationConfirmation()
        let f1 = ConfirmationFixture.qualified(frameID: 1, yawDeg: 0, wall: [0.0, 0.0, 0.0], tvec: [1.0, 0.0, 6.0], cColmap: [10, 0, 0])
        let f2 = ConfirmationFixture.qualified(frameID: 2, yawDeg: 2, wall: [0.2, 0.0, 0.0], tvec: [2.0, 0.0, 6.0], cColmap: [20, 0, 0])
        let f3 = ConfirmationFixture.qualified(frameID: 3, yawDeg: 4, wall: [0.4, 0.0, 0.0], tvec: [3.0, 0.0, 6.0], cColmap: [30, 0, 0])
        _ = engine.ingest(f1)
        _ = engine.ingest(f2)
        let tick = engine.ingest(f3)
        XCTAssertEqual(tick.localizationState, "localized")
        let confirmed = try XCTUnwrap(tick.confirmedT_opencvCam_colmap)
        XCTAssertEqual(confirmed, f3.T_opencvCam_colmap)
        XCTAssertNotEqual(confirmed, averageT([f1, f2, f3]))
        XCTAssertNotEqual(confirmed[0][3], (1.0 + 2.0 + 3.0) / 3.0, accuracy: 1e-9)
        XCTAssertEqual(confirmed[0][3], 3.0, accuracy: 1e-12)
        let meanCWall = [0.2, 0.0, 0.0]
        XCTAssertNotEqual(f3.C_wall, meanCWall)
        let meanCColmap = [20.0, 0.0, 0.0]
        XCTAssertNotEqual(f3.C_colmap, meanCColmap)
        let chordalMeanR = ConfirmationFixture.yaw((0.0 + 2.0 + 4.0) / 3.0)
        XCTAssertNotEqual(f3.rotationMatrix, chordalMeanR)
    }

    func testArchitectureGuardsIsolation() throws {
        var engine = LocalizationConfirmation()
        localizeThree(&engine)
        XCTAssertEqual(engine.localizationState, "localized")
        XCTAssertFalse(engine.stats.confirmedAlwaysEqualsLatestRefined == false)

        let confirmationSource = try readHostSource("RockVision/Features/PnP/LocalizationConfirmation.swift")
        XCTAssertFalse(confirmationSource.contains("productionAlignment"))
        XCTAssertFalse(confirmationSource.contains("T_ARWorld_Wall ="))
        XCTAssertFalse(confirmationSource.contains("CLLocation"))

        let source = try readHostSource("RockVision/Features/OpenCV/OpenCVFrameProcessor.swift")
        XCTAssertTrue(source.contains("confirmationEngine.ingest(pnp)"))
        XCTAssertTrue(source.contains("alignmentRuntime.update"))
        XCTAssertFalse(source.contains("ingest(pnp, arkit"))
        XCTAssertFalse(source.contains("previousPose"))
        XCTAssertFalse(source.contains("Kalman"))
        XCTAssertFalse(source.contains("T_ARWorld_Wall ="))
        XCTAssertTrue(source.contains("requestedInterval: TimeInterval = 0.50"))
        XCTAssertTrue(source.contains("if isProcessing || now.timeIntervalSince(lastAcceptedAt) < requestedInterval"))
        XCTAssertFalse(source.contains("DispatchQueue(label: \"com.rockvision.v2.confirmation\""))
        XCTAssertFalse(source.contains("DispatchQueue(label: \"com.rockvision.v2.pnp\""))
        XCTAssertFalse(source.contains("DispatchQueue(label: \"com.rockvision.v2.alignment\""))
        XCTAssertFalse(source.contains("CLLocation"))
        XCTAssertFalse(source.contains("RouteOverlay"))
        XCTAssertFalse(source.contains("climbing route"))

        XCTAssertFalse(PnPConfig.useExtrinsicGuess)
        XCTAssertEqual(MatchingConfig.diagnosticMatchCap, 20)

        let sidecar = ARKitCameraTransformSidecar.capture(columnMajor4x4: [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ])
        XCTAssertTrue(sidecar.sameARFrame)
        XCTAssertFalse(sidecar.usedInPnP)
        XCTAssertFalse(sidecar.usedInConfirmation)
        XCTAssertFalse(sidecar.producesT_ARWorld_Wall)

        let tick = ingest(&engine, frameID: 24, yawDeg: 3.2, wall: [1.16, 2.02, 3.01], tvec: [0.46, 0.22, 6.08])
        XCTAssertFalse(tick.hasT_ARWorld_Wall)
        XCTAssertFalse(tick.usedARKitInConfirmation)
        XCTAssertFalse(tick.usedGPSInConfirmation)
        XCTAssertFalse(tick.usedPreviousPosePnPPrior)
    }

    func testPnPStillUsesFullCorrespondencesNotDiagnosticCap() throws {
        XCTAssertEqual(MatchingConfig.diagnosticMatchCap, 20)
        XCTAssertGreaterThan(PnPConfig.minCorrespondences, 0)
        let pnpSource = try readHostSource("RockVision/Features/PnP/PnPRuntime.swift")
        XCTAssertTrue(pnpSource.contains("correspondences: matching.pnpCorrespondences"))
        XCTAssertFalse(pnpSource.contains("diagnosticMatches"))
        XCTAssertFalse(pnpSource.contains("previousPose"))
        XCTAssertFalse(pnpSource.contains("camera.transform"))
        XCTAssertFalse(pnpSource.contains("CLLocation"))
        XCTAssertFalse(pnpSource.contains("productionAlignment"))
    }

    func testPositiveDepthFailureResetsIdleNotRestart() {
        var engine = LocalizationConfirmation()
        _ = ingest(&engine, frameID: 1, yawDeg: 0, wall: [0, 0, 0], tvec: [0, 0, 6])
        var bad = ConfirmationFixture.qualified(frameID: 2, yawDeg: 1, wall: [0.05, 0, 0], tvec: [0.05, 0, 6])
        bad.positiveDepthRatioRefined = 0.9
        let tick = engine.ingest(bad)
        XCTAssertEqual(tick.localizationState, "idle")
        XCTAssertEqual(tick.windowCount, 0)
        XCTAssertEqual(tick.resetReason, "positive depth")
        XCTAssertFalse(tick.restartedFromBreakingFrame)
    }

    private func localizeThree(_ engine: inout LocalizationConfirmation) {
        _ = ingest(&engine, frameID: 21, yawDeg: 0, wall: [1.00, 2.00, 3.00], tvec: [0.10, 0.20, 6.00])
        _ = ingest(&engine, frameID: 22, yawDeg: 1.5, wall: [1.05, 2.00, 3.00], tvec: [0.20, 0.20, 6.00])
        let last = engine.ingest(
            ConfirmationFixture.qualified(frameID: 23, yawDeg: 2.5, wall: [1.10, 2.02, 3.00], tvec: [0.31, 0.22, 6.05])
        )
        XCTAssertEqual(last.localizationState, "localized")
    }

    @discardableResult
    private func ingest(
        _ engine: inout LocalizationConfirmation,
        frameID: UInt64,
        yawDeg: Double,
        wall: [Double],
        tvec: [Double]
    ) -> ConfirmationTick {
        engine.ingest(ConfirmationFixture.qualified(frameID: frameID, yawDeg: yawDeg, wall: wall, tvec: tvec))
    }

    private func averageT(_ frames: [PnPFrameResult]) -> [[Double]] {
        let ts = frames.compactMap(\.T_opencvCam_colmap)
        var out = Array(repeating: Array(repeating: 0.0, count: 4), count: 4)
        for t in ts {
            for r in 0..<4 {
                for c in 0..<4 {
                    out[r][c] += t[r][c] / Double(ts.count)
                }
            }
        }
        return out
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

private enum ConfirmationFixture {
    static func yaw(_ degrees: Double) -> [[Double]] {
        let r = degrees * .pi / 180.0
        let c = cos(r)
        let s = sin(r)
        return [
            [c, 0, s],
            [0, 1, 0],
            [-s, 0, c]
        ]
    }

    static func transform(R: [[Double]], t: [Double]) -> [[Double]] {
        [
            [R[0][0], R[0][1], R[0][2], t[0]],
            [R[1][0], R[1][1], R[1][2], t[1]],
            [R[2][0], R[2][1], R[2][2], t[2]],
            [0, 0, 0, 1]
        ]
    }

    static func qualified(
        frameID: UInt64,
        yawDeg: Double,
        wall: [Double],
        tvec: [Double],
        cColmap: [Double]? = nil
    ) -> PnPFrameResult {
        let R = yaw(yawDeg)
        var result = PnPFrameResult.inactive(reason: "candidate")
        result.status = "candidate"
        result.localizationState = PnPConfig.localizationState
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
        result.inlierRatio = 30.0 / 40.0
        result.frameID = frameID
        result.timestamp = TimeInterval(frameID)
        result.positiveDepthRatioRefined = 1.0
        result.rotationMatrix = R
        result.tvecRefined = tvec
        result.rvecRefined = [0, yawDeg * .pi / 180.0, 0]
        result.T_opencvCam_colmap = transform(R: R, t: tvec)
        result.C_wall = wall
        result.C_colmap = cColmap ?? [wall[0] / 3.19764417024824, wall[1] / 3.19764417024824, wall[2] / 3.19764417024824]
        result.medianInlierDepthCam = 2.0
        result.medianInlierDepthMeters = 2.0 * 3.19764417024824
        return result
    }
}
