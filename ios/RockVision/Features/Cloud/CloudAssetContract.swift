import Foundation

enum CloudAssetSchema {
    static let catalog = "cragpal.wall-catalog.v1"
    static let manifest = "cragpal.wall-manifest.v1"
}

enum CloudAssetError: Error, Equatable {
    case network
    case httpStatus(Int)
    case decoding
    case unsupportedSchema(String)
    case integrityFailure(String)
    case storageFailure(String)
    case notInstalled
    case offlineNoCache
    case invalidIdentifier(String)
    case immutableReleaseConflict
    case missingRequiredSemanticType(String)
    case semanticTypeNotRequired(String)
    case duplicateSemanticType(String)

    static func == (lhs: CloudAssetError, rhs: CloudAssetError) -> Bool {
        switch (lhs, rhs) {
        case (.network, .network),
             (.decoding, .decoding),
             (.notInstalled, .notInstalled),
             (.offlineNoCache, .offlineNoCache),
             (.immutableReleaseConflict, .immutableReleaseConflict):
            return true
        case (.httpStatus(let a), .httpStatus(let b)):
            return a == b
        case (.unsupportedSchema(let a), .unsupportedSchema(let b)),
             (.integrityFailure(let a), .integrityFailure(let b)),
             (.storageFailure(let a), .storageFailure(let b)),
             (.invalidIdentifier(let a), .invalidIdentifier(let b)),
             (.missingRequiredSemanticType(let a), .missingRequiredSemanticType(let b)),
             (.semanticTypeNotRequired(let a), .semanticTypeNotRequired(let b)),
             (.duplicateSemanticType(let a), .duplicateSemanticType(let b)):
            return a == b
        default:
            return false
        }
    }
}

struct WallCatalog: Codable, Equatable, Sendable {
    var schema: String
    var walls: [WallCatalogEntry]
}

struct WallCatalogEntry: Codable, Equatable, Sendable {
    var wallId: String
    var name: String
    var latestReleaseId: String
}

struct WallManifest: Codable, Equatable, Sendable {
    var schema: String
    var wallId: String
    var releaseId: String
    var createdAt: String
    var assets: [WallAssetDescriptor]
}

struct WallAssetDescriptor: Codable, Equatable, Sendable {
    var assetId: String
    var type: String
    var required: Bool
    var sha256: String
    var bytes: Int
}

/// Frozen Cloud Asset Contract v1 semantic `type` vocabulary.
/// `type` remains an opaque string on the wire; these values are the
/// official meanings. They are not filenames and not COS object keys.
enum CloudAssetType {
    static let referenceMap = "reference_map"
    static let referenceDescriptorsRVS1 = "reference_descriptors_rvs1"
    static let referenceLandmarksJSON = "reference_landmarks_json"
}

/// Stage 3 localization consumption: exactly one required asset of each
/// frozen semantic type. Resolution is by `type`, then the concrete `assetId`.
enum CloudStage3AssetSemantics {
    static func uniquelyRequiredAsset(type: String, in manifest: WallManifest) throws -> WallAssetDescriptor {
        let matches = manifest.assets.filter { $0.type == type }
        if matches.isEmpty {
            throw CloudAssetError.missingRequiredSemanticType(type)
        }
        if matches.count > 1 {
            throw CloudAssetError.duplicateSemanticType(type)
        }
        let asset = matches[0]
        if !asset.required {
            throw CloudAssetError.semanticTypeNotRequired(type)
        }
        return asset
    }

    static func requiredStage3Assets(
        in manifest: WallManifest
    ) throws -> (descriptors: WallAssetDescriptor, landmarks: WallAssetDescriptor) {
        let descriptors = try uniquelyRequiredAsset(
            type: CloudAssetType.referenceDescriptorsRVS1,
            in: manifest
        )
        let landmarks = try uniquelyRequiredAsset(
            type: CloudAssetType.referenceLandmarksJSON,
            in: manifest
        )
        return (descriptors, landmarks)
    }
}

enum CloudIdentifier {
    static func requireWallId(_ value: String) throws {
        try requireSafeId(value, label: "wallId")
    }

    static func requireAssetId(_ value: String) throws {
        try requireSafeId(value, label: "assetId")
    }

    static func requireReleaseId(_ value: String) throws {
        let pattern = "^r[0-9]{6}$"
        guard value.range(of: pattern, options: .regularExpression) != nil else {
            throw CloudAssetError.invalidIdentifier("releaseId")
        }
    }

    private static func requireSafeId(_ value: String, label: String) throws {
        if value.contains("..") || value.contains("/") || value.contains("\\")
            || value.contains(":") || value.contains("@") {
            throw CloudAssetError.invalidIdentifier(label)
        }
        let pattern = "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
        guard value.range(of: pattern, options: .regularExpression) != nil else {
            throw CloudAssetError.invalidIdentifier(label)
        }
    }
}

enum CloudAssetContract {
    static func decodeCatalog(_ data: Data) throws -> WallCatalog {
        let catalog: WallCatalog
        do {
            catalog = try JSONDecoder().decode(WallCatalog.self, from: data)
        } catch {
            throw CloudAssetError.decoding
        }
        guard catalog.schema == CloudAssetSchema.catalog else {
            throw CloudAssetError.unsupportedSchema(catalog.schema)
        }
        return catalog
    }

    static func decodeManifest(_ data: Data) throws -> WallManifest {
        let manifest: WallManifest
        do {
            manifest = try JSONDecoder().decode(WallManifest.self, from: data)
        } catch {
            throw CloudAssetError.decoding
        }
        guard manifest.schema == CloudAssetSchema.manifest else {
            throw CloudAssetError.unsupportedSchema(manifest.schema)
        }
        try CloudIdentifier.requireWallId(manifest.wallId)
        try CloudIdentifier.requireReleaseId(manifest.releaseId)
        for asset in manifest.assets {
            try CloudIdentifier.requireAssetId(asset.assetId)
        }
        return manifest
    }

    /// Semantic equality of an immutable published release. Asset order is not significant.
    static func sameImmutableRelease(_ lhs: WallManifest, _ rhs: WallManifest) -> Bool {
        guard lhs.schema == rhs.schema,
              lhs.wallId == rhs.wallId,
              lhs.releaseId == rhs.releaseId,
              lhs.createdAt == rhs.createdAt else {
            return false
        }
        let leftIds = lhs.assets.map(\.assetId)
        let rightIds = rhs.assets.map(\.assetId)
        if Set(leftIds).count != leftIds.count || Set(rightIds).count != rightIds.count {
            return lhs.assets == rhs.assets
        }
        guard Set(leftIds) == Set(rightIds) else {
            return false
        }
        let rightById = Dictionary(uniqueKeysWithValues: rhs.assets.map { ($0.assetId, $0) })
        for asset in lhs.assets {
            guard let other = rightById[asset.assetId] else {
                return false
            }
            if asset.type != other.type
                || asset.required != other.required
                || asset.bytes != other.bytes
                || asset.sha256.lowercased() != other.sha256.lowercased() {
                return false
            }
        }
        return true
    }
}
