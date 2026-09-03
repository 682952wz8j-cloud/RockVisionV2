import Foundation

/// Diagnostic provenance for the localization input. Does not affect matching math.
struct ReferenceAssetProvenance: Equatable, Sendable {
    var source: String
    var wallId: String
    var releaseId: String
    var descriptorsAssetId: String
    var landmarksAssetId: String
    var assetState: String

    static let unavailable = ReferenceAssetProvenance(
        source: "developmentFixture",
        wallId: "—",
        releaseId: "—",
        descriptorsAssetId: "—",
        landmarksAssetId: "—",
        assetState: "unavailable"
    )
}

struct ResolvedReferenceAssets: Equatable, Sendable {
    var descriptorsURL: URL
    var landmarksURL: URL
    var provenance: ReferenceAssetProvenance
}

struct LoadedReferenceAssets: Equatable, Sendable {
    var database: ReferenceDatabase
    var provenance: ReferenceAssetProvenance
    var descriptorsURL: URL
    var landmarksURL: URL
}

enum ReferenceAssetError: Error, Equatable, LocalizedError {
    case bundleUnavailable(String)
    case notInstalled
    case missingRequiredAsset(String)
    case missingRequiredSemanticType(String)
    case semanticTypeNotRequired(String)
    case duplicateSemanticType(String)
    case typeMismatch(assetId: String, expected: String, actual: String)
    case integrityRejected(String)

    var errorDescription: String? {
        switch self {
        case .bundleUnavailable(let reason):
            return reason
        case .notInstalled:
            return "cloud CURRENT release is not installed"
        case .missingRequiredAsset(let assetId):
            return "missing required cloud asset \(assetId)"
        case .missingRequiredSemanticType(let type):
            return "missing required semantic type \(type)"
        case .semanticTypeNotRequired(let type):
            return "semantic type \(type) is present but required=false"
        case .duplicateSemanticType(let type):
            return "duplicate semantic type \(type)"
        case .typeMismatch(let assetId, let expected, let actual):
            return "cloud asset \(assetId) type \(actual) != \(expected)"
        case .integrityRejected(let reason):
            return reason
        }
    }

    static func wrapping(_ error: Error) -> ReferenceAssetError {
        if let asset = error as? ReferenceAssetError {
            return asset
        }
        if let cloud = error as? CloudAssetError {
            switch cloud {
            case .notInstalled:
                return .notInstalled
            case .missingRequiredSemanticType(let type):
                return .missingRequiredSemanticType(type)
            case .semanticTypeNotRequired(let type):
                return .semanticTypeNotRequired(type)
            case .duplicateSemanticType(let type):
                return .duplicateSemanticType(type)
            default:
                return .integrityRejected(String(describing: cloud))
            }
        }
        return .integrityRejected(String(describing: error))
    }
}

/// Resolves local file URLs only. Parsing stays in `ReferenceDatabase.load`.
protocol ReferenceAssetResolving {
    func resolve() throws -> ResolvedReferenceAssets
}

enum ReferenceAssetLoader {
    static func load(from source: ReferenceAssetResolving) throws -> LoadedReferenceAssets {
        let resolved = try source.resolve()
        let database = try ReferenceDatabase.load(
            descriptorsURL: resolved.descriptorsURL,
            landmarksURL: resolved.landmarksURL
        )
        return LoadedReferenceAssets(
            database: database,
            provenance: resolved.provenance,
            descriptorsURL: resolved.descriptorsURL,
            landmarksURL: resolved.landmarksURL
        )
    }
}

/// Explicit selection. Cloud mode never falls back to Bundle.
enum ReferenceAssetSelection {
    case developmentFixture(bundle: Bundle = .main, directory: URL? = nil)
    case cloudValidatedRelease(wallId: String, service: CloudAssetService)
}

enum ReferenceAssetSession {
    static func load(_ selection: ReferenceAssetSelection) throws -> LoadedReferenceAssets {
        switch selection {
        case .developmentFixture(let bundle, let directory):
            return try ReferenceAssetLoader.load(
                from: BundleDevelopmentFixtureSource(bundle: bundle, directory: directory)
            )
        case .cloudValidatedRelease(let wallId, let service):
            return try ReferenceAssetLoader.load(
                from: CloudValidatedReleaseSource(wallId: wallId, service: service)
            )
        }
    }
}

struct BundleDevelopmentFixtureSource: ReferenceAssetResolving {
    var bundle: Bundle = .main
    var directory: URL?

    func resolve() throws -> ResolvedReferenceAssets {
        let dir: URL
        if let directory {
            dir = directory
        } else {
            guard let resource = DevelopmentFixture.resourceDirectory(in: bundle) else {
                throw ReferenceAssetError.bundleUnavailable("development fixture not in bundle")
            }
            dir = resource
        }
        let manifestURL = dir.appendingPathComponent("manifest.json")
        let files = FileManager.default
        if !files.fileExists(atPath: manifestURL.path) {
            throw ReferenceAssetError.bundleUnavailable("missing manifest.json")
        }
        let descriptorsProbe = dir.appendingPathComponent("descriptors.bin")
        let landmarksProbe = dir.appendingPathComponent("landmarks.json")
        if !files.fileExists(atPath: descriptorsProbe.path) || !files.fileExists(atPath: landmarksProbe.path) {
            throw ReferenceAssetError.bundleUnavailable("development fixture binaries not installed")
        }
        do {
            let verified = try DevelopmentFixture.verifiedAssetURLs(from: dir)
            return ResolvedReferenceAssets(
                descriptorsURL: verified.descriptors,
                landmarksURL: verified.landmarks,
                provenance: ReferenceAssetProvenance(
                    source: "developmentFixture",
                    wallId: verified.manifest.wallId,
                    releaseId: "—",
                    descriptorsAssetId: verified.manifest.descriptorsPath,
                    landmarksAssetId: verified.manifest.landmarksPath,
                    assetState: "available"
                )
            )
        } catch let matching as MatchingError {
            throw ReferenceAssetError.bundleUnavailable(matching.errorDescription ?? String(describing: matching))
        } catch {
            throw ReferenceAssetError.wrapping(error)
        }
    }
}

/// Uses only validated CURRENT APIs. Never builds on-disk cache locations.
struct CloudValidatedReleaseSource: ReferenceAssetResolving {
    var wallId: String
    var service: CloudAssetService

    func resolve() throws -> ResolvedReferenceAssets {
        let release: LocalValidatedRelease
        do {
            release = try service.localValidatedRelease(wallId: wallId)
        } catch {
            throw ReferenceAssetError.wrapping(error)
        }
        let stage3: (descriptors: WallAssetDescriptor, landmarks: WallAssetDescriptor)
        do {
            stage3 = try CloudStage3AssetSemantics.requiredStage3Assets(in: release.manifest)
        } catch {
            throw ReferenceAssetError.wrapping(error)
        }
        let descriptorsURL = try validatedURL(assetId: stage3.descriptors.assetId)
        let landmarksURL = try validatedURL(assetId: stage3.landmarks.assetId)
        return ResolvedReferenceAssets(
            descriptorsURL: descriptorsURL,
            landmarksURL: landmarksURL,
            provenance: ReferenceAssetProvenance(
                source: "cloud",
                wallId: release.wallId,
                releaseId: release.releaseId,
                descriptorsAssetId: stage3.descriptors.assetId,
                landmarksAssetId: stage3.landmarks.assetId,
                assetState: "available"
            )
        )
    }

    private func validatedURL(assetId: String) throws -> URL {
        do {
            return try service.localAssetURL(wallId: wallId, assetId: assetId)
        } catch {
            throw ReferenceAssetError.wrapping(error)
        }
    }
}
