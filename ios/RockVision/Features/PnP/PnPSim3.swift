import Foundation

/// Validated `S_wall_colmap` for metric C_wall / observation-depth and Gate 4A productionAlignment.
/// Does not enter PnP or confirmation.
struct ValidatedSim3: Equatable, Sendable {
    var name: String
    var status: String
    var convention: String
    var scale: Double
    var rotationMatrix: [[Double]]
    var translationMeters: [Double]

    /// X_wall = s * R * X_colmap + t
    func apply(_ colmap: [Double]) -> [Double]? {
        guard colmap.count == 3, colmap.allSatisfy(\.isFinite),
              PnPGeometry.isFiniteMatrix(rotationMatrix, rows: 3, cols: 3),
              PnPGeometry.isFiniteVec(translationMeters, count: 3),
              scale.isFinite, scale > 0
        else { return nil }
        let r = rotationMatrix
        let t = translationMeters
        let rx = r[0][0] * colmap[0] + r[0][1] * colmap[1] + r[0][2] * colmap[2]
        let ry = r[1][0] * colmap[0] + r[1][1] * colmap[1] + r[1][2] * colmap[2]
        let rz = r[2][0] * colmap[0] + r[2][1] * colmap[1] + r[2][2] * colmap[2]
        return [scale * rx + t[0], scale * ry + t[1], scale * rz + t[2]]
    }

    func meters(fromCamDepth cam: Double) -> Double? {
        guard cam.isFinite, scale.isFinite, scale > 0 else { return nil }
        return cam * scale
    }
}

enum Sim3LoadError: Error, Equatable {
    case missingResource
    case invalidStatus(String)
    case scaleMismatch(Double)
}

enum ValidatedSim3Loader {
    static let resourceName = "S_wall_colmap"

    static func load(from url: URL) throws -> ValidatedSim3 {
        let payload = try JSONDecoder().decode(File.self, from: try Data(contentsOf: url))
        guard payload.status == "VALIDATED" else {
            throw Sim3LoadError.invalidStatus(payload.status)
        }
        guard abs(payload.scale - PnPConfig.expectedSim3Scale) < 1e-9 else {
            throw Sim3LoadError.scaleMismatch(payload.scale)
        }
        return ValidatedSim3(
            name: payload.name,
            status: payload.status,
            convention: payload.convention,
            scale: payload.scale,
            rotationMatrix: payload.rotationMatrix,
            translationMeters: payload.translationMeters
        )
    }

    static func loadFromBundle(_ bundle: Bundle) -> ValidatedSim3? {
        guard let url = bundle.url(forResource: resourceName, withExtension: "json") else {
            return nil
        }
        return try? load(from: url)
    }

    private struct File: Codable {
        var name: String
        var status: String
        var convention: String
        var scale: Double
        var rotationMatrix: [[Double]]
        var translationMeters: [Double]
    }
}

/// Production release Sim(3). Scale is per-wall; not the Jiulongfeng bundle constant.
enum ProductionSim3Loader {
    static func load(from url: URL) throws -> ValidatedSim3 {
        let object = try JSONSerialization.jsonObject(with: try Data(contentsOf: url))
        guard let dict = object as? [String: Any] else {
            throw Sim3LoadError.invalidStatus("not-an-object")
        }
        guard (dict["status"] as? String) == "VALIDATED" else {
            throw Sim3LoadError.invalidStatus(String(describing: dict["status"]))
        }
        guard let name = dict["name"] as? String,
              let convention = dict["convention"] as? String,
              let scale = dict["scale"] as? Double,
              scale.isFinite, scale > 0
        else {
            throw Sim3LoadError.scaleMismatch(0)
        }
        guard let translation = dict["translationMeters"] as? [Double],
              translation.count == 3,
              translation.allSatisfy(\.isFinite)
        else {
            throw Sim3LoadError.invalidStatus("translation")
        }
        return ValidatedSim3(
            name: name,
            status: "VALIDATED",
            convention: convention,
            scale: scale,
            rotationMatrix: try rotationMatrix(from: dict["rotationMatrix"]),
            translationMeters: translation
        )
    }

    private static func rotationMatrix(from raw: Any?) throws -> [[Double]] {
        if let flat = raw as? [[Double]],
           flat.count == 3,
           flat.allSatisfy({ $0.count == 3 && $0.allSatisfy(\.isFinite) }) {
            return flat
        }
        if let nested = raw as? [String: Any],
           let values = nested["values"] as? [[Double]],
           values.count == 3,
           values.allSatisfy({ $0.count == 3 && $0.allSatisfy(\.isFinite) }) {
            return values
        }
        throw Sim3LoadError.invalidStatus("rotationMatrix")
    }
}
