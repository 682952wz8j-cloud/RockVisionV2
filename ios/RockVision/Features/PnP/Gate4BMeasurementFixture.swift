import Foundation

/// Development / validation-only runtime copy of frozen Gate 4B W01–W04.
/// Not a production route asset. Not `S_wall_colmap`. Not the Gate 3C matching fixture.
struct Gate4BMeasurementLandmark: Codable, Equatable, Sendable {
    var id: String
    var wallXYZMeters: [Double]
}

struct Gate4BMeasurementFixture: Codable, Equatable, Sendable {
    var schemaVersion: String
    var developmentValidationOnly: Bool
    var notAProductionRouteAsset: Bool
    var sourceFormalManifest: String
    var localMetricGtArtifact: String?
    var wallID: String
    var coordinateFrame: String
    var landmarks: [Gate4BMeasurementLandmark]

    static let resourceName = "Gate4BMeasurementFixture"
    static let expectedWallID = "wall_jiulongfeng_01"
    static let expectedIDs = ["W01", "W02", "W03", "W04"]
    static let forbiddenRuntimeIDs = ["R02H", "R02F", "R04H", "R04V"]

    static func load(from url: URL) throws -> Gate4BMeasurementFixture {
        try JSONDecoder().decode(Gate4BMeasurementFixture.self, from: try Data(contentsOf: url))
    }

    static func loadFromBundle(_ bundle: Bundle) -> Gate4BMeasurementFixture? {
        guard let url = bundle.url(forResource: resourceName, withExtension: "json") else {
            return nil
        }
        return try? load(from: url)
    }

    /// Returns W01–W04 only when the currently loaded wall matches. No fallback.
    func activeLandmarks(currentWallID: String?) -> [Gate4BMeasurementLandmark] {
        guard developmentValidationOnly,
              notAProductionRouteAsset,
              schemaVersion == "gate4b.measurementFixture.1",
              coordinateFrame == "WallMetricMeters",
              wallID == Self.expectedWallID,
              currentWallID == wallID
        else {
            return []
        }
        let ids = landmarks.map(\.id)
        guard ids == Self.expectedIDs else { return [] }
        if landmarks.contains(where: { Self.forbiddenRuntimeIDs.contains($0.id) }) {
            return []
        }
        for landmark in landmarks {
            guard landmark.wallXYZMeters.count == 3,
                  landmark.wallXYZMeters.allSatisfy(\.isFinite)
            else { return [] }
        }
        return landmarks
    }
}

struct Gate4BRuntimeMarker: Codable, Equatable, Sendable {
    var landmarkID: String
    var wallXYZMeters: [Double]
    var predictedARWorldXYZMeters: [Double]
    var visibleByAlignmentState: Bool
}
