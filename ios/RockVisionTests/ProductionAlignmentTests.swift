import XCTest
@testable import RockVision

final class ProductionAlignmentTests: XCTestCase {
    func testNoAlignmentBeforeLocalized() throws {
        var engine = LocalizationConfirmation()
        var alignment = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        let pnp = Gate4AFixture.qualified(frameID: 11)
        let tick = engine.ingest(pnp)
        let result = alignment.update(
            confirmation: tick,
            pnp: pnp,
            arkit: Gate4AFixture.sidecar(frameID: 11),
            sim3: sim3
        )
        XCTAssertEqual(tick.localizationState, "confirming")
        XCTAssertFalse(result.hasT_ARWorld_Wall)
        XCTAssertNil(result.T_ARWorld_Wall)
        XCTAssertFalse(result.productionAlignmentCalled)
        XCTAssertEqual(result.reason, "notLocalized")
    }

    func testThreeFrameConfirmationGeneratesTFromProductionAlignment() throws {
        var engine = LocalizationConfirmation()
        var alignment = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        let localized = localizeThree(&engine, &alignment, sim3: sim3)
        XCTAssertEqual(localized.tick.localizationState, "localized")
        XCTAssertTrue(localized.alignment.hasT_ARWorld_Wall)
        XCTAssertTrue(localized.alignment.productionAlignmentCalled)
        XCTAssertEqual(localized.alignment.renderedRoute, false)
        let transform = try XCTUnwrap(localized.alignment.T_ARWorld_Wall)
        let provenance = try XCTUnwrap(localized.alignment.provenance)
        XCTAssertEqual(provenance.confirmedFrameID, 13)
        XCTAssertEqual(provenance.arFrameID, 13)
        XCTAssertEqual(provenance.confirmedTimestamp, 13)
        XCTAssertEqual(provenance.arFrameTimestamp, 13)
        XCTAssertEqual(provenance.T_opencvCam_colmap, localized.pnp.T_opencvCam_colmap)
        XCTAssertEqual(localized.tick.confirmedT_opencvCam_colmap, localized.pnp.T_opencvCam_colmap)
        XCTAssertEqual(localized.tick.confirmedEqualsLatestRefined, true)

        let expected = try CoordinateTransforms.productionAlignment(
            T_opencvCam_colmap: try XCTUnwrap(localized.pnp.T_opencvCam_colmap),
            S_wall_colmap: sim3,
            T_ARWorld_arkitCam: provenance.T_ARWorld_arkitCam
        )
        XCTAssertEqual(transform, expected)
        XCTAssertEqual(axisLength(transform, [1, 0, 0]), 1.0, accuracy: 1e-9)
        XCTAssertEqual(axisLength(transform, [0, 1, 0]), 1.0, accuracy: 1e-9)
        XCTAssertEqual(axisLength(transform, [0, 0, 1]), 1.0, accuracy: 1e-9)
        XCTAssertEqual(rotationDeterminant(transform), 1.0, accuracy: 1e-9)
        XCTAssertFalse(localized.tick.hasT_ARWorld_Wall)
        XCTAssertFalse(localized.sidecar.usedInPnP)
        XCTAssertFalse(localized.sidecar.usedInConfirmation)
        XCTAssertFalse(localized.sidecar.producesT_ARWorld_Wall)
        XCTAssertFalse(localized.tick.usedARKitInConfirmation)
        XCTAssertFalse(localized.tick.usedGPSInConfirmation)
        XCTAssertFalse(localized.tick.usedPreviousPosePnPPrior)
    }

    func testInputIsConfirmedLastFrameNotWindowAverage() throws {
        var engine = LocalizationConfirmation()
        let f1 = Gate4AFixture.qualified(frameID: 1, yawDeg: 0, tvec: [1, 0, 6])
        let f2 = Gate4AFixture.qualified(frameID: 2, yawDeg: 2, tvec: [2, 0, 6])
        let f3 = Gate4AFixture.qualified(frameID: 3, yawDeg: 4, tvec: [3, 0, 6])
        _ = engine.ingest(f1)
        _ = engine.ingest(f2)
        let tick = engine.ingest(f3)
        XCTAssertEqual(tick.confirmedT_opencvCam_colmap, f3.T_opencvCam_colmap)
        XCTAssertNotEqual(tick.confirmedT_opencvCam_colmap, averageT([f1, f2, f3]))

        var alignment = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        let result = alignment.update(
            confirmation: tick,
            pnp: f3,
            arkit: Gate4AFixture.sidecar(frameID: 3),
            sim3: sim3
        )
        let used = try XCTUnwrap(result.provenance?.T_opencvCam_colmap)
        XCTAssertEqual(used, f3.T_opencvCam_colmap)
        XCTAssertEqual(used[0][3], 3.0, accuracy: 1e-12)
        XCTAssertNotEqual(used[0][3], 2.0, accuracy: 1e-9)
    }

    func testMissingSameARFrameIdentityRefuses() throws {
        var engine = LocalizationConfirmation()
        var alignment = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        let localized = localizeThree(&engine, &alignment, sim3: sim3)
        XCTAssertTrue(localized.alignment.hasT_ARWorld_Wall)

        var missing = Gate4AFixture.sidecar(frameID: 13)
        missing.frameID = nil
        missing.timestamp = nil
        let refused = alignment.update(
            confirmation: localized.tick,
            pnp: localized.pnp,
            arkit: missing,
            sim3: sim3
        )
        XCTAssertFalse(refused.hasT_ARWorld_Wall)
        XCTAssertNil(refused.T_ARWorld_Wall)
        XCTAssertTrue(refused.cleared)
        XCTAssertEqual(refused.reason, "missingARKitIdentity")

        var freshEngine = LocalizationConfirmation()
        var freshAlign = ProductionAlignmentRuntime()
        let f1 = Gate4AFixture.qualified(frameID: 11)
        let f2 = Gate4AFixture.qualified(frameID: 12)
        let f3 = Gate4AFixture.qualified(frameID: 13)
        _ = freshEngine.ingest(f1)
        _ = freshEngine.ingest(f2)
        let tick = freshEngine.ingest(f3)
        let none = freshAlign.update(confirmation: tick, pnp: f3, arkit: nil, sim3: sim3)
        XCTAssertFalse(none.hasT_ARWorld_Wall)
        XCTAssertFalse(none.cleared)
        XCTAssertEqual(none.reason, "missingARKitIdentity")
    }

    func testProvenanceMismatchClearsCurrentAlignment() throws {
        var engine = LocalizationConfirmation()
        var alignment = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        let localized = localizeThree(&engine, &alignment, sim3: sim3)
        XCTAssertTrue(localized.alignment.hasT_ARWorld_Wall)

        let mismatch = alignment.update(
            confirmation: localized.tick,
            pnp: localized.pnp,
            arkit: Gate4AFixture.sidecar(frameID: 99, timestamp: 99),
            sim3: sim3
        )
        XCTAssertFalse(mismatch.hasT_ARWorld_Wall)
        XCTAssertNil(mismatch.T_ARWorld_Wall)
        XCTAssertTrue(mismatch.cleared)
        XCTAssertEqual(mismatch.reason, "provenanceMismatch")
        XCTAssertNil(alignment.current.T_ARWorld_Wall)
    }

    func testMissingSim3RefusesWithoutIdentityFallback() throws {
        var engine = LocalizationConfirmation()
        var alignment = ProductionAlignmentRuntime()
        let f1 = Gate4AFixture.qualified(frameID: 11)
        let f2 = Gate4AFixture.qualified(frameID: 12)
        let f3 = Gate4AFixture.qualified(frameID: 13)
        _ = engine.ingest(f1)
        _ = engine.ingest(f2)
        let tick = engine.ingest(f3)
        let result = alignment.update(
            confirmation: tick,
            pnp: f3,
            arkit: Gate4AFixture.sidecar(frameID: 13),
            sim3: nil
        )
        XCTAssertFalse(result.hasT_ARWorld_Wall)
        XCTAssertNil(result.T_ARWorld_Wall)
        XCTAssertEqual(result.reason, "sim3Unavailable")
    }

    func testLockLossClearsTImmediately() throws {
        var engine = LocalizationConfirmation()
        var alignment = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        _ = localizeThree(&engine, &alignment, sim3: sim3)
        XCTAssertTrue(alignment.current.hasT_ARWorld_Wall)

        var bad = Gate4AFixture.qualified(frameID: 14)
        bad.candidateQualified = false
        let lost = engine.ingest(bad)
        XCTAssertEqual(lost.localizationState, "idle")
        XCTAssertTrue(lost.lostLocalized)
        let cleared = alignment.update(
            confirmation: lost,
            pnp: bad,
            arkit: Gate4AFixture.sidecar(frameID: 14),
            sim3: sim3
        )
        XCTAssertFalse(cleared.hasT_ARWorld_Wall)
        XCTAssertTrue(cleared.cleared)
        XCTAssertNil(alignment.current.T_ARWorld_Wall)
        XCTAssertEqual(alignment.current.reason, "unqualified")
    }

    func testConsistencyFailClearsTImmediately() throws {
        var engine = LocalizationConfirmation()
        var alignment = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        _ = localizeThree(&engine, &alignment, sim3: sim3)
        let tick = engine.ingest(
            Gate4AFixture.qualified(frameID: 14, yawDeg: 2.5, wall: [1.80, 2.02, 3.01], tvec: [1.10, 0.22, 6.08])
        )
        XCTAssertEqual(tick.localizationState, "confirming")
        XCTAssertTrue(tick.lostLocalized)
        let cleared = alignment.update(
            confirmation: tick,
            pnp: Gate4AFixture.qualified(frameID: 14, yawDeg: 2.5, wall: [1.80, 2.02, 3.01], tvec: [1.10, 0.22, 6.08]),
            arkit: Gate4AFixture.sidecar(frameID: 14),
            sim3: sim3
        )
        XCTAssertFalse(cleared.hasT_ARWorld_Wall)
        XCTAssertTrue(cleared.cleared)
        XCTAssertNil(alignment.current.provenance)
    }

    func testRollingLocalizedReplacesOldAlignment() throws {
        var engine = LocalizationConfirmation()
        var alignment = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        let first = localizeThree(&engine, &alignment, sim3: sim3)
        XCTAssertEqual(first.alignment.provenance?.confirmedFrameID, 13)

        let fourth = Gate4AFixture.qualified(frameID: 14, yawDeg: 3.0, wall: [1.14, 2.02, 3.01], tvec: [0.44, 0.22, 6.08])
        let tick = engine.ingest(fourth)
        XCTAssertEqual(tick.localizationState, "localized")
        XCTAssertEqual(tick.confirmedFrameID, 14)
        let next = alignment.update(
            confirmation: tick,
            pnp: fourth,
            arkit: Gate4AFixture.sidecar(frameID: 14),
            sim3: sim3
        )
        XCTAssertTrue(next.hasT_ARWorld_Wall)
        XCTAssertEqual(next.provenance?.confirmedFrameID, 14)
        XCTAssertEqual(next.provenance?.arFrameID, 14)
        XCTAssertEqual(next.provenance?.T_opencvCam_colmap, fourth.T_opencvCam_colmap)
        XCTAssertNotEqual(next.provenance?.confirmedFrameID, 13)
        XCTAssertNotEqual(next.T_ARWorld_Wall, first.alignment.T_ARWorld_Wall)
        XCTAssertEqual(alignment.stats.firstGeneratedFrameID, 13)
        XCTAssertEqual(alignment.stats.generatedCount, 2)
    }

    func testARKitAndGPSStayOutOfPnPAndConfirmation() throws {
        let pnpSource = try readHostSource("RockVision/Features/PnP/PnPRuntime.swift")
        XCTAssertFalse(pnpSource.contains("camera.transform"))
        XCTAssertFalse(pnpSource.contains("CLLocation"))
        XCTAssertFalse(pnpSource.contains("productionAlignment"))
        XCTAssertFalse(pnpSource.contains("T_ARWorld_Wall"))

        let confSource = try readHostSource("RockVision/Features/PnP/LocalizationConfirmation.swift")
        XCTAssertFalse(confSource.contains("productionAlignment"))
        XCTAssertFalse(confSource.contains("CLLocation"))

        let processor = try readHostSource("RockVision/Features/OpenCV/OpenCVFrameProcessor.swift")
        XCTAssertTrue(processor.contains("alignmentRuntime.update"))
        XCTAssertTrue(processor.contains("stamped(frameID:"))
        XCTAssertFalse(processor.contains("CLLocation"))
        XCTAssertFalse(processor.contains("RouteOverlay"))
        XCTAssertFalse(processor.contains("climbing route"))
        XCTAssertFalse(processor.contains("T_ARWorld_Wall ="))

        let alignmentSource = try readHostSource("RockVision/Features/PnP/ProductionAlignment.swift")
        XCTAssertTrue(alignmentSource.contains("CoordinateTransforms.productionAlignment"))
        XCTAssertFalse(alignmentSource.contains("CLLocation"))
        XCTAssertTrue(alignmentSource.contains("renderedRoute: false"))
        XCTAssertFalse(alignmentSource.contains("opencvCamMetersWallTransform"))
        XCTAssertFalse(alignmentSource.contains("Kalman"))
    }

    func testDoesNotRenderClimbingRoute() {
        var alignment = ProductionAlignmentRuntime()
        XCTAssertFalse(alignment.stats.renderedRoute)
        XCTAssertFalse(alignment.current.renderedRoute)
        XCTAssertFalse(alignment.current.hasT_ARWorld_Wall)
    }

    private func localizeThree(
        _ engine: inout LocalizationConfirmation,
        _ alignment: inout ProductionAlignmentRuntime,
        sim3: ValidatedSim3
    ) -> (tick: ConfirmationTick, pnp: PnPFrameResult, alignment: AlignmentFrameResult, sidecar: ARKitCameraTransformSidecar) {
        _ = alignment.update(
            confirmation: engine.ingest(Gate4AFixture.qualified(frameID: 11)),
            pnp: Gate4AFixture.qualified(frameID: 11),
            arkit: Gate4AFixture.sidecar(frameID: 11),
            sim3: sim3
        )
        _ = alignment.update(
            confirmation: engine.ingest(Gate4AFixture.qualified(frameID: 12)),
            pnp: Gate4AFixture.qualified(frameID: 12),
            arkit: Gate4AFixture.sidecar(frameID: 12),
            sim3: sim3
        )
        let pnp = Gate4AFixture.qualified(frameID: 13)
        let tick = engine.ingest(pnp)
        let sidecar = Gate4AFixture.sidecar(frameID: 13)
        let result = alignment.update(confirmation: tick, pnp: pnp, arkit: sidecar, sim3: sim3)
        return (tick, pnp, result, sidecar)
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

    private func loadSim3() -> ValidatedSim3? {
        let bundle = Bundle(for: OpenCVFrameProcessor.self)
        if let sim3 = ValidatedSim3Loader.loadFromBundle(bundle) {
            return sim3
        }
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("RockVision/Resources/S_wall_colmap.json")
        return try? ValidatedSim3Loader.load(from: url)
    }

    private func readHostSource(_ relative: String) throws -> String {
        let path = sourcePath(relative)
        guard FileManager.default.isReadableFile(atPath: path) else {
            throw XCTSkip("host source tree not readable")
        }
        return try String(contentsOfFile: path, encoding: .utf8)
    }

    private func sourcePath(_ relative: String) -> String {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(relative)
            .path
    }

    private func axisLength(_ t: [[Double]], _ axis: [Double]) -> Double {
        let origin = Homogeneous.apply(t, point: [0, 0, 0])
        let end = Homogeneous.apply(t, point: axis)
        let dx = end[0] - origin[0], dy = end[1] - origin[1], dz = end[2] - origin[2]
        return sqrt(dx * dx + dy * dy + dz * dz)
    }

    private func rotationDeterminant(_ t: [[Double]]) -> Double {
        let a = t[0][0], b = t[0][1], c = t[0][2]
        let d = t[1][0], e = t[1][1], f = t[1][2]
        let g = t[2][0], h = t[2][1], i = t[2][2]
        return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    }
}

private enum Gate4AFixture {
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
        yawDeg: Double = 0,
        wall: [Double] = [1.00, 2.00, 3.00],
        tvec: [Double] = [0.10, 0.20, 6.00]
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
        result.C_colmap = [wall[0] / 3.19764417024824, wall[1] / 3.19764417024824, wall[2] / 3.19764417024824]
        result.medianInlierDepthCam = 2.0
        result.medianInlierDepthMeters = 2.0 * 3.19764417024824
        return result
    }

    static func sidecar(frameID: UInt64, timestamp: TimeInterval? = nil) -> ARKitCameraTransformSidecar {
        ARKitCameraTransformSidecar.capture(
            columnMajor4x4: [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0.5, 1.5, 2.5, 1]
            ],
            timestamp: timestamp ?? TimeInterval(frameID)
        ).stamped(frameID: frameID, timestamp: timestamp ?? TimeInterval(frameID))
    }
}
