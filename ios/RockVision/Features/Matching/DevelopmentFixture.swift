import CryptoKit
import Foundation

/// Frozen Gate 3C development fixture. Not a Wall Package.
enum DevelopmentFixture {
    static let directoryName = "DevelopmentFixture"
    static let expectedDescriptorsSha256 = "635982437d892870719591ae397cbfc61d6902084e5533114dc32953dc37c8a1"
    static let expectedLandmarksSha256 = "39b4292973e1495b91871fbd76a4989e5605107f9d09b61bb0513a63a4a371f6"
    static let expectedDescriptorCount = 47207
    static let expectedUniquePoint3D = 13771
    static let expectedReferenceImages = 47
    static let expectedWallId = "wall_jiulongfeng_01"

    struct Manifest: Codable, Equatable, Sendable {
        var schema: String
        var wallId: String
        var developmentFixtureOnly: Bool
        var notAWallPackage: Bool
        var sourceArtifact: String
        var descriptorsPath: String
        var landmarksPath: String
        var descriptorCount: Int
        var uniquePoint3D: Int
        var referenceImages: Int
        var descriptorsSha256: String
        var landmarksSha256: String
        var descriptorsBytes: Int
        var landmarksBytes: Int
        var matcherHotPath: [String]
        var xyzNotUsedInMatching: Bool
    }

    enum Status: Equatable {
        case inactive(String)
        case ready(ReferenceDatabase)
    }

    static func loadManifest(from url: URL) throws -> Manifest {
        try JSONDecoder().decode(Manifest.self, from: try Data(contentsOf: url))
    }

    static func sha256Hex(ofFile url: URL) throws -> String {
        let data = try Data(contentsOf: url, options: [.mappedIfSafe])
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func verifyIdentity(_ manifest: Manifest) throws {
        if manifest.descriptorsSha256 != expectedDescriptorsSha256
            || manifest.landmarksSha256 != expectedLandmarksSha256
            || manifest.descriptorCount != expectedDescriptorCount
            || manifest.uniquePoint3D != expectedUniquePoint3D
            || manifest.referenceImages != expectedReferenceImages
            || manifest.wallId != expectedWallId
            || manifest.developmentFixtureOnly != true
            || manifest.notAWallPackage != true
            || manifest.matcherHotPath != ["descriptor", "point3DID"]
            || manifest.xyzNotUsedInMatching != true {
            throw MatchingError.fixtureIdentityMismatch("development fixture manifest does not match frozen baseline_2px identity")
        }
    }

    static func loadVerified(from directory: URL) throws -> ReferenceDatabase {
        let manifest = try loadManifest(from: directory.appendingPathComponent("manifest.json"))
        try verifyIdentity(manifest)
        let descriptorsURL = directory.appendingPathComponent(manifest.descriptorsPath)
        let landmarksURL = directory.appendingPathComponent(manifest.landmarksPath)
        guard FileManager.default.fileExists(atPath: descriptorsURL.path) else {
            throw MatchingError.missingFixtureFile(manifest.descriptorsPath)
        }
        guard FileManager.default.fileExists(atPath: landmarksURL.path) else {
            throw MatchingError.missingFixtureFile(manifest.landmarksPath)
        }
        let descriptorsSha = try sha256Hex(ofFile: descriptorsURL)
        if descriptorsSha != manifest.descriptorsSha256 {
            throw MatchingError.sha256Mismatch(
                file: manifest.descriptorsPath,
                expected: manifest.descriptorsSha256,
                actual: descriptorsSha
            )
        }
        let landmarksSha = try sha256Hex(ofFile: landmarksURL)
        if landmarksSha != manifest.landmarksSha256 {
            throw MatchingError.sha256Mismatch(
                file: manifest.landmarksPath,
                expected: manifest.landmarksSha256,
                actual: landmarksSha
            )
        }
        let database = try ReferenceDatabase.load(descriptorsURL: descriptorsURL, landmarksURL: landmarksURL)
        if database.descriptorCount != manifest.descriptorCount {
            throw MatchingError.landmarkCountMismatch(
                descriptors: database.descriptorCount,
                landmarks: manifest.descriptorCount
            )
        }
        let unique = Set(database.point3dIds).count
        if unique != manifest.uniquePoint3D {
            throw MatchingError.uniquePoint3DMismatch(expected: manifest.uniquePoint3D, actual: unique)
        }
        if database.wallId != manifest.wallId
            || database.developmentFixtureOnly != true
            || database.notAWallPackage != true
            || database.matcherHotPath != ["descriptor", "point3DID"] {
            throw MatchingError.fixtureIdentityMismatch("loaded fixture is not the development-only baseline_2px artifact")
        }
        return database
    }

    static func loadIfPresent(from directory: URL) -> Status {
        let manifestURL = directory.appendingPathComponent("manifest.json")
        let descriptorsURL = directory.appendingPathComponent("descriptors.bin")
        let landmarksURL = directory.appendingPathComponent("landmarks.json")
        let files = FileManager.default
        if !files.fileExists(atPath: manifestURL.path) {
            return .inactive("missing manifest.json")
        }
        if !files.fileExists(atPath: descriptorsURL.path) || !files.fileExists(atPath: landmarksURL.path) {
            return .inactive("development fixture binaries not installed")
        }
        do {
            return .ready(try loadVerified(from: directory))
        } catch {
            return .inactive(error.localizedDescription)
        }
    }

    static func resourceDirectory(in bundle: Bundle) -> URL? {
        bundle.url(forResource: directoryName, withExtension: nil)
    }

    static func loadIfPresent(from bundle: Bundle = .main) -> Status {
        guard let directory = resourceDirectory(in: bundle) else {
            return .inactive("development fixture not in bundle")
        }
        return loadIfPresent(from: directory)
    }
}
