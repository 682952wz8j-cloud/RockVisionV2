import CryptoKit
import XCTest
@testable import RockVision

/// Gate 5B: frozen WallMetricMeters polyline is transformed to ARWorld
/// exclusively through existing production `T_ARWorld_Wall`.
final class Gate5BRouteTransformTests: XCTestCase {
    private let expectedHash = "ff6ff3ee58303634d369b919284ee8c827a80eb57a9403004614cda6194d2f99"
    private let frozenScale = 3.19764417024824
    private let applyTol = 1e-12
    private let se3Tol = 1e-9

    func testFrozenHashIs264ByteBinary64LittleEndian() throws {
        let ingested = try loadIngested()
        XCTAssertEqual(ingested.schemaVersion, "gate5a.ingested.route.1")
        XCTAssertEqual(ingested.kind, "canonical_ingested_route")
        XCTAssertEqual(ingested.routeId, "route_test_01")
        XCTAssertEqual(ingested.wallId, "wall_jiulongfeng_01")
        XCTAssertEqual(ingested.coordinateFrame, "WallMetricMeters")
        XCTAssertEqual(ingested.provenance, "IDENTITY_PROVEN")
        XCTAssertTrue(ingested.dummyOriginExcluded)
        XCTAssertEqual(ingested.pointCount, 11)
        XCTAssertEqual(ingested.polyline.count, 11)
        XCTAssertEqual(ingested.polylineSha256, expectedHash)

        let closure = try loadClosure()
        XCTAssertEqual(closure.FIRST_ROUTE_FROZEN, true)
        XCTAssertEqual(closure.FIRST_ROUTE_ID, "route_test_01")
        XCTAssertEqual(closure.GATE_5A_PASS, true)
        XCTAssertEqual(closure.gate5AStatus, "PASS_CLOSED")
        XCTAssertEqual(closure.ingestedPolylineSha256, expectedHash)
        XCTAssertEqual(closure.ingestedPolylineSha256, ingested.polylineSha256)

        let bytes = try canonicalBinary64Bytes(ingested.polyline)
        XCTAssertEqual(bytes.count, 264)
        XCTAssertEqual(sha256Hex(bytes), expectedHash)
        XCTAssertFalse(ingested.polyline.contains { $0 == [0.0, 0.0, 0.0] })
    }

    func testIdentityApplyLeavesAllElevenPointsUnchanged() throws {
        let points = try loadIngested().polyline
        XCTAssertEqual(points.count, 11)
        let identity = identitySE3()
        for p in points {
            let y = try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                wallPointMeters: p,
                T_ARWorld_Wall: identity
            )
            assertAlmostEqual(y, p, accuracy: applyTol)
        }
    }

    func testKnownRigidSE3MatchesIndependentOracleForAllElevenPoints() throws {
        let points = try loadIngested().polyline
        XCTAssertEqual(points.count, 11)
        let R = yaw(27.0)
        let t = [1.25, -0.40, 3.75]
        let T = se3(rotation: R, translation: t)
        for p in points {
            let actual = try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                wallPointMeters: p,
                T_ARWorld_Wall: T
            )
            let expected = independentApply(rotation: R, translation: t, point: p)
            assertAlmostEqual(actual, expected, accuracy: se3Tol)
        }
    }

    func testTranslationAffectsRouteVerticesExactlyOnce() throws {
        let points = try loadIngested().polyline
        XCTAssertEqual(points.count, 11)
        let R = yaw(-19.0)
        let t = [4.0, -2.5, 1.5]
        let T = se3(rotation: R, translation: t)
        for p in points {
            let actual = try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                wallPointMeters: p,
                T_ARWorld_Wall: T
            )
            let rotatedOnly = independentRotate(R, p)
            let delta = sub(actual, rotatedOnly)
            assertAlmostEqual(delta, t, accuracy: se3Tol)
            let twice = add(delta, t)
            XCTAssertGreaterThan(norm(sub(twice, t)), 1.0)
        }
    }

    func testKnownRigidPreservesConsecutiveDistancesAndTotalLength() throws {
        let points = try loadIngested().polyline
        let R = yaw(33.0)
        let t = [-2.0, 0.75, 5.0]
        let T = se3(rotation: R, translation: t)
        let transformed = try points.map {
            try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                wallPointMeters: $0,
                T_ARWorld_Wall: T
            )
        }
        assertLengthPreservation(before: points, after: transformed, accuracy: se3Tol)
    }

    func testProductionAlignmentIntegrationForAllElevenPoints() throws {
        let ingested = try loadIngested()
        let points = ingested.polyline
        XCTAssertEqual(ingested.coordinateFrame, "WallMetricMeters")
        XCTAssertEqual(points.count, 11)

        XCTAssertEqual(
            CoordinateTransforms.T_arkitCam_opencvCam,
            [
                [1, 0, 0, 0],
                [0, -1, 0, 0],
                [0, 0, -1, 0],
                [0, 0, 0, 1]
            ]
        )

        let sim3 = try XCTUnwrap(loadSim3())
        XCTAssertEqual(sim3.scale, frozenScale, accuracy: 1e-12)
        let T_opencvCam_colmap = se3(rotation: yaw(18.0), translation: [0.40, -0.25, 5.50])
        let T_ARWorld_arkitCam = se3(rotation: yaw(-12.0), translation: [8.0, 1.0, -3.0])

        let actualT = try CoordinateTransforms.productionAlignment(
            T_opencvCam_colmap: T_opencvCam_colmap,
            S_wall_colmap: sim3,
            T_ARWorld_arkitCam: T_ARWorld_arkitCam
        )

        let expectedT = independentProductionT(
            T_opencvCam_colmap: T_opencvCam_colmap,
            sim3: sim3,
            T_ARWorld_arkitCam: T_ARWorld_arkitCam
        )
        assertAlmostEqual(actualT, expectedT, accuracy: se3Tol)

        var actualPoints: [[Double]] = []
        for p in points {
            let actual = try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                wallPointMeters: p,
                T_ARWorld_Wall: actualT
            )
            let expected = independentApplySE3(expectedT, p)
            assertAlmostEqual(actual, expected, accuracy: se3Tol)

            let scaled = [frozenScale * p[0], frozenScale * p[1], frozenScale * p[2]]
            let doubleScaled = try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                wallPointMeters: scaled,
                T_ARWorld_Wall: actualT
            )
            XCTAssertGreaterThan(norm(sub(actual, doubleScaled)), 1.0)

            actualPoints.append(actual)
        }
        assertLengthPreservation(before: points, after: actualPoints, accuracy: se3Tol)
    }

    func testRoutePathDoesNotAcceptOrApplySWallColmap() throws {
        let helper = try readHostSource("RockVision/Features/PnP/CoordinateTransforms.swift")
        XCTAssertTrue(helper.contains("static func applyFrozenWallRoutePointToARWorld("))
        XCTAssertTrue(helper.contains("try apply(T_ARWorld_Wall, point: wallPointMeters)"))
        let helperBody = helper.slice(
            after: "static func applyFrozenWallRoutePointToARWorld(",
            before: "static func rowMajor"
        )
        XCTAssertFalse(helperBody.contains("S_wall_colmap"))
        XCTAssertFalse(helperBody.contains("ValidatedSim3"))
        XCTAssertFalse(helperBody.contains("3.19764417024824"))
        XCTAssertFalse(helperBody.contains("productionAlignment"))

        let tests = try readHostSource("RockVisionTests/Gate5BRouteTransformTests.swift")
        XCTAssertTrue(tests.contains("frozenScale * p[0]"))

        let productionJoined = [
            helper,
            try readHostSource("RockVision/Features/PnP/ProductionAlignment.swift"),
            try readHostSource("RockVision/Features/PnP/WallAlignmentDebugGeometry.swift")
        ].joined(separator: "\n")
        XCTAssertFalse(productionJoined.contains("CLLocation"))
        XCTAssertFalse(productionJoined.contains("CLHeading"))
        XCTAssertFalse(productionJoined.contains("CLLocationManager"))
        XCTAssertFalse(productionJoined.contains("CMDeviceMotion"))
    }

    func testNoSecondWallToARWorldTransformOrRouteCorrection() throws {
        let transforms = try readHostSource("RockVision/Features/PnP/CoordinateTransforms.swift")
        XCTAssertTrue(transforms.contains("static func productionAlignment("))
        XCTAssertTrue(transforms.contains("static let T_arkitCam_opencvCam"))
        XCTAssertEqual(
            CoordinateTransforms.T_arkitCam_opencvCam[1][1],
            -1,
            accuracy: 0
        )
        XCTAssertEqual(
            CoordinateTransforms.T_arkitCam_opencvCam[2][2],
            -1,
            accuracy: 0
        )

        let alignment = try readHostSource("RockVision/Features/PnP/ProductionAlignment.swift")
        XCTAssertTrue(alignment.contains("CoordinateTransforms.productionAlignment"))
        XCTAssertTrue(alignment.contains("renderedRoute: false"))

        let debugGeom = try readHostSource("RockVision/Features/PnP/WallAlignmentDebugGeometry.swift")
        XCTAssertFalse(debugGeom.contains("route_test_01"))
        XCTAssertFalse(debugGeom.contains("applyFrozenWallRoutePointToARWorld"))

        XCTAssertFalse(transforms.contains("enum RouteAlignment"))
        XCTAssertFalse(transforms.contains("RouteCorrection"))
        XCTAssertFalse(transforms.contains("RouteScale"))
        XCTAssertFalse(transforms.contains("DXFTransform"))
    }

    // MARK: - Load frozen Gate 5A input

    private struct IngestedRoute: Decodable {
        var schemaVersion: String
        var kind: String
        var routeId: String
        var wallId: String
        var coordinateFrame: String
        var provenance: String
        var dummyOriginExcluded: Bool
        var pointCount: Int
        var polyline: [[Double]]
        var polylineSha256: String
    }

    private struct PassClosure: Decodable {
        var ingestedPolylineSha256: String
        var FIRST_ROUTE_FROZEN: Bool
        var FIRST_ROUTE_ID: String
        var GATE_5A_PASS: Bool
        var gate5AStatus: String
    }

    private func loadIngested() throws -> IngestedRoute {
        let url = repoRoot().appendingPathComponent(
            "validation/gate5a/gate5a_ingested_route_test_01.json"
        )
        return try JSONDecoder().decode(IngestedRoute.self, from: Data(contentsOf: url))
    }

    private func loadClosure() throws -> PassClosure {
        let url = repoRoot().appendingPathComponent(
            "validation/gate5a/gate5a_pass_closure_route_test_01.json"
        )
        return try JSONDecoder().decode(PassClosure.self, from: Data(contentsOf: url))
    }

    private func repoRoot() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
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

    // MARK: - Frozen hash (binary64 little-endian)

    private func canonicalBinary64Bytes(_ points: [[Double]]) throws -> Data {
        var data = Data()
        data.reserveCapacity(264)
        for point in points {
            XCTAssertEqual(point.count, 3)
            for coord in point {
                var bits = coord.bitPattern.littleEndian
                withUnsafeBytes(of: &bits) { data.append(contentsOf: $0) }
            }
        }
        return data
    }

    private func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    // MARK: - Independent oracle (does not call apply / Homogeneous / route helper)

    private func identitySE3() -> [[Double]] {
        [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ]
    }

    private func yaw(_ degrees: Double) -> [[Double]] {
        let r = degrees * .pi / 180.0
        let c = cos(r)
        let s = sin(r)
        return [
            [c, 0, s],
            [0, 1, 0],
            [-s, 0, c]
        ]
    }

    private func se3(rotation r: [[Double]], translation t: [Double]) -> [[Double]] {
        [
            [r[0][0], r[0][1], r[0][2], t[0]],
            [r[1][0], r[1][1], r[1][2], t[1]],
            [r[2][0], r[2][1], r[2][2], t[2]],
            [0, 0, 0, 1]
        ]
    }

    private func independentRotate(_ r: [[Double]], _ p: [Double]) -> [Double] {
        [
            r[0][0] * p[0] + r[0][1] * p[1] + r[0][2] * p[2],
            r[1][0] * p[0] + r[1][1] * p[1] + r[1][2] * p[2],
            r[2][0] * p[0] + r[2][1] * p[1] + r[2][2] * p[2]
        ]
    }

    private func independentApply(rotation r: [[Double]], translation t: [Double], point p: [Double]) -> [Double] {
        let rp = independentRotate(r, p)
        return [rp[0] + t[0], rp[1] + t[1], rp[2] + t[2]]
    }

    private func independentApplySE3(_ t: [[Double]], _ p: [Double]) -> [Double] {
        independentApply(
            rotation: [
                [t[0][0], t[0][1], t[0][2]],
                [t[1][0], t[1][1], t[1][2]],
                [t[2][0], t[2][1], t[2][2]]
            ],
            translation: [t[0][3], t[1][3], t[2][3]],
            point: p
        )
    }

    private func independentMultiply4x4(_ a: [[Double]], _ b: [[Double]]) -> [[Double]] {
        var c = Array(repeating: Array(repeating: 0.0, count: 4), count: 4)
        for i in 0..<4 {
            for j in 0..<4 {
                c[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j]
                    + a[i][2] * b[2][j] + a[i][3] * b[3][j]
            }
        }
        return c
    }

    private func independentMultiply3x3(_ a: [[Double]], _ b: [[Double]]) -> [[Double]] {
        var c = Array(repeating: Array(repeating: 0.0, count: 3), count: 3)
        for i in 0..<3 {
            for j in 0..<3 {
                c[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j]
            }
        }
        return c
    }

    private func independentMultiply3x3vec(_ r: [[Double]], _ v: [Double]) -> [Double] {
        [
            r[0][0] * v[0] + r[0][1] * v[1] + r[0][2] * v[2],
            r[1][0] * v[0] + r[1][1] * v[1] + r[1][2] * v[2],
            r[2][0] * v[0] + r[2][1] * v[1] + r[2][2] * v[2]
        ]
    }

    private func independentTranspose3x3(_ r: [[Double]]) -> [[Double]] {
        [
            [r[0][0], r[1][0], r[2][0]],
            [r[0][1], r[1][1], r[2][1]],
            [r[0][2], r[1][2], r[2][2]]
        ]
    }

    /// Independent reconstruction of the frozen production chain.
    /// Does not call `productionAlignment`, `apply`, `Homogeneous`, or the route helper.
    private func independentProductionT(
        T_opencvCam_colmap: [[Double]],
        sim3: ValidatedSim3,
        T_ARWorld_arkitCam: [[Double]]
    ) -> [[Double]] {
        let R_p = [
            [T_opencvCam_colmap[0][0], T_opencvCam_colmap[0][1], T_opencvCam_colmap[0][2]],
            [T_opencvCam_colmap[1][0], T_opencvCam_colmap[1][1], T_opencvCam_colmap[1][2]],
            [T_opencvCam_colmap[2][0], T_opencvCam_colmap[2][1], T_opencvCam_colmap[2][2]]
        ]
        let t_p = [T_opencvCam_colmap[0][3], T_opencvCam_colmap[1][3], T_opencvCam_colmap[2][3]]
        let R_sT = independentTranspose3x3(sim3.rotationMatrix)
        let R_cam_wall = independentMultiply3x3(R_p, R_sT)
        let RsT_ts = independentMultiply3x3vec(R_sT, sim3.translationMeters)
        let Rp_RsT_ts = independentMultiply3x3vec(R_p, RsT_ts)
        let s = sim3.scale
        let t_cam_wall = [
            s * t_p[0] - Rp_RsT_ts[0],
            s * t_p[1] - Rp_RsT_ts[1],
            s * t_p[2] - Rp_RsT_ts[2]
        ]
        let T_opencvCamMeters_wall = se3(rotation: R_cam_wall, translation: t_cam_wall)
        let T_arkitCam_opencvCam: [[Double]] = [
            [1, 0, 0, 0],
            [0, -1, 0, 0],
            [0, 0, -1, 0],
            [0, 0, 0, 1]
        ]
        return independentMultiply4x4(
            independentMultiply4x4(T_ARWorld_arkitCam, T_arkitCam_opencvCam),
            T_opencvCamMeters_wall
        )
    }

    private func assertLengthPreservation(
        before: [[Double]],
        after: [[Double]],
        accuracy: Double,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(before.count, 11, file: file, line: line)
        XCTAssertEqual(after.count, 11, file: file, line: line)
        var beforeTotal = 0.0
        var afterTotal = 0.0
        for i in 0..<10 {
            let dBefore = norm(sub(before[i + 1], before[i]))
            let dAfter = norm(sub(after[i + 1], after[i]))
            XCTAssertEqual(dAfter, dBefore, accuracy: accuracy, file: file, line: line)
            beforeTotal += dBefore
            afterTotal += dAfter
        }
        XCTAssertEqual(afterTotal, beforeTotal, accuracy: accuracy, file: file, line: line)
    }

    private func assertAlmostEqual(
        _ a: [Double],
        _ b: [Double],
        accuracy: Double,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(a.count, 3, file: file, line: line)
        XCTAssertEqual(b.count, 3, file: file, line: line)
        XCTAssertEqual(a[0], b[0], accuracy: accuracy, file: file, line: line)
        XCTAssertEqual(a[1], b[1], accuracy: accuracy, file: file, line: line)
        XCTAssertEqual(a[2], b[2], accuracy: accuracy, file: file, line: line)
    }

    private func assertAlmostEqual(
        _ a: [[Double]],
        _ b: [[Double]],
        accuracy: Double,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(a.count, 4, file: file, line: line)
        XCTAssertEqual(b.count, 4, file: file, line: line)
        for r in 0..<4 {
            for c in 0..<4 {
                XCTAssertEqual(a[r][c], b[r][c], accuracy: accuracy, file: file, line: line)
            }
        }
    }

    private func sub(_ a: [Double], _ b: [Double]) -> [Double] {
        [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
    }

    private func add(_ a: [Double], _ b: [Double]) -> [Double] {
        [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
    }

    private func norm(_ v: [Double]) -> Double {
        sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    }
}

private extension String {
    func slice(after: String, before: String) -> String {
        guard let start = range(of: after)?.upperBound,
              let end = range(of: before, range: start..<self.endIndex)?.lowerBound
        else { return self }
        return String(self[start..<end])
    }
}
