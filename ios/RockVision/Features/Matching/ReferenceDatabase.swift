import Foundation

struct LandmarkRow: Codable, Equatable, Sendable {
    var index: Int
    var referenceImageID: Int
    var referenceImageName: String
    var referenceKeypointX: Double
    var referenceKeypointY: Double
    var point3DID: Int64
    var colmapXYZ: [Double]?
    var wallLocalXYZ: [Double]?
}

struct MatchProvenance: Equatable, Sendable {
    var queryIndex: Int
    var point3DID: Int64?
    var distance: Double?
    var secondDistance: Double?
    var ratio: Double?
    var referenceRow: Int
    var referenceImageID: Int
    var referenceImageName: String
    var referenceXY: [Double]
}

struct ReferenceDatabase: Equatable, Sendable {
    var descriptors: Data
    var descriptorCount: Int
    var point3dIds: [Int64]
    var rows: [LandmarkRow]
    var wallId: String
    var matcherHotPath: [String]
    var developmentFixtureOnly: Bool
    var notAWallPackage: Bool

    static func load(descriptorsURL: URL, landmarksURL: URL) throws -> ReferenceDatabase {
        let rvs1 = try RVS1Artifact.read(from: descriptorsURL)
        let file = try JSONDecoder().decode(LandmarksFile.self, from: try Data(contentsOf: landmarksURL))
        if file.landmarks.count != rvs1.count {
            throw MatchingError.landmarkCountMismatch(descriptors: rvs1.count, landmarks: file.landmarks.count)
        }
        return ReferenceDatabase(
            descriptors: rvs1.data,
            descriptorCount: rvs1.count,
            point3dIds: file.landmarks.map(\.point3DID),
            rows: file.landmarks,
            wallId: file.wallId,
            matcherHotPath: file.matcherHotPath ?? ["descriptor", "point3DID"],
            developmentFixtureOnly: file.developmentFixtureOnly ?? true,
            notAWallPackage: file.notAWallPackage ?? true
        )
    }

    func provenance(for record: MatchRecord) -> MatchProvenance? {
        guard let rowIndex = record.referenceRow, rowIndex >= 0, rowIndex < rows.count else { return nil }
        let row = rows[rowIndex]
        return MatchProvenance(
            queryIndex: record.queryIndex,
            point3DID: record.point3DID,
            distance: record.distance,
            secondDistance: record.secondDistance,
            ratio: record.ratio,
            referenceRow: rowIndex,
            referenceImageID: row.referenceImageID,
            referenceImageName: row.referenceImageName,
            referenceXY: [row.referenceKeypointX, row.referenceKeypointY]
        )
    }
}

private struct LandmarksFile: Codable {
    var schema: Int?
    var schemaId: String?
    var wallId: String
    var developmentFixtureOnly: Bool?
    var notAWallPackage: Bool?
    var landmarks: [LandmarkRow]
    var matcherHotPath: [String]?
}

enum Point3DMatcher {
    /// Injected-KNN path used by unit tests. OpenCV is not required.
    static func match(
        queryCount: Int,
        descriptorDim: Int = MatchingConfig.descriptorDim,
        queryFinite: [Bool]? = nil,
        knnIndices: [[Int]],
        knnDistances: [[Double]],
        point3dIds: [Int64],
        candidateK: Int = MatchingConfig.candidateK,
        emptyReference: Bool = false
    ) throws -> MatchResult {
        try DescriptorMatrix.validateNonEmptyDimension(descriptorDim, count: queryCount)
        return Point3DMatchCollapser.match(
            queryCount: queryCount,
            queryFinite: queryFinite,
            knnIndices: knnIndices,
            knnDistances: knnDistances,
            point3dIds: point3dIds,
            candidateK: candidateK,
            emptyReference: emptyReference
        )
    }
}
