import XCTest
@testable import RockVision

final class CoordinateTransformsTests: XCTestCase {
    func testOpenCVCameraToARKitCameraIsUniqueProperRotation() throws {
        let t = CoordinateTransforms.openCVCameraToARKitCamera()
        XCTAssertEqual(t, CoordinateTransforms.T_arkitCam_opencvCam)
        XCTAssertEqual(t[0], [1, 0, 0, 0])
        XCTAssertEqual(t[1], [0, -1, 0, 0])
        XCTAssertEqual(t[2], [0, 0, -1, 0])
        XCTAssertEqual(t[3], [0, 0, 0, 1])
        let det = t[0][0] * (t[1][1] * t[2][2] - t[1][2] * t[2][1])
            - t[0][1] * (t[1][0] * t[2][2] - t[1][2] * t[2][0])
            + t[0][2] * (t[1][0] * t[2][1] - t[1][1] * t[2][0])
        XCTAssertEqual(det, 1.0, accuracy: 1e-12)

        let down = try CoordinateTransforms.apply(t, point: [0, 1, 0])
        XCTAssertEqual(down[0], 0, accuracy: 1e-12)
        XCTAssertEqual(down[1], -1, accuracy: 1e-12)
        XCTAssertEqual(down[2], 0, accuracy: 1e-12)
        let forward = try CoordinateTransforms.apply(t, point: [0, 0, 1])
        XCTAssertEqual(forward[0], 0, accuracy: 1e-12)
        XCTAssertEqual(forward[1], 0, accuracy: 1e-12)
        XCTAssertEqual(forward[2], -1, accuracy: 1e-12)
    }

    func testInverseSim3RemainsPointMapInverseWithScale() throws {
        let sim3 = syntheticSim3(scale: 2.5, yawDeg: 35, translation: [1.5, -2.0, 4.0])
        let inv = try CoordinateTransforms.inverseSim3(sim3)
        XCTAssertEqual(inv[0][0], cos(35 * .pi / 180.0) / 2.5, accuracy: 1e-12)
        let xWall = [3.0, -1.0, 2.0]
        let xColmap = try CoordinateTransforms.apply(inv, point: xWall)
        let roundTrip = try XCTUnwrap(sim3.apply(xColmap))
        XCTAssertEqual(roundTrip[0], xWall[0], accuracy: 1e-9)
        XCTAssertEqual(roundTrip[1], xWall[1], accuracy: 1e-9)
        XCTAssertEqual(roundTrip[2], xWall[2], accuracy: 1e-9)

        let source = try readHostSource("RockVision/Features/PnP/CoordinateTransforms.swift")
        XCTAssertTrue(source.contains("rt00 = r[0][0] / s"))
        XCTAssertFalse(source.contains("multiply(T_opencvCam_colmap, inverseSim3"))
    }

    func testProductionAlignmentIsMetricSE3() throws {
        let sim3 = syntheticSim3(scale: 2.5, yawDeg: 35, translation: [1.5, -2.0, 4.0])
        let T_pnp = se3(yawDeg: 18, translation: [0.40, -0.25, 5.50])
        let T_world = se3(yawDeg: -12, translation: [8.0, 1.0, -3.0])
        let actual = try CoordinateTransforms.productionAlignment(
            T_opencvCam_colmap: T_pnp,
            S_wall_colmap: sim3,
            T_ARWorld_arkitCam: T_world
        )
        assertOneMeterAxes(actual)
        XCTAssertEqual(rotationDeterminant(actual), 1.0, accuracy: 1e-9)
        XCTAssertGreaterThan(rotationDeterminant(actual), 0)

        let origin = try CoordinateTransforms.apply(actual, point: [0, 0, 0])
        let xEnd = try CoordinateTransforms.apply(actual, point: [1, 0, 0])
        let yEnd = try CoordinateTransforms.apply(actual, point: [0, 1, 0])
        let zEnd = try CoordinateTransforms.apply(actual, point: [0, 0, 1])
        XCTAssertEqual(dot(sub(xEnd, origin), sub(yEnd, origin)), 0, accuracy: 1e-9)
        XCTAssertEqual(dot(sub(xEnd, origin), sub(zEnd, origin)), 0, accuracy: 1e-9)
        XCTAssertEqual(dot(sub(yEnd, origin), sub(zEnd, origin)), 0, accuracy: 1e-9)

        let T_old = try oldFormula(
            T_opencvCam_colmap: T_pnp,
            sim3: sim3,
            T_ARWorld_arkitCam: T_world
        )
        XCTAssertFalse(almostEqual(actual, T_old))

        let xColmap = [1.2, -0.4, 0.8]
        let xWall = try XCTUnwrap(sim3.apply(xColmap))
        let camRecon = try CoordinateTransforms.apply(T_pnp, point: xColmap)
        let camMetersExpected = camRecon.map { $0 * sim3.scale }
        let T_left = try CoordinateTransforms.multiply(T_world, CoordinateTransforms.T_arkitCam_opencvCam)
        let T_cam = try CoordinateTransforms.multiply(invertSE3(T_left), actual)
        let camMeters = try CoordinateTransforms.apply(T_cam, point: xWall)
        XCTAssertEqual(camMeters[0], camMetersExpected[0], accuracy: 1e-9)
        XCTAssertEqual(camMeters[1], camMetersExpected[1], accuracy: 1e-9)
        XCTAssertEqual(camMeters[2], camMetersExpected[2], accuracy: 1e-9)
    }

    func testOldFormulaNegativeScaleDefect() throws {
        let sim3 = try XCTUnwrap(loadSim3())
        XCTAssertEqual(sim3.scale, 3.19764417024824, accuracy: 1e-12)
        let T_pnp = se3(yawDeg: 22, translation: [0.31, 0.22, 6.05])
        let T_world = se3(yawDeg: 8, translation: [0.5, 1.5, 2.5])
        let T_old = try oldFormula(
            T_opencvCam_colmap: T_pnp,
            sim3: sim3,
            T_ARWorld_arkitCam: T_world
        )
        let expectedLen = 1.0 / sim3.scale
        let origin = try CoordinateTransforms.apply(T_old, point: [0, 0, 0])
        let xEnd = try CoordinateTransforms.apply(T_old, point: [1, 0, 0])
        let yEnd = try CoordinateTransforms.apply(T_old, point: [0, 1, 0])
        let zEnd = try CoordinateTransforms.apply(T_old, point: [0, 0, 1])
        XCTAssertEqual(norm(sub(xEnd, origin)), expectedLen, accuracy: 1e-9)
        XCTAssertEqual(norm(sub(yEnd, origin)), expectedLen, accuracy: 1e-9)
        XCTAssertEqual(norm(sub(zEnd, origin)), expectedLen, accuracy: 1e-9)
        XCTAssertEqual(rotationDeterminant(T_old), expectedLen * expectedLen * expectedLen, accuracy: 1e-9)

        let production = try CoordinateTransforms.productionAlignment(
            T_opencvCam_colmap: T_pnp,
            S_wall_colmap: sim3,
            T_ARWorld_arkitCam: T_world
        )
        XCTAssertFalse(almostEqual(production, T_old))
        assertOneMeterAxes(production)
        XCTAssertEqual(rotationDeterminant(production), 1.0, accuracy: 1e-9)
    }

    func testCameraCenterClosureMatchesFrozenCWall() throws {
        let sim3 = try XCTUnwrap(loadSim3())
        let R_p = yaw(25)
        let t_p = [0.40, -0.15, 5.80]
        let T_pnp = [
            [R_p[0][0], R_p[0][1], R_p[0][2], t_p[0]],
            [R_p[1][0], R_p[1][1], R_p[1][2], t_p[1]],
            [R_p[2][0], R_p[2][1], R_p[2][2], t_p[2]],
            [0, 0, 0, 1]
        ]
        let T_world = se3(yawDeg: -7, translation: [4.0, -1.0, 9.0])
        let T = try CoordinateTransforms.productionAlignment(
            T_opencvCam_colmap: T_pnp,
            S_wall_colmap: sim3,
            T_ARWorld_arkitCam: T_world
        )
        let T_left = try CoordinateTransforms.multiply(T_world, CoordinateTransforms.T_arkitCam_opencvCam)
        let T_cam = try CoordinateTransforms.multiply(invertSE3(T_left), T)
        let R_cam = [
            [T_cam[0][0], T_cam[0][1], T_cam[0][2]],
            [T_cam[1][0], T_cam[1][1], T_cam[1][2]],
            [T_cam[2][0], T_cam[2][1], T_cam[2][2]]
        ]
        let t_cam = [T_cam[0][3], T_cam[1][3], T_cam[2][3]]
        let C_from_T = PnPGeometry.cameraCenter(rotationRowMajor3x3: R_cam, t: t_cam)

        let C_colmap = PnPGeometry.cameraCenter(rotationRowMajor3x3: R_p, t: t_p)
        let C_wall = try XCTUnwrap(sim3.apply(C_colmap))
        XCTAssertEqual(C_from_T[0], C_wall[0], accuracy: 1e-9)
        XCTAssertEqual(C_from_T[1], C_wall[1], accuracy: 1e-9)
        XCTAssertEqual(C_from_T[2], C_wall[2], accuracy: 1e-9)

        let s_tp = [sim3.scale * t_p[0], sim3.scale * t_p[1], sim3.scale * t_p[2]]
        XCTAssertEqual(t_cam[0] + (R_cam[0][0] * C_from_T[0] + R_cam[0][1] * C_from_T[1] + R_cam[0][2] * C_from_T[2]), 0, accuracy: 1e-9)
        XCTAssertNotEqual(s_tp[2], t_p[2], accuracy: 0.5)
    }

    func testRealSim3ScaleKeepsOneMeterAndDetPlusOne() throws {
        let sim3 = try XCTUnwrap(loadSim3())
        XCTAssertEqual(sim3.scale, 3.19764417024824, accuracy: 1e-12)
        let T = try CoordinateTransforms.productionAlignment(
            T_opencvCam_colmap: se3(yawDeg: 11, translation: [0.10, 0.20, 6.00]),
            S_wall_colmap: sim3,
            T_ARWorld_arkitCam: se3(yawDeg: 4, translation: [0.5, 1.5, 2.5])
        )
        assertOneMeterAxes(T)
        XCTAssertEqual(rotationDeterminant(T), 1.0, accuracy: 1e-9)
        XCTAssertNotEqual(axisLength(T, axis: [1, 0, 0]), 1.0 / sim3.scale, accuracy: 0.05)
        XCTAssertNotEqual(rotationDeterminant(T), pow(1.0 / sim3.scale, 3), accuracy: 0.001)
    }

    func testValidatedResourceSim3HasNoIdentityFallback() throws {
        let sim3 = try XCTUnwrap(loadSim3())
        XCTAssertEqual(sim3.status, "VALIDATED")
        XCTAssertEqual(sim3.scale, 3.19764417024824, accuracy: 1e-12)

        XCTAssertThrowsError(
            try CoordinateTransforms.productionAlignment(
                T_opencvCam_colmap: Homogeneous.multiply(
                    [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                    [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
                ),
                S_wall_colmap: nil,
                T_ARWorld_arkitCam: [
                    [1, 0, 0, 0],
                    [0, 1, 0, 0],
                    [0, 0, 1, 0],
                    [0, 0, 0, 1]
                ]
            )
        ) { error in
            XCTAssertEqual(error as? CoordinateTransformError, .sim3Unavailable)
        }

        var undefined = sim3
        undefined.status = "undefined"
        XCTAssertThrowsError(
            try CoordinateTransforms.productionAlignment(
                T_opencvCam_colmap: [
                    [1, 0, 0, 0],
                    [0, 1, 0, 0],
                    [0, 0, 1, 0],
                    [0, 0, 0, 1]
                ],
                S_wall_colmap: undefined,
                T_ARWorld_arkitCam: [
                    [1, 0, 0, 0],
                    [0, 1, 0, 0],
                    [0, 0, 1, 0],
                    [0, 0, 0, 1]
                ]
            )
        ) { error in
            XCTAssertEqual(error as? CoordinateTransformError, .sim3Unavailable)
        }

        let aligned = try CoordinateTransforms.productionAlignment(
            T_opencvCam_colmap: [
                [1, 0, 0, 0.4],
                [0, 1, 0, 0.2],
                [0, 0, 1, 6.0],
                [0, 0, 0, 1]
            ],
            S_wall_colmap: sim3,
            T_ARWorld_arkitCam: [
                [1, 0, 0, 1],
                [0, 1, 0, 2],
                [0, 0, 1, 3],
                [0, 0, 0, 1]
            ]
        )
        XCTAssertNotEqual(aligned, [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ])
    }

    func testColumnMajorARKitConvertIsTransposeOfColumns() throws {
        let columns: [[Double]] = [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [4, 5, 6, 1]
        ]
        let rowMajor = try CoordinateTransforms.rowMajor(fromColumnMajor: columns)
        XCTAssertEqual(rowMajor[0][3], 4, accuracy: 1e-12)
        XCTAssertEqual(rowMajor[1][3], 5, accuracy: 1e-12)
        XCTAssertEqual(rowMajor[2][3], 6, accuracy: 1e-12)
        XCTAssertEqual(rowMajor[3], [0, 0, 0, 1])
    }

    func testUniqueHomeForCameraBasisChange() throws {
        let transforms = try readHostSource("RockVision/Features/PnP/CoordinateTransforms.swift")
        XCTAssertTrue(transforms.contains("static let T_arkitCam_opencvCam"))
        XCTAssertTrue(transforms.contains("static func productionAlignment("))
        XCTAssertTrue(transforms.contains("opencvCamMetersWallTransform"))
        XCTAssertTrue(transforms.contains("T_opencvCamMeters_wall"))
        XCTAssertTrue(transforms.contains("private static func opencvCamMetersWallTransform"))
        XCTAssertFalse(transforms.contains("multiply(T_opencvCam_colmap, inverseSim3"))
        XCTAssertTrue(transforms.contains("T_arkitCam_opencvCam"))
        XCTAssertTrue(transforms.contains("inverseSim3"))

        let alignment = try readHostSource("RockVision/Features/PnP/ProductionAlignment.swift")
        XCTAssertTrue(alignment.contains("CoordinateTransforms.productionAlignment"))
        XCTAssertFalse(alignment.contains("opencvCamMetersWallTransform"))
        XCTAssertFalse(alignment.contains("T_arkitCam_opencvCam"))
        XCTAssertFalse(alignment.contains("y = -y"))
        XCTAssertFalse(alignment.contains("z = -z"))

        let processor = try readHostSource("RockVision/Features/OpenCV/OpenCVFrameProcessor.swift")
        XCTAssertFalse(processor.contains("T_arkitCam_opencvCam"))
        XCTAssertFalse(processor.contains("T_ARWorld_Wall ="))
        XCTAssertFalse(processor.contains("opencvCamMetersWallTransform"))
        XCTAssertFalse(processor.contains("y = -y"))
        XCTAssertFalse(processor.contains("z = -z"))
    }

    private func syntheticSim3(scale: Double, yawDeg: Double, translation: [Double]) -> ValidatedSim3 {
        ValidatedSim3(
            name: "S_wall_colmap",
            status: "VALIDATED",
            convention: "X_wall = s * R * X_colmap + t",
            scale: scale,
            rotationMatrix: yaw(yawDeg),
            translationMeters: translation
        )
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

    private func se3(yawDeg: Double, translation: [Double]) -> [[Double]] {
        let R = yaw(yawDeg)
        return [
            [R[0][0], R[0][1], R[0][2], translation[0]],
            [R[1][0], R[1][1], R[1][2], translation[1]],
            [R[2][0], R[2][1], R[2][2], translation[2]],
            [0, 0, 0, 1]
        ]
    }

    private func oldFormula(
        T_opencvCam_colmap: [[Double]],
        sim3: ValidatedSim3,
        T_ARWorld_arkitCam: [[Double]]
    ) throws -> [[Double]] {
        let sInv = try CoordinateTransforms.inverseSim3(sim3)
        let T_wrong = try CoordinateTransforms.multiply(T_opencvCam_colmap, sInv)
        return try CoordinateTransforms.multiply(
            try CoordinateTransforms.multiply(T_ARWorld_arkitCam, CoordinateTransforms.T_arkitCam_opencvCam),
            T_wrong
        )
    }

    private func invertSE3(_ t: [[Double]]) -> [[Double]] {
        let rt00 = t[0][0], rt01 = t[1][0], rt02 = t[2][0]
        let rt10 = t[0][1], rt11 = t[1][1], rt12 = t[2][1]
        let rt20 = t[0][2], rt21 = t[1][2], rt22 = t[2][2]
        let tx = t[0][3], ty = t[1][3], tz = t[2][3]
        return [
            [rt00, rt01, rt02, -(rt00 * tx + rt01 * ty + rt02 * tz)],
            [rt10, rt11, rt12, -(rt10 * tx + rt11 * ty + rt12 * tz)],
            [rt20, rt21, rt22, -(rt20 * tx + rt21 * ty + rt22 * tz)],
            [0, 0, 0, 1]
        ]
    }

    private func rotationDeterminant(_ t: [[Double]]) -> Double {
        let a = t[0][0], b = t[0][1], c = t[0][2]
        let d = t[1][0], e = t[1][1], f = t[1][2]
        let g = t[2][0], h = t[2][1], i = t[2][2]
        return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    }

    private func sub(_ a: [Double], _ b: [Double]) -> [Double] {
        [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
    }

    private func norm(_ v: [Double]) -> Double {
        sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    }

    private func dot(_ a: [Double], _ b: [Double]) -> Double {
        a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    }

    private func axisLength(_ t: [[Double]], axis: [Double]) -> Double {
        let origin = Homogeneous.apply(t, point: [0, 0, 0])
        let end = Homogeneous.apply(t, point: axis)
        return norm(sub(end, origin))
    }

    private func assertOneMeterAxes(_ t: [[Double]], file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(axisLength(t, axis: [1, 0, 0]), 1.0, accuracy: 1e-9, file: file, line: line)
        XCTAssertEqual(axisLength(t, axis: [0, 1, 0]), 1.0, accuracy: 1e-9, file: file, line: line)
        XCTAssertEqual(axisLength(t, axis: [0, 0, 1]), 1.0, accuracy: 1e-9, file: file, line: line)
    }

    private func almostEqual(_ a: [[Double]], _ b: [[Double]]) -> Bool {
        guard a.count == 4, b.count == 4 else { return false }
        for r in 0..<4 {
            for c in 0..<4 {
                if abs(a[r][c] - b[r][c]) > 1e-9 { return false }
            }
        }
        return true
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

    private func assertAlmostEqual(_ a: [[Double]], _ b: [[Double]], file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(a.count, 4, file: file, line: line)
        XCTAssertEqual(b.count, 4, file: file, line: line)
        for r in 0..<4 {
            for c in 0..<4 {
                XCTAssertEqual(a[r][c], b[r][c], accuracy: 1e-9, file: file, line: line)
            }
        }
    }
}
