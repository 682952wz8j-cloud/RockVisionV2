import Foundation

/// Catalog GPS for coarse wall selection. Never a pose.
struct WallCatalogLocation: Equatable, Sendable {
    static let purpose = "wall_candidate_selection_only"

    var purpose: String
    var latitudeDeg: Double
    var longitudeDeg: Double
    var altitudeMeters: Double?
}

extension WallCatalogLocation: Codable {
    enum CodingKeys: String, CodingKey {
        case purpose
        case latitudeDeg
        case longitudeDeg
        case altitudeMeters
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        purpose = try container.decode(String.self, forKey: .purpose)
        guard purpose == Self.purpose else {
            throw DecodingError.dataCorruptedError(
                forKey: .purpose,
                in: container,
                debugDescription: "catalogLocation.purpose is not wall_candidate_selection_only"
            )
        }
        latitudeDeg = try container.decode(Double.self, forKey: .latitudeDeg)
        longitudeDeg = try container.decode(Double.self, forKey: .longitudeDeg)
        altitudeMeters = try container.decodeIfPresent(Double.self, forKey: .altitudeMeters)
        guard latitudeDeg.isFinite, latitudeDeg >= -90, latitudeDeg <= 90,
              longitudeDeg.isFinite, longitudeDeg >= -180, longitudeDeg <= 180
        else {
            throw DecodingError.dataCorruptedError(
                forKey: .latitudeDeg,
                in: container,
                debugDescription: "catalogLocation coordinates are invalid"
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(purpose, forKey: .purpose)
        try container.encode(latitudeDeg, forKey: .latitudeDeg)
        try container.encode(longitudeDeg, forKey: .longitudeDeg)
        try container.encodeIfPresent(altitudeMeters, forKey: .altitudeMeters)
    }
}

enum JinshidongCatalogLocation {
    static let wallId = "wall_jinshidong_01"
    static let displayName = "金狮洞"
    static let releaseId = "r000001"
    static let location = WallCatalogLocation(
        purpose: WallCatalogLocation.purpose,
        latitudeDeg: 30.623418333479282,
        longitudeDeg: 118.72756872205237,
        altitudeMeters: 211.89499999933113
    )
}

enum JiulongfengCatalogLocation {
    static let wallId = "wall_jiulongfeng_01"
    static let displayName = "九龙峰"
    static let releaseId = "r000001"
    static let routeId = "jiulongfeng_bai_qiang_ce_shi"
    static let location = WallCatalogLocation(
        purpose: WallCatalogLocation.purpose,
        latitudeDeg: 30.12974461019837,
        longitudeDeg: 118.01518161700322,
        altitudeMeters: 352.50399999973473
    )
}

/// GPS coarse wall selection only. Does not import Core Location.
enum WallCandidateSelector {
    static let maxDistanceMeters = 2500.0

    static func selectWallId(latitude: Double, longitude: Double, catalog: WallCatalog) -> String? {
        guard latitude.isFinite, longitude.isFinite,
              latitude >= -90, latitude <= 90,
              longitude >= -180, longitude <= 180
        else { return nil }
        var bestId: String?
        var bestDistance = maxDistanceMeters
        for entry in catalog.walls {
            guard let location = entry.catalogLocation else { continue }
            let distance = haversineMeters(
                lat1: latitude,
                lon1: longitude,
                lat2: location.latitudeDeg,
                lon2: location.longitudeDeg
            )
            if distance < bestDistance || (distance == bestDistance && (bestId == nil || entry.wallId < bestId!)) {
                if distance <= maxDistanceMeters {
                    bestId = entry.wallId
                    bestDistance = distance
                }
            }
        }
        return bestId
    }

    static func haversineMeters(lat1: Double, lon1: Double, lat2: Double, lon2: Double) -> Double {
        let radius = 6_371_000.0
        let phi1 = lat1 * .pi / 180
        let phi2 = lat2 * .pi / 180
        let dPhi = (lat2 - lat1) * .pi / 180
        let dLam = (lon2 - lon1) * .pi / 180
        let a = sin(dPhi / 2) * sin(dPhi / 2)
            + cos(phi1) * cos(phi2) * sin(dLam / 2) * sin(dLam / 2)
        return 2 * radius * asin(min(1, sqrt(a)))
    }
}
