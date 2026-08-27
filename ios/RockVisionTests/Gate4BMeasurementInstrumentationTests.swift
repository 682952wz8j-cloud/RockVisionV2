import XCTest
import simd
@testable import RockVision

final class Gate4BMeasurementInstrumentationTests: XCTestCase {
    func testFormalManifestContainsExactlyW01ToW04() throws {
        let formal = try loadFormalManifest()
        XCTAssertEqual(formal.landmarks.map(\.id), ["W01", "W02", "W03", "W04"])
        XCTAssertEqual(formal.wallID, "wall_jiulongfeng_01")
    }

    func testRuntimeFixtureContainsExactlyW01ToW04() throws {
        let fixture = try loadFixture()
        XCTAssertEqual(fixture.landmarks.map(\.id), ["W01", "W02", "W03", "W04"])
        XCTAssertEqual(fixture.wallID, "wall_jiulongfeng_01")
        XCTAssertTrue(fixture.developmentValidationOnly)
        XCTAssertTrue(fixture.notAProductionRouteAsset)
        XCTAssertEqual(fixture.sourceFormalManifest, "validation/gate4b/gate4b_landmarks_frozen.json")
        XCTAssertEqual(fixture.coordinateFrame, "WallMetricMeters")
    }

    func testFixtureXYZMatchesFormalWithinOneMillimeterIncludingTrailingZeroEquivalence() throws {
        let formal = try loadFormalManifest()
        let fixture = try loadFixture()
        var globalMax = 0.0
        for (a, b) in zip(formal.landmarks, fixture.landmarks) {
            XCTAssertEqual(a.id, b.id)
            let d = distance(a.wallXYZMeters, b.wallXYZMeters)
            globalMax = max(globalMax, d)
            XCTAssertLessThanOrEqual(d, 0.001)
        }
        let canonicalW02Z = -46.3900
        let fixtureW02 = try XCTUnwrap(fixture.landmarks.first { $0.id == "W02" })
        XCTAssertEqual(abs(fixtureW02.wallXYZMeters[2] - canonicalW02Z), 0, accuracy: 0)
        XCTAssertEqual(globalMax, 0, accuracy: 0)
    }

    func testRPointsAreAbsentFromRuntimeFixtureAndMarkerSet() throws {
        let fixtureText = try String(contentsOf: fixtureURL(), encoding: .utf8)
        for forbidden in Gate4BMeasurementFixture.forbiddenRuntimeIDs {
            XCTAssertFalse(fixtureText.contains(forbidden))
        }
        let geom = WallAlignmentDebugGeometry.evaluate(
            alignment: makeAligned(identityT(), frameID: 1),
            measurementFixture: try loadFixture(),
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        let ids = (geom.markers ?? []).map(\.landmarkID)
        XCTAssertEqual(ids, ["W01", "W02", "W03", "W04"])
        XCTAssertFalse(ids.contains { $0.hasPrefix("R") })
        XCTAssertEqual(geom.markerCount, 4)
        XCTAssertEqual(geom.validatedLandmarkCount, 0)
    }

    func testPredictedARWorldEqualsCoordinateTransformsApply() throws {
        let t = rigidT(yawDeg: 18, translation: [2.5, -4.0, 9.25])
        let fixture = try loadFixture()
        let geom = WallAlignmentDebugGeometry.evaluate(
            alignment: makeAligned(t, frameID: 8),
            measurementFixture: fixture,
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        for marker in try XCTUnwrap(geom.markers) {
            let expected = try CoordinateTransforms.apply(t, point: marker.wallXYZMeters)
            XCTAssertEqual(marker.predictedARWorldXYZMeters, expected)
        }
    }

    func testIdentityTMapsARWorldToWallXYZ() throws {
        let geom = WallAlignmentDebugGeometry.evaluate(
            alignment: makeAligned(identityT(), frameID: 2),
            measurementFixture: try loadFixture(),
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        for marker in try XCTUnwrap(geom.markers) {
            XCTAssertEqual(distance(marker.predictedARWorldXYZMeters, marker.wallXYZMeters), 0, accuracy: 1e-12)
        }
    }

    func testKnownTranslationMovesMarkers() throws {
        let t = rigidT(yawDeg: 0, translation: [1.0, 2.0, 3.0])
        let geom = WallAlignmentDebugGeometry.evaluate(
            alignment: makeAligned(t, frameID: 3),
            measurementFixture: try loadFixture(),
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        for marker in try XCTUnwrap(geom.markers) {
            XCTAssertEqual(marker.predictedARWorldXYZMeters[0], marker.wallXYZMeters[0] + 1.0, accuracy: 1e-12)
            XCTAssertEqual(marker.predictedARWorldXYZMeters[1], marker.wallXYZMeters[1] + 2.0, accuracy: 1e-12)
            XCTAssertEqual(marker.predictedARWorldXYZMeters[2], marker.wallXYZMeters[2] + 3.0, accuracy: 1e-12)
        }
    }

    func testKnownRotationRotatesMarkers() throws {
        let t = rigidT(yawDeg: 90, translation: [0, 0, 0])
        let wall = [-11.0079, 26.0123, -38.8601]
        let geom = WallAlignmentDebugGeometry.evaluate(
            alignment: makeAligned(t, frameID: 4),
            measurementFixture: try loadFixture(),
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        let w01 = try XCTUnwrap(geom.markers?.first { $0.landmarkID == "W01" })
        let expected = try CoordinateTransforms.apply(t, point: wall)
        XCTAssertEqual(distance(w01.predictedARWorldXYZMeters, expected), 0, accuracy: 1e-12)
        XCTAssertEqual(w01.predictedARWorldXYZMeters[0], wall[2], accuracy: 1e-9)
        XCTAssertEqual(w01.predictedARWorldXYZMeters[1], wall[1], accuracy: 1e-9)
        XCTAssertEqual(w01.predictedARWorldXYZMeters[2], -wall[0], accuracy: 1e-9)
    }

    func testInvalidAlignmentHidesAndClearsMarkers() throws {
        let hidden = WallAlignmentDebugGeometry.evaluate(
            alignment: .none,
            measurementFixture: try loadFixture(),
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        XCTAssertFalse(hidden.visible)
        XCTAssertEqual(hidden.markerCount ?? 0, 0)
        XCTAssertEqual(hidden.markers ?? [], [])
        XCTAssertFalse(hidden.renderedRoute)
    }

    func testLockLossDoesNotKeepOldMarkers() throws {
        var runtime = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        var engine = LocalizationConfirmation()
        let first = localizeThenAlign(&engine, &runtime, sim3: sim3, startID: 11)
        let shown = WallAlignmentDebugGeometry.evaluate(
            alignment: first.alignment,
            measurementFixture: try loadFixture(),
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        XCTAssertEqual(shown.markerCount, 4)
        let previous = try XCTUnwrap(shown.markers)

        var bad = Gate4BAlignFixture.qualified(frameID: 14)
        bad.candidateQualified = false
        let lost = engine.ingest(bad)
        let cleared = runtime.update(
            confirmation: lost,
            pnp: bad,
            arkit: Gate4BAlignFixture.sidecar(frameID: 14),
            sim3: sim3
        )
        let hidden = WallAlignmentDebugGeometry.evaluate(
            alignment: cleared,
            measurementFixture: try loadFixture(),
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        XCTAssertFalse(hidden.visible)
        XCTAssertEqual(hidden.markers ?? [], [])
        XCTAssertNotEqual(previous, hidden.markers ?? [])
    }

    func testNewRollingTDoesNotReuseOldPredictedPositions() throws {
        var runtime = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        var engine = LocalizationConfirmation()
        let first = localizeThenAlign(&engine, &runtime, sim3: sim3, startID: 11)
        let shown = WallAlignmentDebugGeometry.evaluate(
            alignment: first.alignment,
            measurementFixture: try loadFixture(),
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        var bad = Gate4BAlignFixture.qualified(frameID: 14)
        bad.candidateQualified = false
        _ = runtime.update(
            confirmation: engine.ingest(bad),
            pnp: bad,
            arkit: Gate4BAlignFixture.sidecar(frameID: 14),
            sim3: sim3
        )
        let again = localizeThenAlign(&engine, &runtime, sim3: sim3, startID: 20)
        let relocated = WallAlignmentDebugGeometry.evaluate(
            alignment: again.alignment,
            measurementFixture: try loadFixture(),
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        XCTAssertEqual(relocated.markerCount, 4)
        XCTAssertNotEqual(relocated.T_ARWorld_Wall, shown.T_ARWorld_Wall)
        XCTAssertNotEqual(relocated.markers, shown.markers)
        XCTAssertFalse(relocated.renderedRoute)
        for marker in try XCTUnwrap(relocated.markers) {
            let expected = try CoordinateTransforms.apply(
                try XCTUnwrap(relocated.T_ARWorld_Wall),
                point: marker.wallXYZMeters
            )
            XCTAssertEqual(marker.predictedARWorldXYZMeters, expected)
        }
    }

    func testRenderedRouteRemainsFalse() throws {
        let geom = WallAlignmentDebugGeometry.evaluate(
            alignment: makeAligned(identityT(), frameID: 5),
            measurementFixture: try loadFixture(),
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        XCTAssertFalse(geom.renderedRoute)
        XCTAssertFalse(geom.visible == false && geom.renderedRoute)
    }

    func testOverlayRootLifecycleClearsMarkersWithAxes() throws {
        let overlay = try readHostSource("RockVision/Features/DebugOverlay/WallAlignmentDebugOverlay.swift")
        XCTAssertTrue(overlay.contains("root.children.removeAll()"))
        let removeIdx = try XCTUnwrap(overlay.range(of: "root.children.removeAll()")?.lowerBound)
        let markerIdx = try XCTUnwrap(overlay.range(of: "measurementMarker")?.lowerBound)
        XCTAssertLessThan(removeIdx, markerIdx)
        XCTAssertFalse(overlay.contains("CoordinateTransforms.apply"))
        XCTAssertFalse(overlay.contains("look(at"))
        XCTAssertFalse(overlay.contains("billboard"))
        XCTAssertFalse(overlay.contains("physicalError"))
        XCTAssertFalse(overlay.contains("workingGroundTruthUncertainty"))
    }

    func testWrongWallIDHidesMarkersWithoutFallback() throws {
        let geom = WallAlignmentDebugGeometry.evaluate(
            alignment: makeAligned(identityT(), frameID: 6),
            measurementFixture: try loadFixture(),
            currentWallID: "some_other_wall"
        )
        XCTAssertTrue(geom.visible)
        XCTAssertEqual(geom.markerCount, 0)
        XCTAssertEqual(geom.markers ?? [], [])
        XCTAssertEqual(geom.validatedLandmarkCount, 0)
    }

    func testMissingWallIDHidesMarkers() throws {
        let geom = WallAlignmentDebugGeometry.evaluate(
            alignment: makeAligned(identityT(), frameID: 7),
            measurementFixture: try loadFixture(),
            currentWallID: nil
        )
        XCTAssertEqual(geom.markerCount, 0)
        XCTAssertEqual(geom.markers ?? [], [])
    }

    func testW02RemainsInRuntimeMarkerSet() throws {
        let geom = WallAlignmentDebugGeometry.evaluate(
            alignment: makeAligned(identityT(), frameID: 9),
            measurementFixture: try loadFixture(),
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        XCTAssertEqual((geom.markers ?? []).map(\.landmarkID), ["W01", "W02", "W03", "W04"])
    }

    func testOldGeometryJSONWithoutMarkersStillDecodes() throws {
        let json = """
        {"kind":"WallAlignmentDebugGeometry","visible":false,"consumedProductionT_ARWorld_Wall":false,"renderedRoute":false,"validatedLandmarkCount":0,"finite":true}
        """
        let decoded = try JSONDecoder().decode(WallAlignmentDebugGeometry.self, from: Data(json.utf8))
        XCTAssertNil(decoded.markerCount)
        XCTAssertNil(decoded.markers)
        XCTAssertEqual(decoded.validatedLandmarkCount, 0)
        XCTAssertEqual(FieldTestExportSchema.version, "gate4b.runtime.1")
    }

    func testExportSummaryHasMarkersAndNoPhysicalError() throws {
        let export = try readHostSource("RockVision/Features/FieldTest/FieldTestExport.swift")
        XCTAssertTrue(export.contains("measurementMarkers:"))
        XCTAssertFalse(export.contains("physicalErrorMeters"))
        XCTAssertFalse(export.contains("within2cm"))
        XCTAssertFalse(export.contains("measurementPass"))
    }

    func testFloatOnlyAtRenderingBoundary() throws {
        let geom = try readHostSource("RockVision/Features/PnP/WallAlignmentDebugGeometry.swift")
        XCTAssertTrue(geom.contains("CoordinateTransforms.apply(transform, point: landmark.wallXYZMeters)"))
        XCTAssertFalse(geom.contains("SIMD3<Float>"))
        let overlay = try readHostSource("RockVision/Features/DebugOverlay/WallAlignmentDebugOverlay.swift")
        XCTAssertTrue(overlay.contains("simd3(marker.predictedARWorldXYZMeters)"))
        XCTAssertTrue(overlay.contains("group.position = center"))
        XCTAssertTrue(overlay.contains("markerLabelLocalOffset"))
        XCTAssertFalse(overlay.contains("CoordinateTransforms.apply"))
    }

    func testLabelOffsetDoesNotMoveMarkerCenter() throws {
        XCTAssertEqual(WallAlignmentDebugOverlay.markerLabelLocalOffset, SIMD3<Float>(0, 0.055, 0))
        XCTAssertGreaterThan(WallAlignmentDebugOverlay.markerDotRadius, 0)
        XCTAssertLessThanOrEqual(WallAlignmentDebugOverlay.markerDotRadius, 0.015)
        XCTAssertGreaterThanOrEqual(WallAlignmentDebugOverlay.markerArmLength, 0.08)
        XCTAssertLessThanOrEqual(WallAlignmentDebugOverlay.markerArmLength, 0.15)
    }

    func testNoSecondTransformOrSmoothingInInstrumentation() throws {
        let overlay = try readHostSource("RockVision/Features/DebugOverlay/WallAlignmentDebugOverlay.swift")
        let geom = try readHostSource("RockVision/Features/PnP/WallAlignmentDebugGeometry.swift")
        let fixture = try readHostSource("RockVision/Features/PnP/Gate4BMeasurementFixture.swift")
        let joined = overlay + geom + fixture
        XCTAssertFalse(joined.contains("Kalman"))
        XCTAssertFalse(joined.contains("low-pass"))
        XCTAssertFalse(joined.contains("empirical"))
        XCTAssertFalse(joined.contains("screen-space"))
        XCTAssertFalse(joined.contains("inverseSim3"))
        XCTAssertFalse(joined.contains("productionAlignment("))
    }

    private func loadFormalManifest() throws -> FormalLandmarks {
        let url = repoRoot().appendingPathComponent("validation/gate4b/gate4b_landmarks_frozen.json")
        return try JSONDecoder().decode(FormalLandmarks.self, from: try Data(contentsOf: url))
    }

    private func loadFixture() throws -> Gate4BMeasurementFixture {
        if let bundled = Gate4BMeasurementFixture.loadFromBundle(Bundle(for: OpenCVFrameProcessor.self)) {
            return bundled
        }
        return try Gate4BMeasurementFixture.load(from: fixtureURL())
    }

    private func fixtureURL() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("RockVision/Resources/Gate4BMeasurementFixture.json")
    }

    private func repoRoot() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
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
                T_ARWorld_arkitCam: identityT()
            ),
            confirmedEqualsLatestRefined: true
        )
    }

    private func identityT() -> [[Double]] {
        [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ]
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

    private func distance(_ a: [Double], _ b: [Double]) -> Double {
        sqrt(zip(a, b).map { ($0 - $1) * ($0 - $1) }.reduce(0, +))
    }

    private func localizeThenAlign(
        _ engine: inout LocalizationConfirmation,
        _ alignment: inout ProductionAlignmentRuntime,
        sim3: ValidatedSim3,
        startID: UInt64
    ) -> (alignment: AlignmentFrameResult, pnp: PnPFrameResult) {
        _ = alignment.update(
            confirmation: engine.ingest(Gate4BAlignFixture.qualified(frameID: startID)),
            pnp: Gate4BAlignFixture.qualified(frameID: startID),
            arkit: Gate4BAlignFixture.sidecar(frameID: startID),
            sim3: sim3
        )
        _ = alignment.update(
            confirmation: engine.ingest(Gate4BAlignFixture.qualified(frameID: startID + 1)),
            pnp: Gate4BAlignFixture.qualified(frameID: startID + 1),
            arkit: Gate4BAlignFixture.sidecar(frameID: startID + 1),
            sim3: sim3
        )
        let pnp = Gate4BAlignFixture.qualified(
            frameID: startID + 2,
            yawDeg: Double(startID) * 0.05,
            tvec: [0.10 + Double(startID) * 0.01, 0.20, 6.00]
        )
        let tick = engine.ingest(pnp)
        let result = alignment.update(
            confirmation: tick,
            pnp: pnp,
            arkit: Gate4BAlignFixture.sidecar(frameID: startID + 2),
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

private struct FormalLandmarks: Decodable {
    var wallID: String
    var landmarks: [Gate4BMeasurementLandmark]
}

private enum Gate4BAlignFixture {
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
