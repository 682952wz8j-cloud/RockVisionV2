import Foundation

struct PnPFrameResult: Codable, Equatable, Sendable {
    var status: String
    var localizationState: String
    var attempted: Bool
    var ransacAttempted: Bool
    var ransacSuccess: Bool
    var refineAttempted: Bool
    var refineOk: Bool
    var refineQualityOk: Bool
    var refineQualityFlag: String?
    var candidateQualified: Bool
    var inputCorrespondenceCount: Int
    var uniquePoint3DCount: Int
    var xyzMissingRejected: Int
    var inlierCount: Int
    var inlierRatio: Double
    var queryCoordinateSpace: String
    var distortionModel: String
    var opencvVersion: String
    var capturedWidth: Int?
    var capturedHeight: Int?
    var fx: Double?
    var fy: Double?
    var cx: Double?
    var cy: Double?
    var timestamp: TimeInterval?
    var frameID: UInt64?
    var reprojectionRansac: PnPReprojectionStats?
    var reprojectionRefined: PnPReprojectionStats?
    var refinementDeltaMedian: Double?
    var positiveDepthRatioRansac: Double?
    var positiveDepthRatioRefined: Double?
    var rvecRansac: [Double]?
    var tvecRansac: [Double]?
    var rvecRefined: [Double]?
    var tvecRefined: [Double]?
    var rotationMatrix: [[Double]]?
    var C_colmap: [Double]?
    var C_colmapUnits: String
    var T_opencvCam_colmap: [[Double]]?
    var C_wall: [Double]?
    var C_wallUnits: String
    var medianInlierDepthCam: Double?
    var medianInlierDepthCamUnits: String
    var medianInlierDepthMeters: Double?
    var medianInlierDepthMetersUnits: String
    var observationDepthNote: String
    var sim3Scale: Double?
    var error: String?

    static func inactive(reason: String) -> PnPFrameResult {
        base(status: reason, attempted: false)
    }

    fileprivate static func base(status: String, attempted: Bool, input: Int = 0, unique: Int = 0, missing: Int = 0) -> PnPFrameResult {
        PnPFrameResult(
            status: status,
            localizationState: PnPConfig.localizationState,
            attempted: attempted,
            ransacAttempted: false,
            ransacSuccess: false,
            refineAttempted: false,
            refineOk: false,
            refineQualityOk: false,
            refineQualityFlag: nil,
            candidateQualified: false,
            inputCorrespondenceCount: input,
            uniquePoint3DCount: unique,
            xyzMissingRejected: missing,
            inlierCount: 0,
            inlierRatio: 0,
            queryCoordinateSpace: PnPConfig.queryCoordinateSpace,
            distortionModel: PnPConfig.distortionModel,
            opencvVersion: OpenCVBridge.openCVVersion(),
            capturedWidth: nil,
            capturedHeight: nil,
            fx: nil,
            fy: nil,
            cx: nil,
            cy: nil,
            timestamp: nil,
            frameID: nil,
            reprojectionRansac: nil,
            reprojectionRefined: nil,
            refinementDeltaMedian: nil,
            positiveDepthRatioRansac: nil,
            positiveDepthRatioRefined: nil,
            rvecRansac: nil,
            tvecRansac: nil,
            rvecRefined: nil,
            tvecRefined: nil,
            rotationMatrix: nil,
            C_colmap: nil,
            C_colmapUnits: PnPConfig.cColmapUnits,
            T_opencvCam_colmap: nil,
            C_wall: nil,
            C_wallUnits: PnPConfig.cWallUnits,
            medianInlierDepthCam: nil,
            medianInlierDepthCamUnits: PnPConfig.depthCamUnits,
            medianInlierDepthMeters: nil,
            medianInlierDepthMetersUnits: PnPConfig.depthMetersUnits,
            observationDepthNote: PnPConfig.observationDepthLabel,
            sim3Scale: nil,
            error: nil
        )
    }
}

struct PnPRuntimeSnapshot: Equatable, Sendable {
    var status: String = "inactive"
    var localization: String = PnPConfig.localizationState
    var inputCorr: String = "—"
    var inliers: String = "—"
    var inlierRatio: String = "—"
    var reproj: String = "—"
    var cWall: String = "—"
    var obsDepth: String = "—"
}

enum PnPInputExtractor {
    /// Full unique + finite `colmapXYZ` / `queryXYNative`. Never diagnostic cap 20.
    static func finiteCorrespondences(from rows: [PnPCorrespondence]) -> (xyz: [[Double]], uv: [[Double]], missing: Int) {
        var seen = Set<Int64>()
        var xyz: [[Double]] = []
        var uv: [[Double]] = []
        var missing = 0
        xyz.reserveCapacity(rows.count)
        uv.reserveCapacity(rows.count)
        for row in rows {
            if seen.contains(row.point3DID) { continue }
            seen.insert(row.point3DID)
            let colmap = row.colmapXYZ
            let image = row.queryXYNative
            let xyzOK = PnPGeometry.isFiniteVec(colmap, count: 3)
            let uvOK = PnPGeometry.isFiniteVec(image, count: 2)
            if xyzOK && uvOK, let colmap, image.count == 2 {
                xyz.append(colmap)
                uv.append(image)
            } else {
                missing += 1
            }
        }
        return (xyz, uv, missing)
    }
}

enum RefineQuality {
    static func assess(
        refineOk: Bool,
        ransacReproj: PnPReprojectionStats?,
        refinedReproj: PnPReprojectionStats?,
        ransacCheir: PnPCheiralityStats?,
        refinedCheir: PnPCheiralityStats?,
        refinedFinite: Bool
    ) -> (ok: Bool, flag: String, reason: String?) {
        if !refineOk {
            return (false, "refineFailed", "RefineLM failed")
        }
        if !refinedFinite {
            return (false, "nonFinite", "RefineLM produced non-finite geometry")
        }
        guard let ransacReproj, let refinedReproj else {
            return (false, "invalidGeometry", "missing reprojection statistics")
        }
        if refinedReproj.median > ransacReproj.median + PnPConfig.refineReprojWorsePx {
            return (false, "reprojWorse", "RefineLM reprojection worsened")
        }
        if let ransacCheir, let refinedCheir,
           refinedCheir.positiveDepthRatio < ransacCheir.positiveDepthRatio - PnPConfig.refineCheiralityDrop {
            return (false, "cheiralityWorse", "RefineLM cheirality worsened")
        }
        return (true, "ok", nil)
    }
}

/// Same-frame PnP diagnostic. Localization stays idle. No ARKit / GPS / previous pose.
enum RuntimePnP {
    static func evaluate(
        correspondences: [PnPCorrespondence],
        uniquePoint3DCount: Int,
        xyzMissingRejected: Int,
        camera: CameraIntrinsicsSnapshot,
        sim3: ValidatedSim3?,
        frameID: UInt64? = nil,
        timestamp: TimeInterval? = nil
    ) -> PnPFrameResult {
        let extracted = PnPInputExtractor.finiteCorrespondences(from: correspondences)
        let input = extracted.xyz.count
        func annotated(_ result: PnPFrameResult) -> PnPFrameResult {
            var next = result
            next.frameID = frameID
            next.timestamp = timestamp
            next.capturedWidth = camera.capturedWidth
            next.capturedHeight = camera.capturedHeight
            next.fx = camera.fx
            next.fy = camera.fy
            next.cx = camera.cx
            next.cy = camera.cy
            next.uniquePoint3DCount = uniquePoint3DCount
            next.xyzMissingRejected = xyzMissingRejected
            next.inputCorrespondenceCount = input
            next.sim3Scale = sim3?.scale
            return next
        }

        guard camera.pnpIntrinsicsReady else {
            var next = annotated(PnPFrameResult.base(status: "skippedIntrinsics", attempted: false, input: input, unique: uniquePoint3DCount, missing: xyzMissingRejected))
            next.error = "native K / capturedImage not ready for PnP"
            return next
        }
        if input < PnPConfig.minCorrespondences {
            return annotated(
                PnPFrameResult.base(
                    status: "insufficientCorrespondences",
                    attempted: false,
                    input: input,
                    unique: uniquePoint3DCount,
                    missing: xyzMissingRejected
                )
            )
        }

        let solved = OpenCVBridge.solvePnPRansacThenRefine(
            objectPoints: nsPoints(extracted.xyz),
            imagePoints: nsPoints(extracted.uv),
            cameraMatrix: nsMatrix(camera.cameraMatrix),
            distCoeffs: nsVec(Array(repeating: 0, count: 5))
        )
        var result = annotated(
            PnPFrameResult.base(
                status: "ransacFailed",
                attempted: true,
                input: input,
                unique: uniquePoint3DCount,
                missing: xyzMissingRejected
            )
        )
        result.ransacAttempted = true
        result.opencvVersion = solved.cvVersion
        result.ransacSuccess = solved.ransacSuccess
        if !solved.ok {
            result.status = "invalidGeometry"
            result.error = solved.error ?? "PnP call failed"
            return result
        }

        let inliers = solved.inlierIndices.map(\.intValue).filter { $0 >= 0 && $0 < input }
        result.inlierCount = inliers.count
        result.inlierRatio = Double(inliers.count) / Double(input)
        result.rvecRansac = doubles(solved.rvecRansac)
        result.tvecRansac = doubles(solved.tvecRansac)

        guard solved.ransacSuccess else {
            result.status = "ransacFailed"
            result.error = solved.error
            return result
        }
        if inliers.count < PnPConfig.minCorrespondences {
            result.status = "refineRejected"
            result.error = "fewer than 4 RANSAC inliers"
            return result
        }

        let ransacPose = poseMetrics(
            rvec: solved.rvecRansac,
            tvec: solved.tvecRansac,
            objectPoints: extracted.xyz,
            imagePoints: extracted.uv,
            inliers: inliers,
            camera: camera
        )
        guard let ransacPose else {
            result.status = "invalidGeometry"
            result.error = "RANSAC pose is non-finite"
            return result
        }
        result.reprojectionRansac = ransacPose.reproj
        result.positiveDepthRatioRansac = ransacPose.cheirality.positiveDepthRatio

        result.refineAttempted = true
        result.rvecRefined = doubles(solved.rvecRefined)
        result.tvecRefined = doubles(solved.tvecRefined)
        result.refineOk = solved.refineOk

        let refinedPose = solved.refineOk
            ? poseMetrics(
                rvec: solved.rvecRefined,
                tvec: solved.tvecRefined,
                objectPoints: extracted.xyz,
                imagePoints: extracted.uv,
                inliers: inliers,
                camera: camera
            )
            : nil
        result.reprojectionRefined = refinedPose?.reproj
        result.positiveDepthRatioRefined = refinedPose?.cheirality.positiveDepthRatio
        if let ransacReproj = ransacPose.reproj, let refinedReproj = refinedPose?.reproj {
            result.refinementDeltaMedian = refinedReproj.median - ransacReproj.median
        }

        let refinedFinite = refinedPose != nil
        let quality = RefineQuality.assess(
            refineOk: solved.refineOk,
            ransacReproj: ransacPose.reproj,
            refinedReproj: refinedPose?.reproj,
            ransacCheir: ransacPose.cheirality,
            refinedCheir: refinedPose?.cheirality,
            refinedFinite: refinedFinite
        )
        result.refineQualityOk = quality.ok
        result.refineQualityFlag = quality.flag
        if !quality.ok {
            result.status = "refineRejected"
            result.error = quality.reason ?? solved.error
            attachObservationDepth(&result, pose: ransacPose, sim3: sim3)
            return result
        }

        guard let refinedPose else {
            result.status = "refineRejected"
            result.error = "RefineLM pose missing"
            return result
        }
        result.status = "candidate"
        result.candidateQualified = true
        result.rotationMatrix = refinedPose.rotation
        result.C_colmap = refinedPose.center
        result.T_opencvCam_colmap = refinedPose.transform
        attachObservationDepth(&result, pose: refinedPose, sim3: sim3)
        if result.C_wall == nil || result.medianInlierDepthMeters == nil {
            result.error = [result.error, "metric conversion incomplete"].compactMap { $0 }.joined(separator: "; ")
        }
        return result
    }

    static func evaluate(
        matching: MatchingFrameResult,
        camera: CameraIntrinsicsSnapshot,
        sim3: ValidatedSim3?,
        frameID: UInt64? = nil,
        timestamp: TimeInterval? = nil
    ) -> PnPFrameResult {
        evaluate(
            correspondences: matching.pnpCorrespondences,
            uniquePoint3DCount: matching.acceptedUniquePoint3D,
            xyzMissingRejected: matching.xyzMissingRejected,
            camera: camera,
            sim3: sim3,
            frameID: frameID,
            timestamp: timestamp
        )
    }

    static func snapshot(from result: PnPFrameResult) -> PnPRuntimeSnapshot {
        var snap = PnPRuntimeSnapshot()
        snap.status = result.status
        snap.localization = PnPConfig.localizationState
        snap.inputCorr = "\(result.inputCorrespondenceCount)"
        snap.inliers = result.ransacAttempted ? "\(result.inlierCount)" : "—"
        snap.inlierRatio = result.ransacAttempted ? String(format: "%.3f", result.inlierRatio) : "—"
        if let reproj = result.reprojectionRefined ?? result.reprojectionRansac {
            snap.reproj = String(format: "%.2f px", reproj.median)
        }
        if let c = result.C_wall, c.count == 3 {
            snap.cWall = String(format: "%.2f %.2f %.2f m", c[0], c[1], c[2])
        }
        if let meters = result.medianInlierDepthMeters {
            snap.obsDepth = String(format: "%.2f m", meters)
        }
        return snap
    }

    private struct PoseMetrics {
        var rotation: [[Double]]
        var t: [Double]
        var center: [Double]
        var transform: [[Double]]
        var reproj: PnPReprojectionStats?
        var cheirality: PnPCheiralityStats
        var medianInlierDepthCam: Double?
    }

    private static func poseMetrics(
        rvec: [NSNumber],
        tvec: [NSNumber],
        objectPoints: [[Double]],
        imagePoints: [[Double]],
        inliers: [Int],
        camera: CameraIntrinsicsSnapshot
    ) -> PoseMetrics? {
        let t = doubles(tvec)
        guard PnPGeometry.isFiniteVec(t, count: 3) else { return nil }
        let rod = OpenCVBridge.rodriguesRotation(fromRvec: rvec)
        guard rod.ok else { return nil }
        let R = matrix(rod.rotationMatrix)
        guard PnPGeometry.isFiniteMatrix(R, rows: 3, cols: 3) else { return nil }
        let C = PnPGeometry.cameraCenter(rotationRowMajor3x3: R, t: t)
        guard PnPGeometry.isFiniteVec(C, count: 3) else { return nil }
        let T = PnPGeometry.transformOpenCVCamColmap(rotationRowMajor3x3: R, t: t)
        guard PnPGeometry.isFiniteMatrix(T, rows: 4, cols: 4) else { return nil }
        let xyz = inliers.map { objectPoints[$0] }
        let uv = inliers.map { imagePoints[$0] }
        let projected = OpenCVBridge.projectPoints(
            objectPoints: nsPoints(xyz),
            rvec: rvec,
            tvec: tvec,
            cameraMatrix: nsMatrix(camera.cameraMatrix),
            distCoeffs: nsVec(Array(repeating: 0, count: 5))
        )
        let reproj = projected.ok
            ? PnPGeometry.reprojectionStats(observed: uv, projected: matrix(projected.imagePoints))
            : nil
        let cheir = PnPGeometry.cheirality(
            rotationRowMajor3x3: R,
            t: t,
            objectPoints: objectPoints,
            inlierIndices: inliers
        )
        return PoseMetrics(
            rotation: R,
            t: t,
            center: C,
            transform: T,
            reproj: reproj,
            cheirality: cheir,
            medianInlierDepthCam: cheir.medianInlierDepthCam
        )
    }

    private static func attachObservationDepth(_ result: inout PnPFrameResult, pose: PoseMetrics, sim3: ValidatedSim3?) {
        result.medianInlierDepthCam = pose.medianInlierDepthCam
        result.C_wall = sim3.flatMap { $0.apply(pose.center) }
        if let cam = pose.medianInlierDepthCam {
            result.medianInlierDepthMeters = sim3?.meters(fromCamDepth: cam)
        }
    }

    private static func nsVec(_ values: [Double]) -> [NSNumber] { values.map { NSNumber(value: $0) } }
    private static func nsPoints(_ points: [[Double]]) -> [[NSNumber]] { points.map(nsVec) }
    private static func nsMatrix(_ m: [[Double]]) -> [[NSNumber]] { m.map(nsVec) }
    private static func doubles(_ values: [NSNumber]) -> [Double] { values.map(\.doubleValue) }
    private static func matrix(_ values: [[NSNumber]]) -> [[Double]] { values.map(doubles) }
}
