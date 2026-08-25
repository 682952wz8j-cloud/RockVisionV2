import XCTest
@testable import RockVision

final class PnPParityTests: XCTestCase {
    func testSyntheticMacIOSConventionParity() throws {
        let image = try projectNative()
        let rows = zip(PnPSyntheticFixture.objectPoints, image).enumerated().map { i, pair in
            PnPCorrespondence(
                queryIndex: i,
                queryXYNative: pair.1,
                point3DID: Int64(i + 1),
                referenceRow: i,
                colmapXYZ: pair.0,
                ratio: 0.4,
                descriptorDistance: 0.2,
                queryCoordinateSpace: PnPConfig.queryCoordinateSpace
            )
        }
        let result = RuntimePnP.evaluate(
            correspondences: rows,
            uniquePoint3DCount: rows.count,
            xyzMissingRejected: 0,
            camera: nativeCamera(fx: PnPSyntheticFixture.fx, fy: PnPSyntheticFixture.fy, cx: PnPSyntheticFixture.cx, cy: PnPSyntheticFixture.cy, matrix: PnPSyntheticFixture.cameraMatrix),
            sim3: loadSim3()
        )
        XCTAssertTrue(result.ransacSuccess)
        XCTAssertTrue(result.refineOk)
        XCTAssertTrue(result.candidateQualified)
        XCTAssertEqual(result.localizationState, "idle")
        let gtR = try XCTUnwrap(OpenCVBridge.rodriguesRotation(fromRvec: PnPSyntheticFixture.rvec.map { NSNumber(value: $0) }))
        let Rgt = gtR.rotationMatrix.map { $0.map(\.doubleValue) }
        let Cgt = PnPGeometry.cameraCenter(rotationRowMajor3x3: Rgt, t: PnPSyntheticFixture.tvec)
        let R = try XCTUnwrap(result.rotationMatrix)
        let C = try XCTUnwrap(result.C_colmap)
        let rotationDeg = PnPGeometry.rotationAngleDegrees(estimated: R, groundTruth: Rgt)
        let centerErr = PnPGeometry.l2(C, Cgt)
        print("SYNTHETIC_PARITY rotationDeg=\(rotationDeg) C_colmapDiff=\(centerErr) reprojMed=\(result.reprojectionRefined?.median ?? -1) inliers=\(result.inlierCount)")
        XCTAssertLessThan(rotationDeg, 0.05)
        XCTAssertLessThan(centerErr, 1e-3)
        XCTAssertLessThan(try XCTUnwrap(result.reprojectionRefined?.median), 0.05)
        XCTAssertEqual(try XCTUnwrap(result.positiveDepthRatioRefined), 1.0, accuracy: 1e-12)
        XCTAssertTrue(result.opencvVersion.hasPrefix("4.14"))
    }

    func testRealSceneAMacIOSParity() throws {
        let fixture = try loadSceneA()
        XCTAssertEqual(fixture.inputCorrespondenceCount, 725)
        XCTAssertGreaterThan(fixture.objectPoints.count, MatchingConfig.diagnosticMatchCap)
        XCTAssertEqual(fixture.objectPoints.count, fixture.imagePoints.count)
        XCTAssertEqual(fixture.queryCoordinateSpace, "nativeCapturedImage")

        let rows = zip(fixture.objectPoints, fixture.imagePoints).enumerated().map { i, pair in
            PnPCorrespondence(
                queryIndex: i,
                queryXYNative: pair.1,
                point3DID: Int64(i + 1),
                referenceRow: i,
                colmapXYZ: pair.0,
                ratio: 0.4,
                descriptorDistance: 0.2,
                queryCoordinateSpace: fixture.queryCoordinateSpace
            )
        }
        let camera = nativeCamera(fx: fixture.fx, fy: fixture.fy, cx: fixture.cx, cy: fixture.cy, matrix: fixture.cameraMatrix)
        XCTAssertTrue(camera.pnpIntrinsicsReady)
        let sim3 = try XCTUnwrap(loadSim3())
        let ios = RuntimePnP.evaluate(
            correspondences: rows,
            uniquePoint3DCount: rows.count,
            xyzMissingRejected: 0,
            camera: camera,
            sim3: sim3,
            frameID: UInt64(fixture.frameID)
        )
        let mac = try loadExpected()

        XCTAssertTrue(ios.ransacSuccess)
        XCTAssertTrue(mac.ransacSuccess)
        XCTAssertTrue(ios.refineOk)
        XCTAssertTrue(mac.refineOk)
        XCTAssertTrue(ios.candidateQualified)
        XCTAssertEqual(ios.inputCorrespondenceCount, 725)
        XCTAssertEqual(ios.inputCorrespondenceCount, mac.inputCorrespondenceCount)
        XCTAssertEqual(ios.inlierRatio, Double(ios.inlierCount) / Double(ios.inputCorrespondenceCount), accuracy: 1e-12)

        let inlierDelta = abs(ios.inlierCount - mac.inlierCount)
        XCTAssertLessThan(inlierDelta, 150, "inlier count should be the same magnitude")
        XCTAssertLessThan(abs(ios.inlierRatio - mac.inlierRatio), 0.15)

        let iosReproj = try XCTUnwrap(ios.reprojectionRefined?.median)
        XCTAssertLessThan(abs(iosReproj - mac.reprojectionRefinedMedian), 2.0)
        XCTAssertLessThan(iosReproj, 8.0)

        let Rios = try XCTUnwrap(ios.rotationMatrix)
        let rotationDeg = PnPGeometry.rotationAngleDegrees(estimated: Rios, groundTruth: mac.rotationMatrix)
        XCTAssertLessThan(rotationDeg, 1.0, "rotation difference must be far below 1°")

        let Cios = try XCTUnwrap(ios.C_colmap)
        let colmapDiff = PnPGeometry.l2(Cios, mac.C_colmap)
        XCTAssertLessThan(colmapDiff, 0.313, "C_colmap difference must be far below 1 m / 3.1976 reconstruction units")
        XCTAssertEqual(ios.C_colmapUnits, "colmapReconstruction")

        let Wallios = try XCTUnwrap(ios.C_wall)
        let wallDiff = PnPGeometry.l2(Wallios, mac.C_wall)
        XCTAssertLessThan(wallDiff, 1.0, "C_wall difference must be far below 1 m")
        XCTAssertEqual(ios.C_wallUnits, "meters")

        let cam = try XCTUnwrap(ios.medianInlierDepthCam)
        let meters = try XCTUnwrap(ios.medianInlierDepthMeters)
        print(
            "SCENE_A_PARITY iosInliers=\(ios.inlierCount) macInliers=\(mac.inlierCount) iosRatio=\(ios.inlierRatio) macRatio=\(mac.inlierRatio) iosReproj=\(iosReproj) macReproj=\(mac.reprojectionRefinedMedian) rotDeg=\(rotationDeg) C_colmapDiff=\(colmapDiff) C_wallDiff=\(wallDiff) cam=\(cam) meters=\(meters) macCam=\(mac.medianInlierDepthCam) macMeters=\(mac.medianInlierDepthMeters)"
        )
        XCTAssertEqual(meters, cam * sim3.scale, accuracy: 1e-6)
        XCTAssertEqual(ios.medianInlierDepthCamUnits, "colmapReconstruction")
        XCTAssertEqual(ios.medianInlierDepthMetersUnits, "meters")
        XCTAssertLessThan(abs(cam - mac.medianInlierDepthCam), 0.2)
        XCTAssertLessThan(abs(meters - mac.medianInlierDepthMeters), 0.7)
        XCTAssertEqual(try XCTUnwrap(ios.positiveDepthRatioRefined), 1.0, accuracy: 1e-6)
        XCTAssertEqual(ios.localizationState, "idle")
        XCTAssertNotEqual(try XCTUnwrap(ios.tvecRefined), Cios)
        XCTAssertFalse(ios.observationDepthNote.lowercased().contains("walldistance"))
    }

    private struct SceneAFile: Codable {
        var frameID: Int
        var queryCoordinateSpace: String
        var fx: Double
        var fy: Double
        var cx: Double
        var cy: Double
        var cameraMatrix: [[Double]]
        var inputCorrespondenceCount: Int
        var objectPoints: [[Double]]
        var imagePoints: [[Double]]
    }

    private struct SceneAExpected: Codable {
        var inputCorrespondenceCount: Int
        var ransacSuccess: Bool
        var refineOk: Bool
        var inlierCount: Int
        var inlierRatio: Double
        var reprojectionRefinedMedian: Double
        var positiveDepthRatio: Double
        var medianInlierDepthCam: Double
        var medianInlierDepthMeters: Double
        var C_colmap: [Double]
        var C_wall: [Double]
        var rotationMatrix: [[Double]]
        var sim3Scale: Double
    }

    private func loadSceneA() throws -> SceneAFile {
        try JSONDecoder().decode(SceneAFile.self, from: try data(resource: "PnPSceneAParity"))
    }

    private func loadExpected() throws -> SceneAExpected {
        try JSONDecoder().decode(SceneAExpected.self, from: try data(resource: "PnPSceneAParityExpected"))
    }

    private func data(resource: String) throws -> Data {
        let bundle = Bundle(for: OpenCVFrameProcessor.self)
        if let url = bundle.url(forResource: resource, withExtension: "json") {
            return try Data(contentsOf: url)
        }
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("RockVision/Resources/\(resource).json")
        return try Data(contentsOf: url)
    }

    private func projectNative() throws -> [[Double]] {
        let projected = OpenCVBridge.projectPoints(
            objectPoints: PnPSyntheticFixture.objectPoints.map { $0.map { NSNumber(value: $0) } },
            rvec: PnPSyntheticFixture.rvec.map { NSNumber(value: $0) },
            tvec: PnPSyntheticFixture.tvec.map { NSNumber(value: $0) },
            cameraMatrix: PnPSyntheticFixture.cameraMatrix.map { $0.map { NSNumber(value: $0) } },
            distCoeffs: PnPSyntheticFixture.distCoeffs.map { NSNumber(value: $0) }
        )
        XCTAssertTrue(projected.ok, projected.error ?? "projectPoints failed")
        return projected.imagePoints.map { $0.map(\.doubleValue) }
    }

    private func nativeCamera(fx: Double, fy: Double, cx: Double, cy: Double, matrix: [[Double]]) -> CameraIntrinsicsSnapshot {
        CameraIntrinsicsSnapshot(
            fx: fx,
            fy: fy,
            cx: cx,
            cy: cy,
            cameraMatrix: matrix,
            referenceWidth: 1920,
            referenceHeight: 1440,
            capturedWidth: 1920,
            capturedHeight: 1440
        )
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
}
