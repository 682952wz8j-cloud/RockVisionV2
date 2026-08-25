import Foundation

struct PnPCorrespondence: Codable, Equatable, Sendable {
    var queryIndex: Int
    var queryXYNative: [Double]
    var point3DID: Int64
    var referenceRow: Int
    var colmapXYZ: [Double]?
    var ratio: Double
    var descriptorDistance: Double
    var queryCoordinateSpace: String
}

struct FieldTestCameraSidecar: Codable, Equatable, Sendable {
    var nativeWidth: Int
    var nativeHeight: Int
    var processingWidth: Int
    var processingHeight: Int
    var capturedWidth: Int
    var capturedHeight: Int
    var imageResolutionWidth: Int
    var imageResolutionHeight: Int
    var fx: Double
    var fy: Double
    var cx: Double
    var cy: Double
    var cameraMatrix: [[Double]]
    var queryCoordinateSpace: String
    var distortionModel: String
    var openCVVersion: String
    var imageResolutionMatchesCaptured: Bool
    var capturedMatchesExpectedNative: Bool
    var pnpIntrinsicsReady: Bool
}

struct PnPSidecarBuild: Equatable, Sendable {
    var correspondences: [PnPCorrespondence]
    var inputCorrespondenceCount: Int
    var xyzMissingRejected: Int
    var duplicatePoint3DRejected: Int
    var malformedRejected: Int

    static let empty = PnPSidecarBuild(
        correspondences: [],
        inputCorrespondenceCount: 0,
        xyzMissingRejected: 0,
        duplicatePoint3DRejected: 0,
        malformedRejected: 0
    )
}

enum PnPSidecarBuilder {
    /// XYZ lookup happens after matching. Matcher hot path stays descriptor + point3DID.
    static func make(
        unique: [MatchRecord],
        nativeX: [Double],
        nativeY: [Double],
        database: ReferenceDatabase
    ) -> PnPSidecarBuild {
        var seen = Set<Int64>()
        var rows: [PnPCorrespondence] = []
        var input = 0
        var missing = 0
        var duplicate = 0
        var malformed = 0
        rows.reserveCapacity(unique.count)
        for record in unique {
            guard let point3DID = record.point3DID,
                  let rowIndex = record.referenceRow,
                  let distance = record.distance,
                  let ratio = record.ratio
            else {
                malformed += 1
                continue
            }
            if seen.contains(point3DID) {
                duplicate += 1
                continue
            }
            seen.insert(point3DID)
            let qi = record.queryIndex
            let x = qi >= 0 && qi < nativeX.count ? nativeX[qi] : Double.nan
            let y = qi >= 0 && qi < nativeY.count ? nativeY[qi] : Double.nan
            let xyz = (rowIndex >= 0 && rowIndex < database.rows.count) ? database.rows[rowIndex].colmapXYZ : nil
            let finite = isFiniteXYZ(xyz)
            if finite {
                input += 1
            } else {
                missing += 1
            }
            rows.append(
                PnPCorrespondence(
                    queryIndex: qi,
                    queryXYNative: [x, y],
                    point3DID: point3DID,
                    referenceRow: rowIndex,
                    colmapXYZ: finite ? xyz : nil,
                    ratio: ratio,
                    descriptorDistance: distance,
                    queryCoordinateSpace: PnPConfig.queryCoordinateSpace
                )
            )
        }
        return PnPSidecarBuild(
            correspondences: rows,
            inputCorrespondenceCount: input,
            xyzMissingRejected: missing,
            duplicatePoint3DRejected: duplicate,
            malformedRejected: malformed
        )
    }

    static func cameraSidecar(
        result: SIFTFrameResult,
        camera: CameraIntrinsicsSnapshot,
        openCVVersion: String
    ) -> FieldTestCameraSidecar {
        FieldTestCameraSidecar(
            nativeWidth: result.nativeImageWidth,
            nativeHeight: result.nativeImageHeight,
            processingWidth: result.processingWidth,
            processingHeight: result.processingHeight,
            capturedWidth: camera.capturedWidth,
            capturedHeight: camera.capturedHeight,
            imageResolutionWidth: camera.referenceWidth,
            imageResolutionHeight: camera.referenceHeight,
            fx: camera.fx,
            fy: camera.fy,
            cx: camera.cx,
            cy: camera.cy,
            cameraMatrix: camera.cameraMatrix,
            queryCoordinateSpace: PnPConfig.queryCoordinateSpace,
            distortionModel: PnPConfig.distortionModel,
            openCVVersion: openCVVersion,
            imageResolutionMatchesCaptured: camera.imageResolutionMatchesCaptured,
            capturedMatchesExpectedNative: camera.capturedMatchesExpectedNative,
            pnpIntrinsicsReady: camera.pnpIntrinsicsReady
        )
    }

    static func isFiniteXYZ(_ xyz: [Double]?) -> Bool {
        guard let xyz, xyz.count == 3 else { return false }
        return xyz.allSatisfy { $0.isFinite }
    }
}
