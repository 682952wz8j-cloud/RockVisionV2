import XCTest
@testable import RockVision

final class Gate5CRuntimeRouteBindingTests: XCTestCase {
    private let expectedHash = FrozenRoutePolylineHash.expectedRouteTest01
    private let frozenScale = 3.19764417024824
    private let tol = 1e-9

    func testFrozenArtifactLoadAndHashPass() throws {
        let route = try XCTUnwrap(VerifiedFrozenRoute.loadCanonicalIngested(from: canonicalURL()))
        XCTAssertEqual(route.routeId, "route_test_01")
        XCTAssertEqual(route.wallId, "wall_jiulongfeng_01")
        XCTAssertEqual(route.coordinateFrame, "WallMetricMeters")
        XCTAssertEqual(route.provenance, "IDENTITY_PROVEN")
        XCTAssertTrue(route.dummyOriginExcluded)
        XCTAssertEqual(route.wallMetricMeters.count, 11)
        XCTAssertTrue(route.hashVerified)
        XCTAssertFalse(route.wallMetricMeters.contains { $0 == [0.0, 0.0, 0.0] })

        let bytes = try XCTUnwrap(FrozenRoutePolylineHash.canonicalBytes(route.wallMetricMeters))
        XCTAssertEqual(bytes.count, 264)
        XCTAssertEqual(FrozenRoutePolylineHash.sha256Hex(route.wallMetricMeters), expectedHash)
        XCTAssertEqual(route.polylineSha256, expectedHash)
    }

    func testDevelopmentFixtureIsBitIdenticalToCanonicalAndBundleLoadable() throws {
        let canonical = try XCTUnwrap(VerifiedFrozenRoute.loadCanonicalIngested(from: canonicalURL()))
        let fixture = try XCTUnwrap(VerifiedFrozenRoute.load(from: fixtureURL()))
        XCTAssertTrue(fixture.developmentValidationOnly)
        XCTAssertEqual(fixture.wallMetricMeters.count, 11)
        XCTAssertEqual(fixture.polylineSha256, canonical.polylineSha256)
        XCTAssertEqual(FrozenRoutePolylineHash.sha256Hex(fixture.wallMetricMeters), expectedHash)
        for i in 0..<11 {
            XCTAssertEqual(fixture.wallMetricMeters[i][0], canonical.wallMetricMeters[i][0])
            XCTAssertEqual(fixture.wallMetricMeters[i][1], canonical.wallMetricMeters[i][1])
            XCTAssertEqual(fixture.wallMetricMeters[i][2], canonical.wallMetricMeters[i][2])
        }
        XCTAssertEqual(VerifiedFrozenRoute.resourceName, "Gate5CRouteFixture")
        if let bundled = VerifiedFrozenRoute.loadFromBundle(Bundle(for: OpenCVFrameProcessor.self)) {
            XCTAssertEqual(bundled.polylineSha256, expectedHash)
            XCTAssertEqual(bundled.wallMetricMeters.count, 11)
        }
    }

    func testHashTamperFailsClosedWithZeroARWorldPoints() throws {
        var payload = try JSONDecoder().decode(
            VerifiedFrozenRoute.FixtureFile.self,
            from: Data(contentsOf: fixtureURL())
        )
        payload.polyline[0][0] += 1.0
        let tampered = try JSONEncoder().encode(payload)
        XCTAssertNil(VerifiedFrozenRoute.load(from: tampered))
        XCTAssertNotEqual(
            FrozenRoutePolylineHash.sha256Hex(payload.polyline),
            expectedHash
        )

        let aligned = AlignmentFrameResult.aligned(
            transform: identitySE3(),
            provenance: dummyProvenance(),
            confirmedEqualsLatestRefined: true
        )
        let bound = RuntimeRouteBinding.evaluate(verifiedRoute: nil, alignment: aligned)
        XCTAssertEqual(bound.routeARWorldPointCount, 0)
        XCTAssertTrue(bound.routeARWorldPoints.isEmpty)
        XCTAssertFalse(bound.hasBoundRoute)
        XCTAssertEqual(bound.renderedRoute, false)
    }

    func testNoCurrentTYieldsZeroPointsEvenIfHashVerified() throws {
        let route = try loadCanonical()
        var none = AlignmentFrameResult.none
        none.status = "none"
        none.hasT_ARWorld_Wall = false
        none.T_ARWorld_Wall = nil
        let bound = RuntimeRouteBinding.evaluate(verifiedRoute: route, alignment: none)
        XCTAssertTrue(route.hashVerified)
        XCTAssertEqual(bound.hashVerified, true)
        XCTAssertEqual(bound.routeARWorldPointCount, 0)
        XCTAssertTrue(bound.routeARWorldPoints.isEmpty)
        XCTAssertEqual(bound.reason, "noCurrentT_ARWorld_Wall")
        XCTAssertEqual(bound.renderedRoute, false)
    }

    func testCurrentAlignmentBindsAllElevenPointsThroughGate5BApply() throws {
        let route = try loadCanonical()
        let t1 = se3(yawDeg: 12, translation: [1.0, -2.0, 3.0])
        let aligned = AlignmentFrameResult.aligned(
            transform: t1,
            provenance: dummyProvenance(),
            confirmedEqualsLatestRefined: true
        )
        let bound = RuntimeRouteBinding.evaluate(verifiedRoute: route, alignment: aligned)
        XCTAssertTrue(bound.hasBoundRoute)
        XCTAssertEqual(bound.routeARWorldPointCount, 11)
        XCTAssertEqual(bound.routeARWorldPoints.count, 11)
        XCTAssertEqual(bound.renderedRoute, false)
        for i in 0..<11 {
            let expected = try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                wallPointMeters: route.wallMetricMeters[i],
                T_ARWorld_Wall: t1
            )
            assertAlmostEqual(bound.routeARWorldPoints[i], expected)
        }
    }

    func testAlignmentLossClearsStaleARWorldGeometry() throws {
        let route = try loadCanonical()
        let t1 = se3(yawDeg: 8, translation: [0.5, 1.5, 2.5])
        let bound = RuntimeRouteBinding.evaluate(
            verifiedRoute: route,
            alignment: AlignmentFrameResult.aligned(
                transform: t1,
                provenance: dummyProvenance(frameID: 13),
                confirmedEqualsLatestRefined: true
            )
        )
        XCTAssertEqual(bound.routeARWorldPointCount, 11)

        let cleared = RuntimeRouteBinding.evaluate(
            verifiedRoute: route,
            alignment: AlignmentFrameResult.none
        )
        XCTAssertEqual(cleared.routeARWorldPointCount, 0)
        XCTAssertTrue(cleared.routeARWorldPoints.isEmpty)
        XCTAssertFalse(cleared.hasBoundRoute)
    }

    func testSameLifetimeRollingTRecomputesAllPoints() throws {
        let route = try loadCanonical()
        let t1 = se3(yawDeg: 5, translation: [1.0, 0.0, 0.0])
        let t2 = se3(yawDeg: 25, translation: [0.0, 4.0, -1.0])
        XCTAssertNotEqual(t1, t2)

        let b1 = RuntimeRouteBinding.evaluate(
            verifiedRoute: route,
            alignment: AlignmentFrameResult.aligned(
                transform: t1,
                provenance: dummyProvenance(frameID: 13),
                confirmedEqualsLatestRefined: true
            )
        )
        let b2 = RuntimeRouteBinding.evaluate(
            verifiedRoute: route,
            alignment: AlignmentFrameResult.aligned(
                transform: t2,
                provenance: dummyProvenance(frameID: 14),
                confirmedEqualsLatestRefined: true
            )
        )
        XCTAssertEqual(b1.routeARWorldPointCount, 11)
        XCTAssertEqual(b2.routeARWorldPointCount, 11)
        XCTAssertNotEqual(b1.routeARWorldPoints, b2.routeARWorldPoints)
        for i in 0..<11 {
            let expected = try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                wallPointMeters: route.wallMetricMeters[i],
                T_ARWorld_Wall: t2
            )
            assertAlmostEqual(b2.routeARWorldPoints[i], expected)
            XCTAssertNotEqual(b2.routeARWorldPoints[i], b1.routeARWorldPoints[i])
        }
    }

    func testRelocalizationUsesNewTAndDoesNotKeepPreviousLifetimeGeometry() throws {
        let route = try loadCanonical()
        let tA = se3(yawDeg: 10, translation: [2.0, 0.0, 0.0])
        let tB = se3(yawDeg: -15, translation: [0.0, 0.0, 6.0])

        let lifeA = RuntimeRouteBinding.evaluate(
            verifiedRoute: route,
            alignment: AlignmentFrameResult.aligned(
                transform: tA,
                provenance: dummyProvenance(frameID: 13),
                confirmedEqualsLatestRefined: true
            )
        )
        XCTAssertEqual(lifeA.routeARWorldPointCount, 11)

        let lost = RuntimeRouteBinding.evaluate(verifiedRoute: route, alignment: .none)
        XCTAssertEqual(lost.routeARWorldPointCount, 0)

        let lifeB = RuntimeRouteBinding.evaluate(
            verifiedRoute: route,
            alignment: AlignmentFrameResult.aligned(
                transform: tB,
                provenance: dummyProvenance(frameID: 23),
                confirmedEqualsLatestRefined: true
            )
        )
        XCTAssertEqual(lifeB.routeARWorldPointCount, 11)
        XCTAssertNotEqual(lifeB.routeARWorldPoints, lifeA.routeARWorldPoints)
        for i in 0..<11 {
            let expected = try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                wallPointMeters: route.wallMetricMeters[i],
                T_ARWorld_Wall: tB
            )
            assertAlmostEqual(lifeB.routeARWorldPoints[i], expected)
        }
    }

    func testHashFailureDominatesValidAlignment() throws {
        var bad = try loadCanonical()
        bad.hashVerified = false
        bad.wallMetricMeters[0][0] += 1.0
        let aligned = AlignmentFrameResult.aligned(
            transform: identitySE3(),
            provenance: dummyProvenance(),
            confirmedEqualsLatestRefined: true
        )
        let bound = RuntimeRouteBinding.evaluate(verifiedRoute: bad, alignment: aligned)
        XCTAssertTrue(aligned.hasT_ARWorld_Wall)
        XCTAssertEqual(bound.routeARWorldPointCount, 0)
        XCTAssertFalse(bound.hasBoundRoute)
        XCTAssertEqual(bound.reason, "hashUnverified")
        XCTAssertEqual(bound.renderedRoute, false)
    }

    func testNoDoubleScaleOnRoutePoints() throws {
        let route = try loadCanonical()
        let t = se3(yawDeg: 7, translation: [0.2, 0.3, 0.4])
        let bound = RuntimeRouteBinding.evaluate(
            verifiedRoute: route,
            alignment: AlignmentFrameResult.aligned(
                transform: t,
                provenance: dummyProvenance(),
                confirmedEqualsLatestRefined: true
            )
        )
        for i in 0..<11 {
            let x = route.wallMetricMeters[i]
            let scaled = [frozenScale * x[0], frozenScale * x[1], frozenScale * x[2]]
            let wrong = try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                wallPointMeters: scaled,
                T_ARWorld_Wall: t
            )
            XCTAssertGreaterThan(norm(sub(bound.routeARWorldPoints[i], wrong)), 1.0)
        }
        let source = try readHostSource("RockVision/Features/PnP/RuntimeRouteBinding.swift")
        XCTAssertFalse(source.contains("S_wall_colmap"))
        XCTAssertFalse(source.contains("ValidatedSim3"))
        XCTAssertFalse(source.contains("3.19764417024824"))
        XCTAssertTrue(source.contains("applyFrozenWallRoutePointToARWorld"))
        XCTAssertFalse(source.contains("productionAlignment("))
    }

    func testNoExtraRouteAxisFlipAndFrozenCameraBasisUntouched() throws {
        let transforms = try readHostSource("RockVision/Features/PnP/CoordinateTransforms.swift")
        XCTAssertTrue(transforms.contains("static let T_arkitCam_opencvCam"))
        XCTAssertEqual(CoordinateTransforms.T_arkitCam_opencvCam[1][1], -1, accuracy: 0)
        XCTAssertEqual(CoordinateTransforms.T_arkitCam_opencvCam[2][2], -1, accuracy: 0)

        let binding = try readHostSource("RockVision/Features/PnP/RuntimeRouteBinding.swift")
        XCTAssertFalse(binding.contains("T_arkitCam_opencvCam"))
        XCTAssertFalse(binding.contains("y = -y"))
        XCTAssertFalse(binding.contains("z = -z"))
        XCTAssertFalse(binding.contains("RouteAlignment"))
        XCTAssertFalse(binding.contains("RouteCorrection"))

        let debugGeom = try readHostSource("RockVision/Features/PnP/WallAlignmentDebugGeometry.swift")
        XCTAssertFalse(debugGeom.contains("route_test_01"))
        XCTAssertFalse(debugGeom.contains("RuntimeRouteBinding"))
    }

    func testProductionAlignmentIntegrationBindsElevenPoints() throws {
        let route = try loadCanonical()
        var engine = LocalizationConfirmation()
        var alignment = ProductionAlignmentRuntime()
        let sim3 = try XCTUnwrap(loadSim3())
        let localized = localizeThree(&engine, &alignment, sim3: sim3)
        XCTAssertEqual(localized.tick.localizationState, "localized")
        XCTAssertTrue(localized.alignment.hasT_ARWorld_Wall)
        XCTAssertTrue(localized.alignment.productionAlignmentCalled)
        let t = try XCTUnwrap(localized.alignment.T_ARWorld_Wall)
        let expectedT = try CoordinateTransforms.productionAlignment(
            T_opencvCam_colmap: try XCTUnwrap(localized.pnp.T_opencvCam_colmap),
            S_wall_colmap: sim3,
            T_ARWorld_arkitCam: try XCTUnwrap(localized.alignment.provenance?.T_ARWorld_arkitCam)
        )
        XCTAssertEqual(t, expectedT)

        let bound = RuntimeRouteBinding.evaluate(
            verifiedRoute: route,
            alignment: localized.alignment
        )
        XCTAssertEqual(bound.routeARWorldPointCount, 11)
        XCTAssertTrue(bound.hasBoundRoute)
        XCTAssertEqual(bound.renderedRoute, false)
        for i in 0..<11 {
            let expected = try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                wallPointMeters: route.wallMetricMeters[i],
                T_ARWorld_Wall: t
            )
            assertAlmostEqual(bound.routeARWorldPoints[i], expected)
        }

        let fourth = Gate5CPnPFixture.qualified(frameID: 14, yawDeg: 3.0, wall: [1.14, 2.02, 3.01], tvec: [0.44, 0.22, 6.08])
        let tick = engine.ingest(fourth)
        XCTAssertEqual(tick.localizationState, "localized")
        let next = alignment.update(
            confirmation: tick,
            pnp: fourth,
            arkit: Gate5CPnPFixture.sidecar(frameID: 14),
            sim3: sim3
        )
        XCTAssertTrue(next.hasT_ARWorld_Wall)
        XCTAssertNotEqual(next.T_ARWorld_Wall, t)
        let rolled = RuntimeRouteBinding.evaluate(verifiedRoute: route, alignment: next)
        XCTAssertEqual(rolled.routeARWorldPointCount, 11)
        XCTAssertNotEqual(rolled.routeARWorldPoints, bound.routeARWorldPoints)
        let t2 = try XCTUnwrap(next.T_ARWorld_Wall)
        for i in 0..<11 {
            let expected = try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                wallPointMeters: route.wallMetricMeters[i],
                T_ARWorld_Wall: t2
            )
            assertAlmostEqual(rolled.routeARWorldPoints[i], expected)
        }

        let lost = alignment.update(
            confirmation: ConfirmationTick(
                localizationState: ConfirmationConfig.localizationIdle,
                windowCount: 0,
                accepted: false,
                resetReason: "lost",
                adjacentRotationDeg: nil,
                adjacentCWallMeters: nil,
                confirmedT_opencvCam_colmap: nil,
                confirmedFrameID: nil,
                confirmedTimestamp: nil,
                currentFrameID: 15,
                currentTimestamp: 15,
                confirmedEqualsLatestRefined: nil,
                enteredLocalized: false,
                lostLocalized: true,
                restartedFromBreakingFrame: false,
                windowFrameIDs: [],
                hasT_ARWorld_Wall: false,
                usedARKitInConfirmation: false,
                usedGPSInConfirmation: false,
                usedPreviousPosePnPPrior: false
            ),
            pnp: .inactive(reason: "lost"),
            arkit: nil,
            sim3: sim3
        )
        XCTAssertFalse(lost.hasT_ARWorld_Wall)
        let afterLoss = RuntimeRouteBinding.evaluate(verifiedRoute: route, alignment: lost)
        XCTAssertEqual(afterLoss.routeARWorldPointCount, 0)
    }

    func testSharedRuntimeHashVerifierUsedByTestsAndLoader() throws {
        let source = try readHostSource("RockVision/Features/PnP/RuntimeRouteBinding.swift")
        XCTAssertTrue(source.contains("enum FrozenRoutePolylineHash"))
        XCTAssertTrue(source.contains("SHA256.hash(data: bytes)"))
        XCTAssertTrue(source.contains("coord.bitPattern.littleEndian"))
        let tests = try readHostSource("RockVisionTests/Gate5CRuntimeRouteBindingTests.swift")
        XCTAssertTrue(tests.contains("FrozenRoutePolylineHash.sha256Hex"))
        XCTAssertTrue(tests.contains("FrozenRoutePolylineHash.canonicalBytes"))
        XCTAssertTrue(source.contains("import CryptoKit"))
        XCTAssertTrue(source.contains("enum FrozenRoutePolylineHash"))
    }

    func testRenderedRouteRemainsFalseWhenBoundAndNoRenderingCode() throws {
        let route = try loadCanonical()
        let bound = RuntimeRouteBinding.evaluate(
            verifiedRoute: route,
            alignment: AlignmentFrameResult.aligned(
                transform: identitySE3(),
                provenance: dummyProvenance(),
                confirmedEqualsLatestRefined: true
            )
        )
        XCTAssertEqual(bound.routeARWorldPointCount, 11)
        XCTAssertEqual(bound.renderedRoute, false)
        XCTAssertTrue(bound.hasBoundRoute)

        let binding = try readHostSource("RockVision/Features/PnP/RuntimeRouteBinding.swift")
        XCTAssertFalse(binding.contains("RealityKit"))
        XCTAssertFalse(binding.contains("ModelEntity"))
        XCTAssertFalse(binding.contains("AnchorEntity"))
        XCTAssertFalse(binding.contains("SceneKit"))
        XCTAssertFalse(binding.contains("renderedRoute = true"))

        let overlay = try readHostSource("RockVision/Features/DebugOverlay/WallAlignmentDebugOverlay.swift")
        XCTAssertFalse(overlay.contains("RuntimeRouteBinding"))
        XCTAssertFalse(overlay.contains("route_test_01"))

        let processor = try readHostSource("RockVision/Features/OpenCV/OpenCVFrameProcessor.swift")
        XCTAssertTrue(processor.contains("alignmentRuntime.update"))
        XCTAssertTrue(processor.contains("RuntimeRouteBinding.evaluate"))
        XCTAssertFalse(processor.contains("RouteOverlay"))
        XCTAssertFalse(processor.contains("CLLocation"))
        XCTAssertFalse(processor.contains("CLHeading"))
    }

    func testEvaluateDoesNotTakeLocalizationState() throws {
        let source = try readHostSource("RockVision/Features/PnP/RuntimeRouteBinding.swift")
        XCTAssertTrue(source.contains("Does not inspect localizationState"))
        XCTAssertTrue(source.contains("frozenRouteHashVerified && currentAlignment.hasT_ARWorld_Wall"))
        XCTAssertFalse(source.contains("localizationState =="))
        XCTAssertFalse(source.contains("localizationLocalized"))
    }

    // MARK: - Helpers

    private func loadCanonical() throws -> VerifiedFrozenRoute {
        try XCTUnwrap(VerifiedFrozenRoute.loadCanonicalIngested(from: canonicalURL()))
    }

    private func canonicalURL() -> URL {
        repoRoot().appendingPathComponent("validation/gate5a/gate5a_ingested_route_test_01.json")
    }

    private func fixtureURL() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("RockVision/Resources/Gate5CRouteFixture.json")
    }

    private func repoRoot() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    private func dummyProvenance(frameID: UInt64 = 13) -> AlignmentProvenance {
        AlignmentProvenance(
            confirmedFrameID: frameID,
            confirmedTimestamp: TimeInterval(frameID),
            T_opencvCam_colmap: identitySE3(),
            arFrameID: frameID,
            arFrameTimestamp: TimeInterval(frameID),
            T_ARWorld_arkitCam: identitySE3()
        )
    }

    private func identitySE3() -> [[Double]] {
        [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ]
    }

    private func se3(yawDeg: Double, translation: [Double]) -> [[Double]] {
        let r = yawDeg * .pi / 180.0
        let c = cos(r)
        let s = sin(r)
        let R = [
            [c, 0, s],
            [0, 1.0, 0],
            [-s, 0, c]
        ]
        return [
            [R[0][0], R[0][1], R[0][2], translation[0]],
            [R[1][0], R[1][1], R[1][2], translation[1]],
            [R[2][0], R[2][1], R[2][2], translation[2]],
            [0, 0, 0, 1]
        ]
    }

    private func localizeThree(
        _ engine: inout LocalizationConfirmation,
        _ alignment: inout ProductionAlignmentRuntime,
        sim3: ValidatedSim3
    ) -> (tick: ConfirmationTick, pnp: PnPFrameResult, alignment: AlignmentFrameResult) {
        _ = alignment.update(
            confirmation: engine.ingest(Gate5CPnPFixture.qualified(frameID: 11)),
            pnp: Gate5CPnPFixture.qualified(frameID: 11),
            arkit: Gate5CPnPFixture.sidecar(frameID: 11),
            sim3: sim3
        )
        _ = alignment.update(
            confirmation: engine.ingest(Gate5CPnPFixture.qualified(frameID: 12)),
            pnp: Gate5CPnPFixture.qualified(frameID: 12),
            arkit: Gate5CPnPFixture.sidecar(frameID: 12),
            sim3: sim3
        )
        let pnp = Gate5CPnPFixture.qualified(frameID: 13)
        let tick = engine.ingest(pnp)
        let result = alignment.update(
            confirmation: tick,
            pnp: pnp,
            arkit: Gate5CPnPFixture.sidecar(frameID: 13),
            sim3: sim3
        )
        return (tick, pnp, result)
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

    private func assertAlmostEqual(_ a: [Double], _ b: [Double], file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(a.count, 3, file: file, line: line)
        XCTAssertEqual(b.count, 3, file: file, line: line)
        XCTAssertEqual(a[0], b[0], accuracy: tol, file: file, line: line)
        XCTAssertEqual(a[1], b[1], accuracy: tol, file: file, line: line)
        XCTAssertEqual(a[2], b[2], accuracy: tol, file: file, line: line)
    }

    private func sub(_ a: [Double], _ b: [Double]) -> [Double] {
        [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
    }

    private func norm(_ v: [Double]) -> Double {
        sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    }
}

private enum Gate5CPnPFixture {
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
