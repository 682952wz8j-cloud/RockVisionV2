import Foundation

struct MatchingFrameResult: Equatable, Sendable {
    var status: String
    var queryKeypoints: Int
    var referenceDescriptorCount: Int
    var rawDescriptorCandidates: Int
    var uniquePoint3DCandidates: Int
    var insufficientDistinctPoint3D: Int
    var ratioRejected: Int
    var acceptedAfterRatio: Int
    var acceptedUniquePoint3D: Int
    var duplicatePoint3DRejected: Int
    var candidateKTruncatedQueries: Int
    var bestDistanceMedian: Double?
    var bestRatioMedian: Double?
    var matchingLatencyMs: Double
    var stage3TotalMs: Double
    var diagnosticMatches: [DiagnosticMatch]
    var pnpCorrespondences: [PnPCorrespondence]
    var xyzMissingRejected: Int
    var inputCorrespondenceCount: Int

    static func inactive(reason: String, siftTotalMs: Double = 0) -> MatchingFrameResult {
        MatchingFrameResult(
            status: reason,
            queryKeypoints: 0,
            referenceDescriptorCount: 0,
            rawDescriptorCandidates: 0,
            uniquePoint3DCandidates: 0,
            insufficientDistinctPoint3D: 0,
            ratioRejected: 0,
            acceptedAfterRatio: 0,
            acceptedUniquePoint3D: 0,
            duplicatePoint3DRejected: 0,
            candidateKTruncatedQueries: 0,
            bestDistanceMedian: nil,
            bestRatioMedian: nil,
            matchingLatencyMs: 0,
            stage3TotalMs: siftTotalMs,
            diagnosticMatches: [],
            pnpCorrespondences: [],
            xyzMissingRejected: 0,
            inputCorrespondenceCount: 0
        )
    }
}

struct MatchingRuntimeSnapshot: Equatable, Sendable {
    var status: String = "inactive"
    var queryKeypoints: String = "—"
    var acceptedAfterRatio: String = "—"
    var acceptedUniquePoint3D: String = "—"
    var ratioRejected: String = "—"
    var insufficientDistinctPoint3D: String = "—"
    var matchingMs: String = "—"
    var stage3Ms: String = "—"
    var referenceRows: String = "—"
}

/// Runtime matching: OpenCV BF KNN then Swift Point3D grouping. No GPS, pose, or scene label.
enum RuntimeMatcher {
    static func match(
        queryDescriptors: Data?,
        descriptorRows: Int,
        descriptorCols: Int,
        descriptorsFinite: Bool,
        nativeX: [Double],
        nativeY: [Double],
        database: ReferenceDatabase,
        siftTotalMs: Double
    ) -> MatchingFrameResult {
        let started = DispatchTime.now()
        func elapsedMs() -> Double {
            Double(DispatchTime.now().uptimeNanoseconds - started.uptimeNanoseconds) / 1_000_000.0
        }
        if descriptorRows > 0, descriptorCols != MatchingConfig.descriptorDim {
            return MatchingFrameResult.inactive(reason: "dim!=128", siftTotalMs: siftTotalMs)
        }
        let query = queryDescriptors ?? Data()
        let queryCount = max(0, descriptorRows)
        if query.count != DescriptorMatrix.byteCount(rows: queryCount) {
            return MatchingFrameResult.inactive(reason: "descriptor bytes mismatch", siftTotalMs: siftTotalMs)
        }
        let finiteFlags: [Bool]
        if queryCount == 0 {
            finiteFlags = []
        } else if !descriptorsFinite {
            finiteFlags = Array(repeating: false, count: queryCount)
        } else {
            finiteFlags = DescriptorMatrix.finiteFlags(data: query, count: queryCount)
        }
        let knn = OpenCVBridge.knnMatchL2(
            queryDescriptors: query,
            referenceDescriptors: database.descriptors,
            descriptorDim: Int32(MatchingConfig.descriptorDim),
            k: Int32(MatchingConfig.candidateK)
        )
        if !knn.ok {
            let ms = elapsedMs()
            var result = MatchingFrameResult.inactive(reason: knn.error ?? "knn failed", siftTotalMs: siftTotalMs + ms)
            result.queryKeypoints = queryCount
            result.referenceDescriptorCount = database.descriptorCount
            result.matchingLatencyMs = ms
            return result
        }
        let (indices, distances) = MatchingKNN.unpack(
            indicesInt32: knn.indicesInt32,
            distancesFloat32: knn.distancesFloat32,
            queryCount: queryCount,
            k: MatchingConfig.candidateK
        )
        let collapsed = Point3DMatchCollapser.match(
            queryCount: queryCount,
            queryFinite: finiteFlags,
            knnIndices: indices,
            knnDistances: distances,
            point3dIds: database.point3dIds,
            emptyReference: database.descriptorCount == 0
        )
        let matchingMs = elapsedMs()
        let unique = collapsed.acceptedUniquePoint3D
        let distancesKept = unique.compactMap(\.distance)
        let ratiosKept = unique.compactMap(\.ratio)
        let sidecar = PnPSidecarBuilder.make(
            unique: unique,
            nativeX: nativeX,
            nativeY: nativeY,
            database: database
        )
        return MatchingFrameResult(
            status: "active",
            queryKeypoints: queryCount,
            referenceDescriptorCount: database.descriptorCount,
            rawDescriptorCandidates: collapsed.rawDescriptorCandidates,
            uniquePoint3DCandidates: collapsed.uniquePoint3DCandidates,
            insufficientDistinctPoint3D: collapsed.insufficientDistinctPoint3D,
            ratioRejected: collapsed.ratioRejected,
            acceptedAfterRatio: collapsed.acceptedAfterRatio.count,
            acceptedUniquePoint3D: unique.count,
            duplicatePoint3DRejected: collapsed.duplicatePoint3DRejected,
            candidateKTruncatedQueries: collapsed.candidateKTruncatedQueries,
            bestDistanceMedian: SIFTStatistics.percentile(distancesKept, 50),
            bestRatioMedian: SIFTStatistics.percentile(ratiosKept, 50),
            matchingLatencyMs: matchingMs,
            stage3TotalMs: siftTotalMs + matchingMs,
            diagnosticMatches: diagnosticMatches(
                unique: unique,
                nativeX: nativeX,
                nativeY: nativeY,
                database: database
            ),
            pnpCorrespondences: sidecar.correspondences,
            xyzMissingRejected: sidecar.xyzMissingRejected,
            inputCorrespondenceCount: sidecar.inputCorrespondenceCount
        )
    }

    private static func diagnosticMatches(
        unique: [MatchRecord],
        nativeX: [Double],
        nativeY: [Double],
        database: ReferenceDatabase
    ) -> [DiagnosticMatch] {
        Array(unique.prefix(MatchingConfig.diagnosticMatchCap)).compactMap { record in
            guard let provenance = database.provenance(for: record),
                  let distance = record.distance,
                  let ratio = record.ratio,
                  let point3DID = record.point3DID
            else { return nil }
            let qi = record.queryIndex
            let x = qi < nativeX.count ? nativeX[qi] : 0
            let y = qi < nativeY.count ? nativeY[qi] : 0
            return DiagnosticMatch(
                queryXY: [x, y],
                distance: distance,
                ratio: ratio,
                point3DID: point3DID,
                referenceImageID: provenance.referenceImageID,
                referenceImageName: provenance.referenceImageName,
                referenceXY: provenance.referenceXY
            )
        }
    }
}
