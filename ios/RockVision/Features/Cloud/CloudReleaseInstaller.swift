import Foundation

enum CloudReleasePhase: String, Equatable, Sendable {
    case notInstalled = "NOT_INSTALLED"
    case downloading = "DOWNLOADING"
    case verifying = "VERIFYING"
    case ready = "READY"
    case current = "CURRENT"
    case failed = "FAILED"
    case corrupt = "CORRUPT"
}

struct CloudInstallResult: Equatable, Sendable {
    var release: LocalValidatedRelease
    var optionalFailures: [String]
    var reusedExistingRelease: Bool
}

/// Downloads one frozen manifest.releaseId into staging, verifies, then atomically points CURRENT.
final class CloudReleaseInstaller: @unchecked Sendable {
    private let client: CloudAPIClient
    private let store: CloudReleaseStore

    init(client: CloudAPIClient, store: CloudReleaseStore) {
        self.client = client
        self.store = store
    }

    func installPublishedRelease(wallId: String) async throws -> CloudInstallResult {
        try CloudIdentifier.requireWallId(wallId)
        do {
            let manifest = try await client.fetchManifest(wallId: wallId)
            let frozenReleaseId = manifest.releaseId
            try CloudIdentifier.requireReleaseId(frozenReleaseId)

            switch store.inspectImmutableRelease(wallId: wallId, releaseId: frozenReleaseId) {
            case .valid(let existing):
                guard CloudAssetContract.sameImmutableRelease(existing.manifest, manifest) else {
                    throw CloudAssetError.immutableReleaseConflict
                }
                let adopted = try store.adoptExistingReleaseAsCurrent(wallId: wallId, releaseId: frozenReleaseId)
                return CloudInstallResult(release: adopted, optionalFailures: [], reusedExistingRelease: true)
            case .corrupt:
                throw CloudAssetError.storageFailure("local immutable release is corrupt")
            case .absent:
                break
            }

            let staging = try store.prepareStaging(wallId: wallId, releaseId: frozenReleaseId)
            try store.writeManifest(manifest, toReleaseRoot: staging)

            var optionalFailures: [String] = []
            for asset in manifest.assets {
                do {
                    let data = try await client.downloadAsset(
                        wallId: wallId,
                        releaseId: frozenReleaseId,
                        assetId: asset.assetId
                    )
                    try store.commitVerifiedAsset(data, descriptor: asset, toReleaseRoot: staging)
                } catch {
                    store.deleteAssetIfPresent(assetId: asset.assetId, inReleaseRoot: staging)
                    if asset.required {
                        store.discardStaging(wallId: wallId, releaseId: frozenReleaseId)
                        throw mappedFailure(error)
                    }
                    optionalFailures.append(asset.assetId)
                }
            }

            let activated = try store.activateVerifiedStaging(
                wallId: wallId,
                releaseId: frozenReleaseId,
                manifest: manifest
            )
            return CloudInstallResult(
                release: activated,
                optionalFailures: optionalFailures,
                reusedExistingRelease: false
            )
        } catch {
            throw mappedFailure(error)
        }
    }

    private func mappedFailure(_ error: Error) -> CloudAssetError {
        if let cloud = error as? CloudAssetError {
            return cloud
        }
        return .storageFailure("install failed")
    }
}
