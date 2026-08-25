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
