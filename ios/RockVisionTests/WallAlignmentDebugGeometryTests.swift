import XCTest
@testable import RockVision

final class WallAlignmentDebugGeometryTests: XCTestCase {
    func testOriginAndOneMeterAxesThroughRigidT() throws {
        let t = rigidT(yawDeg: 25, translation: [3.0, -1.5, 8.0])
        let alignment = makeAligned(t, frameID: 14)
        let geom = WallAlignmentDebugGeometry.evaluate(alignment: alignment)
        XCTAssertEqual(geom.kind, "WallAlignmentDebugGeometry")
        XCTAssertTrue(geom.visible)
        XCTAssertTrue(geom.consumedProductionT_ARWorld_Wall)
        XCTAssertFalse(geom.renderedRoute)
        XCTAssertEqual(geom.validatedLandmarkCount, 0)
        XCTAssertEqual(geom.markerCount ?? 0, 0)
        XCTAssertEqual(geom.markers ?? [], [])
        XCTAssertEqual(geom.sourceFrameID, 14)
        XCTAssertEqual(geom.sourceTimestamp, 14)
        XCTAssertEqual(geom.T_ARWorld_Wall, t)
        XCTAssertTrue(geom.finite)

        let origin = try XCTUnwrap(geom.originARWorld)
        XCTAssertEqual(origin[0], 3.0, accuracy: 1e-9)
        XCTAssertEqual(origin[1], -1.5, accuracy: 1e-9)
        XCTAssertEqual(origin[2], 8.0, accuracy: 1e-9)

        XCTAssertEqual(try XCTUnwrap(geom.axisLengthX), 1.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.axisLengthY), 1.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.axisLengthZ), 1.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.dotXY), 0.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.dotXZ), 0.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.dotYZ), 0.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.rotationDeterminant), 1.0, accuracy: 1e-9)

        let xEnd = try CoordinateTransforms.apply(t, point: [1, 0, 0])
        XCTAssertEqual(geom.xAxisEndARWorld, xEnd)
    }

    func testNonFiniteTransformIsRejected() {
        var t = rigidT(yawDeg: 0, translation: [0, 0, 0])
        t[0][3] = .nan
        let geom = WallAlignmentDebugGeometry.evaluate(alignment: makeAligned(t, frameID: 1))
        XCTAssertFalse(geom.visible)
        XCTAssertEqual(geom.reason, "nonFinite")
        XCTAssertFalse(geom.finite)
    }

    func testNoTransformProducesNoGeometry() {
        XCTAssertFalse(WallAlignmentDebugGeometry.evaluate(alignment: .none).visible)
        XCTAssertEqual(WallAlignmentDebugGeometry.evaluate(alignment: .none).reason, "noT_ARWorld_Wall")
        var handwritten = AlignmentFrameResult.none
        handwritten.hasT_ARWorld_Wall = true
        handwritten.T_ARWorld_Wall = rigidT(yawDeg: 0, translation: [1, 2, 3])
        handwritten.productionAlignmentCalled = false
        handwritten.provenance = AlignmentProvenance(
            confirmedFrameID: 9,
            confirmedTimestamp: 9,
            T_opencvCam_colmap: rigidT(yawDeg: 0, translation: [0, 0, 0]),
            arFrameID: 9,
            arFrameTimestamp: 9,
            T_ARWorld_arkitCam: rigidT(yawDeg: 0, translation: [0, 0, 0])
        )
        let rejected = WallAlignmentDebugGeometry.evaluate(alignment: handwritten)
        XCTAssertFalse(rejected.visible)
        XCTAssertFalse(rejected.consumedProductionT_ARWorld_Wall)
    }

    func testLockLossAndRelocalizeUseNewAlignment() throws {
        var runtime = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        var engine = LocalizationConfirmation()
        let first = localizeThenAlign(&engine, &runtime, sim3: sim3, startID: 11)
        XCTAssertTrue(first.alignment.hasT_ARWorld_Wall)
        let shown = WallAlignmentDebugGeometry.evaluate(alignment: first.alignment)
        XCTAssertTrue(shown.visible)
        XCTAssertEqual(shown.sourceFrameID, 13)

        var bad = Gate4BFixture.qualified(frameID: 14)
        bad.candidateQualified = false
        let lost = engine.ingest(bad)
        let cleared = runtime.update(
            confirmation: lost,
            pnp: bad,
            arkit: Gate4BFixture.sidecar(frameID: 14),
            sim3: sim3
        )
        XCTAssertTrue(lost.lostLocalized)
        XCTAssertFalse(cleared.hasT_ARWorld_Wall)
        XCTAssertFalse(WallAlignmentDebugGeometry.evaluate(alignment: cleared).visible)

        let again = localizeThenAlign(&engine, &runtime, sim3: sim3, startID: 20)
        let relocated = WallAlignmentDebugGeometry.evaluate(alignment: again.alignment)
        XCTAssertTrue(relocated.visible)
        XCTAssertEqual(relocated.sourceFrameID, 22)
        XCTAssertNotEqual(relocated.T_ARWorld_Wall, shown.T_ARWorld_Wall)
        XCTAssertNotEqual(relocated.originARWorld, shown.originARWorld)
        XCTAssertEqual(try XCTUnwrap(relocated.axisLengthX), 1.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(relocated.axisLengthY), 1.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(relocated.axisLengthZ), 1.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(relocated.rotationDeterminant), 1.0, accuracy: 1e-9)
    }

    func testProductionTKeepsOneMeterAxesAndRejectsOldScale() throws {
        var runtime = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        var engine = LocalizationConfirmation()
        let first = localizeThenAlign(&engine, &runtime, sim3: sim3, startID: 11)
        let geom = WallAlignmentDebugGeometry.evaluate(alignment: first.alignment)
        XCTAssertTrue(geom.visible)
        XCTAssertEqual(try XCTUnwrap(geom.axisLengthX), 1.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.axisLengthY), 1.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.axisLengthZ), 1.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.dotXY), 0.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.dotXZ), 0.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.dotYZ), 0.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.rotationDeterminant), 1.0, accuracy: 1e-9)
        XCTAssertGreaterThan(try XCTUnwrap(geom.rotationDeterminant), 0)
        XCTAssertNotEqual(try XCTUnwrap(geom.axisLengthX), 1.0 / sim3.scale, accuracy: 0.05)
        XCTAssertNotEqual(try XCTUnwrap(geom.rotationDeterminant), pow(1.0 / sim3.scale, 3), accuracy: 0.001)
    }

    func testDoesNotRescaleOrFlipInEvaluator() throws {
        var scaled = rigidT(yawDeg: 0, translation: [0, 0, 0])
        scaled[0][0] = 2
        scaled[1][1] = 2
        scaled[2][2] = 2
        let geom = WallAlignmentDebugGeometry.evaluate(alignment: makeAligned(scaled, frameID: 5))
        XCTAssertTrue(geom.visible)
        XCTAssertEqual(try XCTUnwrap(geom.axisLengthX), 2.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.axisLengthY), 2.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.axisLengthZ), 2.0, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(geom.rotationDeterminant), 8.0, accuracy: 1e-9)
    }

    func testArchitectureIsolation() throws {
        let overlay = try readHostSource("RockVision/Features/DebugOverlay/WallAlignmentDebugOverlay.swift")
        XCTAssertTrue(overlay.contains("originARWorld"))
        XCTAssertFalse(overlay.contains("inverseSim3"))
        XCTAssertFalse(overlay.contains("T_arkitCam_opencvCam"))
        XCTAssertFalse(overlay.contains("productionAlignment"))
        XCTAssertFalse(overlay.contains("y = -y"))
        XCTAssertFalse(overlay.contains("z = -z"))
        XCTAssertFalse(overlay.contains("Kalman"))
        XCTAssertFalse(overlay.contains("ARAnchor"))
        XCTAssertFalse(overlay.contains("session.add"))
        XCTAssertFalse(overlay.contains("climbing"))
        XCTAssertFalse(overlay.contains("CoordinateTransforms.apply"))
        XCTAssertFalse(overlay.contains("look(at"))
        XCTAssertTrue(overlay.contains("root.children.removeAll()"))
        XCTAssertTrue(overlay.contains("geometry.markers"))

        let geom = try readHostSource("RockVision/Features/PnP/WallAlignmentDebugGeometry.swift")
        XCTAssertTrue(geom.contains("CoordinateTransforms.apply"))
        XCTAssertFalse(geom.contains("inverseSim3"))
        XCTAssertFalse(geom.contains("T_arkitCam_opencvCam"))
        XCTAssertFalse(geom.contains("Kalman"))
        XCTAssertFalse(geom.contains("climbing"))

        let processor = try readHostSource("RockVision/Features/OpenCV/OpenCVFrameProcessor.swift")
        XCTAssertTrue(processor.contains("WallAlignmentDebugGeometry.evaluate("))
        XCTAssertTrue(processor.contains("alignment: alignmentResult"))
        XCTAssertTrue(processor.contains("measurementFixture: self.measurementFixture"))
        XCTAssertTrue(processor.contains("currentWallID: self.referenceDatabase?.wallId"))
        XCTAssertTrue(processor.contains("alignmentRuntime.update"))
        XCTAssertFalse(processor.contains("DispatchQueue(label: \"com.rockvision.v2.alignment\""))
        XCTAssertFalse(processor.contains("climbing route"))
        XCTAssertFalse(processor.contains("Kalman"))
    }

    private func makeAligned(_ t: [[Double]], frameID: UInt64) -> AlignmentFrameResult {
        AlignmentFrameResult.aligned(
            transform: t,
            provenance: AlignmentProvenance(
                confirmedFrameID: frameID,
                confirmedTimestamp: TimeInterval(frameID),
                T_opencvCam_colmap: t,
                arFrameID: frameID,
                arFrameTimestamp: TimeInterval(frameID),
                T_ARWorld_arkitCam: rigidT(yawDeg: 0, translation: [0, 0, 0])
            ),
            confirmedEqualsLatestRefined: true
        )
    }

    private func rigidT(yawDeg: Double, translation: [Double]) -> [[Double]] {
        let r = yawDeg * .pi / 180.0
        let c = cos(r)
        let s = sin(r)
        return [
            [c, 0, s, translation[0]],
            [0, 1, 0, translation[1]],
            [-s, 0, c, translation[2]],
            [0, 0, 0, 1]
        ]
    }

    private func localizeThenAlign(
        _ engine: inout LocalizationConfirmation,
        _ alignment: inout ProductionAlignmentRuntime,
        sim3: ValidatedSim3,
        startID: UInt64
    ) -> (alignment: AlignmentFrameResult, pnp: PnPFrameResult) {
        _ = alignment.update(
            confirmation: engine.ingest(Gate4BFixture.qualified(frameID: startID)),
            pnp: Gate4BFixture.qualified(frameID: startID),
            arkit: Gate4BFixture.sidecar(frameID: startID),
            sim3: sim3
        )
        _ = alignment.update(
            confirmation: engine.ingest(Gate4BFixture.qualified(frameID: startID + 1)),
            pnp: Gate4BFixture.qualified(frameID: startID + 1),
            arkit: Gate4BFixture.sidecar(frameID: startID + 1),
            sim3: sim3
        )
        let pnp = Gate4BFixture.qualified(frameID: startID + 2, yawDeg: Double(startID) * 0.05, tvec: [0.10 + Double(startID) * 0.01, 0.20, 6.00])
        let tick = engine.ingest(pnp)
        let result = alignment.update(
            confirmation: tick,
            pnp: pnp,
            arkit: Gate4BFixture.sidecar(frameID: startID + 2),
            sim3: sim3
        )
        return (result, pnp)
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

private enum Gate4BFixture {
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

    static func sidecar(frameID: UInt64) -> ARKitCameraTransformSidecar {
        ARKitCameraTransformSidecar.capture(
            columnMajor4x4: [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0.5, 1.5, 2.5, 1]
            ],
            timestamp: TimeInterval(frameID)
        ).stamped(frameID: frameID, timestamp: TimeInterval(frameID))
    }
}
