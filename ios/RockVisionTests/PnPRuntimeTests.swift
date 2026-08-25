import simd
import XCTest
@testable import RockVision

final class PnPRuntimeTests: XCTestCase {
    func testInsufficientCorrespondencesDoesNotAttemptPnP() {
        let rows = (0..<3).map { i in correspondence(i, xyz: [Double(i), 0, 1], uv: [100, 100]) }
        let result = RuntimePnP.evaluate(
            correspondences: rows,
            uniquePoint3DCount: 3,
            xyzMissingRejected: 0,
            camera: nativeCamera(),
            sim3: loadSim3()
        )
        XCTAssertEqual(result.status, "insufficientCorrespondences")
        XCTAssertFalse(result.attempted)
        XCTAssertFalse(result.ransacAttempted)
        XCTAssertFalse(result.candidateQualified)
        XCTAssertEqual(result.inputCorrespondenceCount, 3)
        XCTAssertEqual(result.localizationState, "idle")
        XCTAssertNil(result.T_opencvCam_colmap)
    }

    func testPnPUsesFullCorrespondencesNotDiagnosticCap() throws {
        XCTAssertEqual(MatchingConfig.diagnosticMatchCap, 20)
        let image = try projectNative()
        XCTAssertGreaterThan(image.count, MatchingConfig.diagnosticMatchCap)
        let rows = zip(PnPSyntheticFixture.objectPoints, image).enumerated().map { i, pair in
            correspondence(i, xyz: pair.0, uv: pair.1)
        }
        let result = RuntimePnP.evaluate(
            correspondences: rows,
            uniquePoint3DCount: rows.count,
            xyzMissingRejected: 0,
            camera: nativeCamera(),
            sim3: loadSim3()
        )
        XCTAssertEqual(result.inputCorrespondenceCount, rows.count)
        XCTAssertGreaterThan(result.inputCorrespondenceCount, MatchingConfig.diagnosticMatchCap)
        XCTAssertEqual(result.inlierRatio, Double(result.inlierCount) / Double(result.inputCorrespondenceCount), accuracy: 1e-12)
        XCTAssertNotEqual(result.inputCorrespondenceCount, MatchingConfig.diagnosticMatchCap)
    }

    func testObservationDepthMetersIsCamTimesValidatedScale() throws {
        let image = try projectNative()
        let rows = zip(PnPSyntheticFixture.objectPoints, image).enumerated().map { i, pair in
            correspondence(i, xyz: pair.0, uv: pair.1)
        }
        let sim3 = try XCTUnwrap(loadSim3())
        let result = RuntimePnP.evaluate(
            correspondences: rows,
            uniquePoint3DCount: rows.count,
            xyzMissingRejected: 0,
            camera: nativeCamera(),
            sim3: sim3
        )
        XCTAssertTrue(result.candidateQualified)
        XCTAssertEqual(result.localizationState, "idle")
        XCTAssertEqual(result.C_colmapUnits, "colmapReconstruction")
        XCTAssertEqual(result.C_wallUnits, "meters")
        XCTAssertEqual(result.medianInlierDepthCamUnits, "colmapReconstruction")
        XCTAssertEqual(result.medianInlierDepthMetersUnits, "meters")
        XCTAssertEqual(result.observationDepthNote, "observation-depth sanity")
        let cam = try XCTUnwrap(result.medianInlierDepthCam)
        let meters = try XCTUnwrap(result.medianInlierDepthMeters)
        XCTAssertEqual(sim3.scale, PnPConfig.expectedSim3Scale, accuracy: 1e-12)
        XCTAssertEqual(meters, cam * sim3.scale, accuracy: 1e-9)
        XCTAssertNotEqual(meters, cam)
        XCTAssertFalse(result.observationDepthNote.lowercased().contains("walldistance"))
        XCTAssertNotEqual(result.C_wall, result.C_colmap)
        let t = try XCTUnwrap(result.tvecRefined)
        let c = try XCTUnwrap(result.C_colmap)
        XCTAssertGreaterThan(PnPGeometry.l2(t, c), 0.05)
        XCTAssertNotNil(result.T_opencvCam_colmap)
        XCTAssertEqual(result.refineQualityFlag, "ok")
        XCTAssertLessThanOrEqual(try XCTUnwrap(result.refinementDeltaMedian), 0.01)
    }

    func testUnscaledCamDepthMustNotBeWrittenAsMeters() throws {
        let cam = 2.4
        let sim3 = loadSim3()
        let meters = try XCTUnwrap(sim3?.meters(fromCamDepth: cam))
        XCTAssertNotEqual(meters, cam)
        XCTAssertEqual(meters, cam * PnPConfig.expectedSim3Scale, accuracy: 1e-12)
    }

    func testRefineQualityRejectsSilentRANSACFallback() {
        let ransac = PnPReprojectionStats(mean: 2, median: 2, p90: 3, max: 4, count: 10)
        let worse = PnPReprojectionStats(mean: 8, median: 8, p90: 9, max: 10, count: 10)
        let cheirOK = PnPCheiralityStats(positiveDepthCount: 10, inlierCount: 10, positiveDepthRatio: 1, medianInlierDepthCam: 2.4)
        let cheirBad = PnPCheiralityStats(positiveDepthCount: 4, inlierCount: 10, positiveDepthRatio: 0.4, medianInlierDepthCam: 2.4)
        let fail = RefineQuality.assess(
            refineOk: false,
            ransacReproj: ransac,
            refinedReproj: ransac,
            ransacCheir: cheirOK,
            refinedCheir: cheirOK,
            refinedFinite: true
        )
        XCTAssertFalse(fail.ok)
        XCTAssertEqual(fail.flag, "refineFailed")
        let reproj = RefineQuality.assess(
            refineOk: true,
            ransacReproj: ransac,
            refinedReproj: worse,
            ransacCheir: cheirOK,
            refinedCheir: cheirOK,
            refinedFinite: true
        )
        XCTAssertFalse(reproj.ok)
        XCTAssertEqual(reproj.flag, "reprojWorse")
        let cheir = RefineQuality.assess(
            refineOk: true,
            ransacReproj: ransac,
            refinedReproj: ransac,
            ransacCheir: cheirOK,
            refinedCheir: cheirBad,
            refinedFinite: true
        )
        XCTAssertFalse(cheir.ok)
        XCTAssertEqual(cheir.flag, "cheiralityWorse")
        let nan = RefineQuality.assess(
            refineOk: true,
            ransacReproj: ransac,
            refinedReproj: ransac,
            ransacCheir: cheirOK,
            refinedCheir: cheirOK,
            refinedFinite: false
        )
        XCTAssertFalse(nan.ok)
        XCTAssertEqual(nan.flag, "nonFinite")
    }

    func testSkippedIntrinsicsWhenNativeKNotReady() {
        var mismatch = simd_float3x3(0)
        mismatch.columns.0 = SIMD3<Float>(725, 0, 0)
        mismatch.columns.1 = SIMD3<Float>(0, 725, 0)
        mismatch.columns.2 = SIMD3<Float>(480, 360, 1)
        let camera = CameraIntrinsicsValidator.make(
            cameraMatrix: mismatch,
            imageResolution: CGSize(width: 960, height: 720),
            capturedWidth: 1920,
            capturedHeight: 1440
        )
        XCTAssertFalse(camera.pnpIntrinsicsReady)
        let rows = (0..<8).map { i in correspondence(i, xyz: [Double(i), 0, 1], uv: [100, 100]) }
        let result = RuntimePnP.evaluate(
            correspondences: rows,
            uniquePoint3DCount: 8,
            xyzMissingRejected: 0,
            camera: camera,
            sim3: loadSim3()
        )
        XCTAssertEqual(result.status, "skippedIntrinsics")
        XCTAssertFalse(result.attempted)
        XCTAssertFalse(result.candidateQualified)
        XCTAssertEqual(result.localizationState, "idle")
    }

    func testExtractorIgnoresMissingXYZAndKeepsUniquePoint3D() {
        let rows = [
            correspondence(0, xyz: [1, 2, 3], uv: [10, 20], point3DID: 1),
            correspondence(1, xyz: nil, uv: [11, 21], point3DID: 2),
            correspondence(2, xyz: [1, 2, 3], uv: [12, 22], point3DID: 1)
        ]
        let extracted = PnPInputExtractor.finiteCorrespondences(from: rows)
        XCTAssertEqual(extracted.xyz.count, 1)
        XCTAssertEqual(extracted.missing, 1)
        XCTAssertEqual(extracted.xyz[0], [1, 2, 3])
    }

    private func correspondence(
        _ index: Int,
        xyz: [Double]?,
        uv: [Double],
        point3DID: Int64? = nil
    ) -> PnPCorrespondence {
        PnPCorrespondence(
            queryIndex: index,
            queryXYNative: uv,
            point3DID: point3DID ?? Int64(index + 1),
            referenceRow: index,
            colmapXYZ: xyz,
            ratio: 0.4,
            descriptorDistance: 0.2,
            queryCoordinateSpace: PnPConfig.queryCoordinateSpace
        )
    }

    private func nativeCamera() -> CameraIntrinsicsSnapshot {
        CameraIntrinsicsSnapshot(
            fx: PnPSyntheticFixture.fx,
            fy: PnPSyntheticFixture.fy,
            cx: PnPSyntheticFixture.cx,
            cy: PnPSyntheticFixture.cy,
            cameraMatrix: PnPSyntheticFixture.cameraMatrix,
            referenceWidth: 1920,
            referenceHeight: 1440,
            capturedWidth: 1920,
            capturedHeight: 1440
        )
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
