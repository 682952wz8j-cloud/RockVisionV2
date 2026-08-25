import Foundation

enum MatchReason: String, Equatable, Sendable {
    case acceptedAfterRatio
    case insufficientDistinctPoint3D
    case ratioRejected
    case nonFiniteDescriptor
}

struct MatchRecord: Equatable, Sendable {
    var queryIndex: Int
    var reason: MatchReason
    var point3DID: Int64?
    var distance: Double?
    var secondDistance: Double?
    var ratio: Double?
    var referenceRow: Int?
    var rawDescriptorCandidates: Int = 0
    var uniquePoint3DCandidates: Int = 0
    var candidateKTruncatedDistinct: Bool = false
}

struct MatchResult: Equatable, Sendable {
    var records: [MatchRecord]
    var acceptedAfterRatio: [MatchRecord]
    var acceptedUniquePoint3D: [MatchRecord]
    var insufficientDistinctPoint3D: Int
    var ratioRejected: Int
    var duplicatePoint3DRejected: Int
    var rawDescriptorCandidates: Int
    var uniquePoint3DCandidates: Int
    var candidateKTruncatedQueries: Int
    var emptyQuery: Bool
    var emptyReference: Bool
}

enum Point3DMatchCollapser {
    /// Point3D-aware matching. KNN is injected so Swift tests do not need OpenCV.
    static func match(
        queryCount: Int,
        queryFinite: [Bool]? = nil,
        knnIndices: [[Int]],
        knnDistances: [[Double]],
        point3dIds: [Int64],
        candidateK: Int = MatchingConfig.candidateK,
        minDistinct: Int = MatchingConfig.minDistinctPoint3DForRatio,
        ratioThreshold: Double = MatchingConfig.ratioThreshold,
        emptyReference: Bool = false
    ) -> MatchResult {
        let emptyQuery = queryCount == 0
        var records: [MatchRecord] = []
        var rawTotal = 0
        var uniqueTotal = 0
        var truncated = 0
        for qi in 0..<queryCount {
            if let flags = queryFinite, qi < flags.count, flags[qi] == false {
                records.append(MatchRecord(queryIndex: qi, reason: .nonFiniteDescriptor))
                continue
            }
            let idxs = qi < knnIndices.count ? knnIndices[qi] : []
            let dists = qi < knnDistances.count ? knnDistances[qi] : []
            let pairs = zip(idxs, dists).filter { $0.0 >= 0 && $0.1.isFinite }
            let rawCount = pairs.count
            rawTotal += rawCount
            let grouped = groupPoint3D(pairs: pairs, point3dIds: point3dIds)
            let uniqueCount = grouped.count
            uniqueTotal += uniqueCount
            let truncatedFlag = rawCount == candidateK && uniqueCount < minDistinct
            if truncatedFlag { truncated += 1 }
            if uniqueCount < minDistinct {
                let first = grouped.first
                records.append(
                    MatchRecord(
                        queryIndex: qi,
                        reason: .insufficientDistinctPoint3D,
                        point3DID: first?.id,
                        distance: first?.distance,
                        referenceRow: first?.row,
                        rawDescriptorCandidates: rawCount,
                        uniquePoint3DCandidates: uniqueCount,
                        candidateKTruncatedDistinct: truncatedFlag
                    )
                )
                continue
            }
            let best = grouped[0]
            let second = grouped[1]
            let ratio = second.distance > 0 ? best.distance / second.distance : Double.infinity
            let reason: MatchReason = ratio < ratioThreshold ? .acceptedAfterRatio : .ratioRejected
            records.append(
                MatchRecord(
                    queryIndex: qi,
                    reason: reason,
                    point3DID: best.id,
                    distance: best.distance,
                    secondDistance: second.distance,
                    ratio: ratio,
                    referenceRow: best.row,
                    rawDescriptorCandidates: rawCount,
                    uniquePoint3DCandidates: uniqueCount,
                    candidateKTruncatedDistinct: truncatedFlag
                )
            )
        }
        let accepted = records.filter { $0.reason == .acceptedAfterRatio }
        let (uniqueKept, dupRejected) = uniquePoint3DDedup(accepted)
        return MatchResult(
            records: records,
            acceptedAfterRatio: accepted,
            acceptedUniquePoint3D: uniqueKept,
            insufficientDistinctPoint3D: records.filter { $0.reason == .insufficientDistinctPoint3D }.count,
            ratioRejected: records.filter { $0.reason == .ratioRejected }.count,
            duplicatePoint3DRejected: dupRejected,
            rawDescriptorCandidates: rawTotal,
            uniquePoint3DCandidates: uniqueTotal,
            candidateKTruncatedQueries: truncated,
            emptyQuery: emptyQuery,
            emptyReference: emptyReference
        )
    }

    static func uniquePoint3DDedup(_ accepted: [MatchRecord]) -> ([MatchRecord], Int) {
        var best: [Int64: MatchRecord] = [:]
        for record in accepted {
            guard let pid = record.point3DID else { continue }
            if let current = best[pid] {
                if betterUnique(record, than: current) {
                    best[pid] = record
                }
            } else {
                best[pid] = record
            }
        }
        let kept = best.values.sorted { $0.queryIndex < $1.queryIndex }
        return (kept, max(0, accepted.count - kept.count))
    }

    private struct Grouped {
        var id: Int64
        var distance: Double
        var row: Int
    }

    private static func groupPoint3D(pairs: [(Int, Double)], point3dIds: [Int64]) -> [Grouped] {
        var best: [Int64: (distance: Double, row: Int)] = [:]
        for (idx, dist) in pairs {
            guard idx >= 0, idx < point3dIds.count else { continue }
            let pid = point3dIds[idx]
            if let prev = best[pid] {
                if dist < prev.distance || (dist == prev.distance && idx < prev.row) {
                    best[pid] = (dist, idx)
                }
            } else {
                best[pid] = (dist, idx)
            }
        }
        return best.map { Grouped(id: $0.key, distance: $0.value.distance, row: $0.value.row) }
            .sorted { lhs, rhs in
                if lhs.distance != rhs.distance { return lhs.distance < rhs.distance }
                if lhs.id != rhs.id { return lhs.id < rhs.id }
                return lhs.row < rhs.row
            }
    }

    private static func betterUnique(_ new: MatchRecord, than old: MatchRecord) -> Bool {
        let newRatio = new.ratio ?? Double.infinity
        let oldRatio = old.ratio ?? Double.infinity
        if newRatio != oldRatio { return newRatio < oldRatio }
        let newD = new.distance ?? Double.infinity
        let oldD = old.distance ?? Double.infinity
        if newD != oldD { return newD < oldD }
        return new.queryIndex < old.queryIndex
    }
}

struct DiagnosticMatch: Equatable, Sendable, Codable {
    var queryXY: [Double]
    var distance: Double
    var ratio: Double
    var point3DID: Int64
    var referenceImageID: Int
    var referenceImageName: String
    var referenceXY: [Double]
}
