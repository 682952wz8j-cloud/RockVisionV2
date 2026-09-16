import CryptoKit
import Foundation

/// Development-only Jinshidong local-test identity. Not a catalog / production release.
struct LocalTestRouteLegendItem: Equatable, Sendable {
    var routeId: String
    var routeName: String
    var grade: String
    var displayDraws: String
}

struct JinshidongLocalTestPackage: Equatable, Sendable {
    var database: ReferenceDatabase
    var provenance: ReferenceAssetProvenance
    var sim3: ValidatedSim3
    var routes: [VerifiedFrozenRoute]
    var legend: [LocalTestRouteLegendItem]
    var notACatalogRelease: Bool
    var notAProductionRelease: Bool
}

enum JinshidongLocalTestError: Error, Equatable, LocalizedError {
    case missingDirectory
    case missingFile(String)
    case identityMismatch(String)
    case sha256Mismatch(String)
    case sim3Invalid(String)
    case routeLoadFailed(String)

    var errorDescription: String? {
        switch self {
        case .missingDirectory:
            return "Jinshidong local-test assets not in bundle"
        case .missingFile(let name):
            return "missing Jinshidong local-test file \(name)"
        case .identityMismatch(let message), .sha256Mismatch(let message), .sim3Invalid(let message), .routeLoadFailed(let message):
            return message
        }
    }
}

enum JinshidongLocalTestAssets {
    static let directoryName = "JinshidongLocalTest"
    static let expectedWallId = "wall_jinshidong_01"
    static let expectedRunId = "wb_20260906T024519Z_6e08b5ff"
    static let expectedFingerprint = "32e9791497d9c9584acf455dc0942762f1d3e1993e9b4e682723408c1294350c"
    static let expectedReleaseId = "r000000"
    static let expectedDescriptorsSha256 = "120b38d654d059d431638abe0b48310aea240d4081a7a044598487d21b3bf49e"
    static let expectedLandmarksSha256 = "949a6ff0c4bdf4ed2df481ae9c5c7a50b3c6ca7996bdb7b13bd6009c9b7814f3"
    static let expectedSim3Sha256 = "c5a855eca2858b7bdf840c53974bfe2bb1daa05037d3d64b5f67f7b9c43486f8"
    static let expectedSim3Scale = 3.7780058545133315
    static let expectedRouteIds = [
        "jinshidong_lucky_baby",
        "jinshidong_shui_tai_shen",
        "jinshidong_mei_xiang_hao",
        "jinshidong_long_zhua_shou",
    ]

    struct Manifest: Codable, Equatable, Sendable {
        var schema: String
        var kind: String
        var wallId: String
        var wallBuildRunId: String
        var colmapModelFingerprint: String
        var releaseId: String
        var developmentLocalTestOnly: Bool
        var notAProductionRelease: Bool
        var notACatalogRelease: Bool
        var notAProductionRoutePackage: Bool
        var descriptorsPath: String
        var landmarksPath: String
        var sim3Path: String
        var packagePath: String
        var routeBundlePath: String
        var descriptorsSha256: String
        var landmarksSha256: String
        var sim3Sha256: String
    }

    struct RouteBundleFile: Codable, Equatable, Sendable {
        var schemaVersion: String
        var kind: String
        var developmentValidationOnly: Bool
        var notAProductionRoutePackage: Bool
        var notAStage5Release: Bool
        var wallId: String
        var wallBuildRunId: String
        var colmapModelFingerprint: String
        var routes: [RouteBundleEntry]
    }

    struct RouteBundleEntry: Codable, Equatable, Sendable {
        var routeId: String
        var routeName: String
        var grade: String
        var quickdraws: String
        var pointCount: Int
        var polylineSha256: String
        var fixturePath: String
    }

    struct PackageIdentity: Codable {
        var wallId: String
        var releaseId: String
        var notACatalogRelease: Bool?
        var packageState: String?
    }

    static func resourceDirectory(in bundle: Bundle) -> URL? {
        if let bundled = bundle.url(forResource: directoryName, withExtension: nil) {
            return bundled
        }
        let repo = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("Resources/\(directoryName)", isDirectory: true)
        if FileManager.default.fileExists(atPath: repo.appendingPathComponent("manifest.json").path) {
            return repo
        }
        return nil
    }

    static func loadManifest(from directory: URL) throws -> Manifest {
        let url = directory.appendingPathComponent("manifest.json")
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw JinshidongLocalTestError.missingFile("manifest.json")
        }
        return try JSONDecoder().decode(Manifest.self, from: try Data(contentsOf: url))
    }

    static func verifyIdentity(_ manifest: Manifest) throws {
        guard manifest.schema == "jinshidong.local_test.1",
              manifest.kind == "development_local_test_assets",
              manifest.wallId == expectedWallId,
              manifest.wallBuildRunId == expectedRunId,
              manifest.colmapModelFingerprint == expectedFingerprint,
              manifest.releaseId == expectedReleaseId,
              manifest.developmentLocalTestOnly,
              manifest.notAProductionRelease,
              manifest.notACatalogRelease,
              manifest.notAProductionRoutePackage,
              manifest.descriptorsSha256 == expectedDescriptorsSha256,
              manifest.landmarksSha256 == expectedLandmarksSha256,
              manifest.sim3Sha256 == expectedSim3Sha256
        else {
            throw JinshidongLocalTestError.identityMismatch("Jinshidong local-test manifest identity mismatch")
        }
    }

    static func sha256Hex(ofFile url: URL) throws -> String {
        let data = try Data(contentsOf: url, options: [.mappedIfSafe])
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func loadRoutes(from directory: URL) throws -> (routes: [VerifiedFrozenRoute], legend: [LocalTestRouteLegendItem], bundle: RouteBundleFile) {
        let manifest = try loadManifest(from: directory)
        try verifyIdentity(manifest)
        let bundleURL = directory.appendingPathComponent(manifest.routeBundlePath)
        guard FileManager.default.fileExists(atPath: bundleURL.path) else {
            throw JinshidongLocalTestError.missingFile(manifest.routeBundlePath)
        }
        let bundle = try JSONDecoder().decode(RouteBundleFile.self, from: try Data(contentsOf: bundleURL))
        guard bundle.schemaVersion == "gate5c.development.route.bundle.1",
              bundle.kind == "development_validation_route_bundle",
              bundle.developmentValidationOnly,
              bundle.notAProductionRoutePackage,
              bundle.notAStage5Release,
              bundle.wallId == expectedWallId,
              bundle.wallBuildRunId == expectedRunId,
              bundle.colmapModelFingerprint == expectedFingerprint,
              bundle.routes.map(\.routeId) == expectedRouteIds
        else {
            throw JinshidongLocalTestError.identityMismatch("Jinshidong route bundle is not the local-test set")
        }
        var routes: [VerifiedFrozenRoute] = []
        var legend: [LocalTestRouteLegendItem] = []
        for entry in bundle.routes {
            let fixtureName = URL(fileURLWithPath: entry.fixturePath).lastPathComponent
            let fixtureURL = directory.appendingPathComponent(fixtureName)
            guard let route = VerifiedFrozenRoute.loadLocalTest(from: fixtureURL, expectedWallId: expectedWallId) else {
                throw JinshidongLocalTestError.routeLoadFailed("failed to load \(fixtureName)")
            }
            guard route.routeId == entry.routeId,
                  route.routeName == entry.routeName,
                  route.grade == entry.grade,
                  route.displayDraws == entry.quickdraws,
                  route.polylineSha256 == entry.polylineSha256,
                  route.wallMetricMeters.count == entry.pointCount,
                  route.developmentValidationOnly,
                  route.wallId == expectedWallId
            else {
                throw JinshidongLocalTestError.identityMismatch("route \(entry.routeId) identity mismatch")
            }
            routes.append(route)
            legend.append(
                LocalTestRouteLegendItem(
                    routeId: route.routeId,
                    routeName: route.routeName ?? entry.routeName,
                    grade: route.grade ?? entry.grade,
                    displayDraws: route.displayDraws ?? entry.quickdraws
                )
            )
        }
        return (routes, legend, bundle)
    }

    static func loadSim3(from directory: URL) throws -> ValidatedSim3 {
        let manifest = try loadManifest(from: directory)
        try verifyIdentity(manifest)
        let url = directory.appendingPathComponent(manifest.sim3Path)
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw JinshidongLocalTestError.missingFile(manifest.sim3Path)
        }
        let actual = try sha256Hex(ofFile: url)
        guard actual == manifest.sim3Sha256 else {
            throw JinshidongLocalTestError.sha256Mismatch("\(manifest.sim3Path) SHA-256 \(actual) != \(manifest.sim3Sha256)")
        }
        return try DevelopmentSim3Loader.load(from: url, expectedScale: expectedSim3Scale)
    }

    static func load(from bundle: Bundle = .main) throws -> JinshidongLocalTestPackage {
        guard let directory = resourceDirectory(in: bundle) else {
            throw JinshidongLocalTestError.missingDirectory
        }
        return try load(from: directory)
    }

    static func load(from directory: URL) throws -> JinshidongLocalTestPackage {
        let manifest = try loadManifest(from: directory)
        try verifyIdentity(manifest)
        let packageURL = directory.appendingPathComponent(manifest.packagePath)
        guard FileManager.default.fileExists(atPath: packageURL.path) else {
            throw JinshidongLocalTestError.missingFile(manifest.packagePath)
        }
        let package = try JSONDecoder().decode(PackageIdentity.self, from: try Data(contentsOf: packageURL))
        guard package.wallId == expectedWallId,
              package.releaseId == expectedReleaseId,
              package.notACatalogRelease == true
        else {
            throw JinshidongLocalTestError.identityMismatch("localization package is not the Jinshidong local-test identity")
        }
        let descriptorsURL = directory.appendingPathComponent(manifest.descriptorsPath)
        let landmarksURL = directory.appendingPathComponent(manifest.landmarksPath)
        guard FileManager.default.fileExists(atPath: descriptorsURL.path) else {
            throw JinshidongLocalTestError.missingFile(manifest.descriptorsPath)
        }
        guard FileManager.default.fileExists(atPath: landmarksURL.path) else {
            throw JinshidongLocalTestError.missingFile(manifest.landmarksPath)
        }
        let descriptorsSha = try sha256Hex(ofFile: descriptorsURL)
        guard descriptorsSha == manifest.descriptorsSha256 else {
            throw JinshidongLocalTestError.sha256Mismatch("\(manifest.descriptorsPath) SHA-256 mismatch")
        }
        let landmarksSha = try sha256Hex(ofFile: landmarksURL)
        guard landmarksSha == manifest.landmarksSha256 else {
            throw JinshidongLocalTestError.sha256Mismatch("\(manifest.landmarksPath) SHA-256 mismatch")
        }
        let database = try ReferenceDatabase.load(descriptorsURL: descriptorsURL, landmarksURL: landmarksURL)
        guard database.wallId == expectedWallId else {
            throw JinshidongLocalTestError.identityMismatch("loaded landmarks wallId \(database.wallId) != \(expectedWallId)")
        }
        let sim3 = try loadSim3(from: directory)
        let loadedRoutes = try loadRoutes(from: directory)
        return JinshidongLocalTestPackage(
            database: database,
            provenance: ReferenceAssetProvenance(
                source: "jinshidongLocalTest",
                wallId: expectedWallId,
                releaseId: expectedReleaseId,
                descriptorsAssetId: "stage3-descriptors",
                landmarksAssetId: "stage3-landmarks",
                assetState: "available"
            ),
            sim3: sim3,
            routes: loadedRoutes.routes,
            legend: loadedRoutes.legend,
            notACatalogRelease: true,
            notAProductionRelease: true
        )
    }
}

/// Development adapter for production `S_wall_colmap` JSON (nested rotationMatrix).
/// Does not change `ValidatedSim3Loader` or the Jiulongfeng expected-scale contract.
enum DevelopmentSim3Loader {
    static func load(from url: URL, expectedScale: Double) throws -> ValidatedSim3 {
        let object = try JSONSerialization.jsonObject(with: try Data(contentsOf: url))
        guard let dict = object as? [String: Any] else {
            throw JinshidongLocalTestError.sim3Invalid("Sim(3) JSON is not an object")
        }
        guard (dict["status"] as? String) == "VALIDATED" else {
            throw JinshidongLocalTestError.sim3Invalid("Sim(3) status is not VALIDATED")
        }
        guard let name = dict["name"] as? String,
              let convention = dict["convention"] as? String,
              let scale = dict["scale"] as? Double,
              scale.isFinite, scale > 0,
              abs(scale - expectedScale) < 1e-9
        else {
            throw JinshidongLocalTestError.sim3Invalid("Sim(3) scale is not the Jinshidong local-test value")
        }
        guard let translation = dict["translationMeters"] as? [Double],
              translation.count == 3,
              translation.allSatisfy(\.isFinite)
        else {
            throw JinshidongLocalTestError.sim3Invalid("Sim(3) translationMeters invalid")
        }
        let rotation = try rotationMatrix(from: dict["rotationMatrix"])
        return ValidatedSim3(
            name: name,
            status: "VALIDATED",
            convention: convention,
            scale: scale,
            rotationMatrix: rotation,
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
        throw JinshidongLocalTestError.sim3Invalid("Sim(3) rotationMatrix schema unsupported")
    }
}
