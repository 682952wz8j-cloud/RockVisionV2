import simd
import XCTest
@testable import RockVision

final class PnPConventionTests: XCTestCase {
    func testFrozenBaselineIsEPNPNotUSAC() {
        XCTAssertEqual(OpenCVBridge.solvePnPFlagsEPNP(), Int32(PnPConfig.flagsValue))
        XCTAssertEqual(PnPConfig.flagsName, "SOLVEPNP_EPNP")
        XCTAssertEqual(PnPConfig.iterationsCount, 100)
        XCTAssertEqual(PnPConfig.reprojectionErrorNativePx, 8.0, accuracy: 0)
        XCTAssertEqual(PnPConfig.confidence, 0.99, accuracy: 0)
        XCTAssertFalse(PnPConfig.useExtrinsicGuess)
        XCTAssertEqual(PnPConfig.associationRadiusPx, 2.0, accuracy: 0)
        XCTAssertNotEqual(PnPConfig.reprojectionErrorNativePx, PnPConfig.associationRadiusPx)
        let summary = OpenCVBridge.solvePnPBaselineSummary()
        XCTAssertTrue(summary.contains("SOLVEPNP_EPNP"))
        XCTAssertTrue(summary.contains("8.0"))
        XCTAssertFalse(summary.lowercased().contains("usac"))
        XCTAssertTrue(OpenCVBridge.openCVVersion().hasPrefix("4.14"))
        XCTAssertEqual(Int(OpenCVBridge.solvePnPFlagsEPNP()), PnPConfig.flagsValue)
    }

    func testTvecIsNotCameraCenter() throws {
        let rod = try XCTUnwrap(OpenCVBridge.rodriguesRotation(fromRvec: nsVec(PnPSyntheticFixture.rvec)))
        XCTAssertTrue(rod.ok)
        let R = matrix(rod.rotationMatrix)
        let t = PnPSyntheticFixture.tvec
        let C = PnPGeometry.cameraCenter(rotationRowMajor3x3: R, t: t)
        let forbiddenMinusRT = [
            -(R[0][0] * t[0] + R[0][1] * t[1] + R[0][2] * t[2]),
            -(R[1][0] * t[0] + R[1][1] * t[1] + R[1][2] * t[2]),
            -(R[2][0] * t[0] + R[2][1] * t[1] + R[2][2] * t[2])
        ]
        XCTAssertGreaterThan(PnPGeometry.l2(C, t), 0.05, "tvec must not be reported as camera position")
        XCTAssertGreaterThan(PnPGeometry.l2(C, forbiddenMinusRT), 0.01, "camera center is -Rᵀ t, not -R t")
        let T = PnPGeometry.transformOpenCVCamColmap(rotationRowMajor3x3: R, t: t)
        XCTAssertEqual(T[0][3], t[0], accuracy: 1e-12)
        XCTAssertEqual(T[3][3], 1, accuracy: 1e-12)
        let X = [0.5, -0.2, 0.1]
        let cam = PnPGeometry.cameraPoint(rotationRowMajor3x3: R, t: t, world: X)
        let recovered = [
            R[0][0] * X[0] + R[0][1] * X[1] + R[0][2] * X[2] + t[0],
            R[1][0] * X[0] + R[1][1] * X[1] + R[1][2] * X[2] + t[1],
            R[2][0] * X[0] + R[2][1] * X[1] + R[2][2] * X[2] + t[2]
        ]
        XCTAssertEqual(PnPGeometry.l2(cam, recovered), 0, accuracy: 1e-12)
        let minusRT = [
            -(R[0][0] * t[0] + R[1][0] * t[1] + R[2][0] * t[2]),
            -(R[0][1] * t[0] + R[1][1] * t[1] + R[2][1] * t[2]),
            -(R[0][2] * t[0] + R[1][2] * t[1] + R[2][2] * t[2])
        ]
        XCTAssertEqual(PnPGeometry.l2(C, minusRT), 0, accuracy: 1e-12)
    }

    func testNativeXYNativeKRecoversKnownPose() throws {
        let correct = try evaluate(imagePoints: try projectNative(), cameraMatrix: PnPSyntheticFixture.cameraMatrix)
        XCTAssertTrue(correct.ransacSuccess)
        XCTAssertTrue(correct.refineOk)
        XCTAssertLessThan(correct.rotationDeg, 0.05)
        XCTAssertLessThan(correct.centerError, 1e-3)
        XCTAssertLessThan(correct.reproj.median, 0.05)
        XCTAssertEqual(correct.cheirality.positiveDepthRatio, 1.0, accuracy: 1e-12)
        XCTAssertGreaterThan(correct.inlierCount, 10)
        XCTAssertFalse(correct.refinedWorse)
        XCTAssertTrue(correct.cvVersion.hasPrefix("4.14"))
    }

    func testCoordinateMismatchNegativesAreClearlyWorse() throws {
        let nativeUV = try projectNative()
        let correct = try evaluate(imagePoints: nativeUV, cameraMatrix: PnPSyntheticFixture.cameraMatrix)
        let scaledK = PnPGeometry.scaleCameraMatrix(PnPSyntheticFixture.cameraMatrix, factor: PnPSyntheticFixture.processingScale)
        let wrongK = try evaluate(imagePoints: nativeUV, cameraMatrix: scaledK)
        let scaledUV = PnPGeometry.scalePoints(nativeUV, factor: PnPSyntheticFixture.processingScale)
        let wrongUV = try evaluate(imagePoints: scaledUV, cameraMatrix: PnPSyntheticFixture.cameraMatrix)

        assertClearlyWorse(wrong: wrongK, correct: correct, label: "native UV + scaled K")
        assertClearlyWorse(wrong: wrongUV, correct: correct, label: "scaled 960 UV + native K")
    }

    func testImageResolutionMismatchDoesNotSilentlyScale() {
        var mismatchK = simd_float3x3(0)
        mismatchK.columns.0 = SIMD3<Float>(725, 0, 0)
        mismatchK.columns.1 = SIMD3<Float>(0, 725, 0)
        mismatchK.columns.2 = SIMD3<Float>(480, 360, 1)
        let mismatch = CameraIntrinsicsValidator.make(
            cameraMatrix: mismatchK,
            imageResolution: CGSize(width: 960, height: 720),
            capturedWidth: 1920,
            capturedHeight: 1440
        )
        XCTAssertTrue(mismatch.isValid)
        XCTAssertFalse(mismatch.imageResolutionMatchesCaptured)
        XCTAssertFalse(mismatch.pnpIntrinsicsReady)

        var nativeK = simd_float3x3(0)
        nativeK.columns.0 = SIMD3<Float>(1450, 0, 0)
        nativeK.columns.1 = SIMD3<Float>(0, 1450, 0)
        nativeK.columns.2 = SIMD3<Float>(960, 720, 1)
        let native = CameraIntrinsicsValidator.make(
            cameraMatrix: nativeK,
            imageResolution: CGSize(width: 1920, height: 1440),
            capturedWidth: 1920,
            capturedHeight: 1440
        )
        XCTAssertTrue(native.pnpIntrinsicsReady)
        XCTAssertEqual(native.cameraMatrix[0][0], 1450, accuracy: 0.01)
        XCTAssertEqual(native.cameraMatrix[0][2], 960, accuracy: 0.01)
    }

    private struct Eval {
        var ransacSuccess: Bool
        var refineOk: Bool
        var rotationDeg: Double
        var centerError: Double
        var reproj: PnPReprojectionStats
        var cheirality: PnPCheiralityStats
        var inlierCount: Int
        var refinedWorse: Bool
        var cvVersion: String
    }

    private func projectNative() throws -> [[Double]] {
        let projected = OpenCVBridge.projectPoints(
            objectPoints: nsPoints3(PnPSyntheticFixture.objectPoints),
            rvec: nsVec(PnPSyntheticFixture.rvec),
            tvec: nsVec(PnPSyntheticFixture.tvec),
            cameraMatrix: nsMatrix(PnPSyntheticFixture.cameraMatrix),
            distCoeffs: nsVec(PnPSyntheticFixture.distCoeffs)
        )
        XCTAssertTrue(projected.ok, projected.error ?? "projectPoints failed")
        let points = matrix(projected.imagePoints)
        XCTAssertEqual(points.count, PnPSyntheticFixture.objectPoints.count)
        for p in points {
            XCTAssertGreaterThan(p[0], 0)
            XCTAssertLessThan(p[0], Double(PnPSyntheticFixture.nativeWidth))
            XCTAssertGreaterThan(p[1], 0)
            XCTAssertLessThan(p[1], Double(PnPSyntheticFixture.nativeHeight))
        }
        return points
    }

    private func evaluate(imagePoints: [[Double]], cameraMatrix: [[Double]]) throws -> Eval {
        let gtR = try XCTUnwrap(OpenCVBridge.rodriguesRotation(fromRvec: nsVec(PnPSyntheticFixture.rvec)))
        let Rgt = matrix(gtR.rotationMatrix)
        let Cgt = PnPGeometry.cameraCenter(rotationRowMajor3x3: Rgt, t: PnPSyntheticFixture.tvec)
        let solved = OpenCVBridge.solvePnPRansacThenRefine(
            objectPoints: nsPoints3(PnPSyntheticFixture.objectPoints),
            imagePoints: nsPoints2(imagePoints),
            cameraMatrix: nsMatrix(cameraMatrix),
            distCoeffs: nsVec(PnPSyntheticFixture.distCoeffs)
        )
        XCTAssertTrue(solved.ok, solved.error ?? "PnP call failed")
        XCTAssertEqual(solved.flagsName, "SOLVEPNP_EPNP")
        XCTAssertEqual(Int(solved.flagsValue), PnPConfig.flagsValue)
        XCTAssertEqual(Int(solved.iterationsCount), 100)
        XCTAssertEqual(solved.reprojectionError, 8.0, accuracy: 0)
        XCTAssertFalse(solved.useExtrinsicGuess)
        let inliers = solved.inlierIndices.map(\.intValue)
        let poseRvec = solved.refineOk ? solved.rvecRefined : solved.rvecRansac
        let poseTvec = solved.refineOk ? solved.tvecRefined : solved.tvecRansac
        let rod = try XCTUnwrap(OpenCVBridge.rodriguesRotation(fromRvec: poseRvec))
        let R = matrix(rod.rotationMatrix)
        let t = doubles(poseTvec)
        let C = PnPGeometry.cameraCenter(rotationRowMajor3x3: R, t: t)
        let metricIndices = inliers.isEmpty ? Array(imagePoints.indices) : inliers
        let metricXYZ = metricIndices.compactMap { i -> [Double]? in
            guard i >= 0 && i < PnPSyntheticFixture.objectPoints.count else { return nil }
            return PnPSyntheticFixture.objectPoints[i]
        }
        let metricUV = metricIndices.compactMap { i -> [Double]? in
            guard i >= 0 && i < imagePoints.count else { return nil }
            return imagePoints[i]
        }
        let projected = OpenCVBridge.projectPoints(
            objectPoints: nsPoints3(metricXYZ),
            rvec: poseRvec,
            tvec: poseTvec,
            cameraMatrix: nsMatrix(cameraMatrix),
            distCoeffs: nsVec(PnPSyntheticFixture.distCoeffs)
        )
        let reproj = try XCTUnwrap(PnPGeometry.reprojectionStats(observed: metricUV, projected: matrix(projected.imagePoints)))
        let cheirality = PnPGeometry.cheirality(
            rotationRowMajor3x3: R,
            t: t,
            objectPoints: PnPSyntheticFixture.objectPoints,
            inlierIndices: metricIndices
        )
        var refinedWorse = false
        if solved.ransacSuccess && solved.refineOk {
            let ransacRod = try XCTUnwrap(OpenCVBridge.rodriguesRotation(fromRvec: solved.rvecRansac))
            let Rr = matrix(ransacRod.rotationMatrix)
            let tr = doubles(solved.tvecRansac)
            let ransacProj = OpenCVBridge.projectPoints(
                objectPoints: nsPoints3(metricXYZ),
                rvec: solved.rvecRansac,
                tvec: solved.tvecRansac,
                cameraMatrix: nsMatrix(cameraMatrix),
                distCoeffs: nsVec(PnPSyntheticFixture.distCoeffs)
            )
            let ransacReproj = try XCTUnwrap(PnPGeometry.reprojectionStats(observed: metricUV, projected: matrix(ransacProj.imagePoints)))
            let ransacCheir = PnPGeometry.cheirality(
                rotationRowMajor3x3: Rr,
                t: tr,
                objectPoints: PnPSyntheticFixture.objectPoints,
                inlierIndices: inliers
            )
            refinedWorse = reproj.median > ransacReproj.median + 1.0
                || cheirality.positiveDepthRatio < ransacCheir.positiveDepthRatio - 0.05
        }
        return Eval(
            ransacSuccess: solved.ransacSuccess,
            refineOk: solved.refineOk,
            rotationDeg: PnPGeometry.rotationAngleDegrees(estimated: R, groundTruth: Rgt),
            centerError: PnPGeometry.l2(C, Cgt),
            reproj: reproj,
            cheirality: cheirality,
            inlierCount: inliers.count,
            refinedWorse: refinedWorse,
            cvVersion: solved.cvVersion
        )
    }

    private func assertClearlyWorse(wrong: Eval, correct: Eval, label: String) {
        XCTAssertGreaterThan(wrong.rotationDeg, max(5.0, correct.rotationDeg * 10), "\(label) rotation")
        XCTAssertGreaterThan(wrong.centerError, max(1.0, correct.centerError * 10), "\(label) camera center")
        XCTAssertGreaterThan(wrong.reproj.median, max(0.5, correct.reproj.median * 10), "\(label) reprojection")
        let geometryWorse = wrong.centerError > 1.0 || wrong.cheirality.positiveDepthRatio < 0.99
        XCTAssertTrue(geometryWorse, "\(label) geometry sanity")
    }

    private func nsVec(_ values: [Double]) -> [NSNumber] { values.map { NSNumber(value: $0) } }
    private func nsPoints3(_ points: [[Double]]) -> [[NSNumber]] { points.map(nsVec) }
    private func nsPoints2(_ points: [[Double]]) -> [[NSNumber]] { points.map(nsVec) }
    private func nsMatrix(_ m: [[Double]]) -> [[NSNumber]] { m.map(nsVec) }
    private func doubles(_ values: [NSNumber]) -> [Double] { values.map(\.doubleValue) }
    private func matrix(_ values: [[NSNumber]]) -> [[Double]] { values.map(doubles) }
}
