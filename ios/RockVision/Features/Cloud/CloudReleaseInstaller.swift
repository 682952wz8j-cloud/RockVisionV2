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
    private var client: CloudAPIClient
    private let store: CloudReleaseStore
    private let diagnostics: CloudInstallDiagnosticsStore?

    init(
        client: CloudAPIClient,
        store: CloudReleaseStore,
        diagnostics: CloudInstallDiagnosticsStore? = nil
    ) {
        self.client = client
        self.store = store
        self.diagnostics = diagnostics
    }

    func installPublishedRelease(wallId: String) async throws -> CloudInstallResult {
        try CloudIdentifier.requireWallId(wallId)
        let session = diagnostics?.beginSession()
        session?.setWallId(wallId)
        if let url = try? client.manifestURL(wallId: wallId) {
            session?.setManifestURL(url.absoluteString)
        }
        client.diagnosticSession = session
        defer { client.diagnosticSession = nil }
        do {
            let manifest = try await client.fetchManifest(wallId: wallId)
            return try await installFetchedManifest(wallId: wallId, manifest: manifest, session: session)
        } catch {
            throw persistMappedFailure(error, session: session, defaultStage: "fetch_manifest")
        }
    }

    /// Explicit immutable release. Does not consult catalog or `latestReleaseId`.
    func installExplicitRelease(wallId: String, releaseId: String) async throws -> CloudInstallResult {
        try CloudIdentifier.requireWallId(wallId)
        try CloudIdentifier.requireReleaseId(releaseId)
        let session = diagnostics?.beginSession()
        session?.setWallId(wallId)
        session?.setReleaseId(releaseId)
        if let url = try? client.releaseManifestURL(wallId: wallId, releaseId: releaseId) {
            session?.setManifestURL(url.absoluteString)
        }
        client.diagnosticSession = session
        defer { client.diagnosticSession = nil }
        do {
            let manifest = try await client.fetchManifest(wallId: wallId, releaseId: releaseId)
            guard manifest.wallId == wallId, manifest.releaseId == releaseId else {
                throw CloudAssetError.decoding
            }
            return try await installFetchedManifest(wallId: wallId, manifest: manifest, session: session)
        } catch {
            throw persistMappedFailure(error, session: session, defaultStage: "fetch_manifest")
        }
    }

    private func installFetchedManifest(
        wallId: String,
        manifest: WallManifest,
        session: CloudInstallDiagnosticSession?
    ) async throws -> CloudInstallResult {
        let frozenReleaseId = manifest.releaseId
        try CloudIdentifier.requireReleaseId(frozenReleaseId)
        session?.setReleaseId(frozenReleaseId)
        session?.registerRequiredAssets(manifest.assets.filter(\.required)) { assetId in
            (try? client.assetURL(wallId: wallId, releaseId: frozenReleaseId, assetId: assetId))?.absoluteString ?? ""
        }

        switch store.inspectImmutableRelease(wallId: wallId, releaseId: frozenReleaseId) {
        case .valid(let existing):
            guard CloudAssetContract.sameImmutableRelease(existing.manifest, manifest) else {
                throw CloudAssetError.immutableReleaseConflict
            }
            let adopted = try store.adoptExistingReleaseAsCurrent(wallId: wallId, releaseId: frozenReleaseId)
            return CloudInstallResult(release: adopted, optionalFailures: [], reusedExistingRelease: true)
        case .corrupt:
            let corrupt = CloudAssetError.storageFailure("local immutable release is corrupt")
            session?.recordFailure(stage: "inspect_existing", error: corrupt)
            throw corrupt
        case .absent:
            break
        }

        let staging = try store.prepareStaging(wallId: wallId, releaseId: frozenReleaseId)
        try store.writeManifest(manifest, toReleaseRoot: staging)

        var optionalFailures: [String] = []
        for asset in manifest.assets {
            var downloaded: Data?
            do {
                if asset.required {
                    session?.markDownloadStarted(assetId: asset.assetId)
                }
                let data = try await client.downloadAsset(
                    wallId: wallId,
                    releaseId: frozenReleaseId,
                    assetId: asset.assetId
                )
                downloaded = data
                try store.commitVerifiedAsset(data, descriptor: asset, toReleaseRoot: staging)
                if asset.required {
                    session?.recordAssetOutcome(assetId: asset.assetId, data: data, error: nil)
                }
            } catch {
                store.deleteAssetIfPresent(assetId: asset.assetId, inReleaseRoot: staging)
                if asset.required {
                    let mapped = mappedFailure(error)
                    session?.recordAssetOutcome(
                        assetId: asset.assetId,
                        data: downloaded,
                        error: mapped
                    )
                    session?.recordStagingInventory(store.stagingInventory(wallId: wallId, releaseId: frozenReleaseId))
                    session?.recordFailure(stage: failureStage(for: mapped), error: mapped)
                    store.discardStaging(wallId: wallId, releaseId: frozenReleaseId)
                    throw mapped
                }
                optionalFailures.append(asset.assetId)
            }
        }

        session?.markCurrentActivationStarted()
        do {
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
            let mapped = mappedFailure(error)
            session?.recordFailure(stage: "activate_current", error: mapped)
            throw mapped
        }
    }

    private func persistMappedFailure(
        _ error: Error,
        session: CloudInstallDiagnosticSession?,
        defaultStage: String
    ) -> CloudAssetError {
        let mapped = mappedFailure(error)
        if session?.snapshot().failureStage == nil {
            session?.recordFailure(stage: defaultStage, error: mapped)
        }
        if let session {
            diagnostics?.persistFailure(session)
        }
        return mapped
    }

    private func failureStage(for error: CloudAssetError) -> String {
        switch error {
        case .httpStatus, .network:
            return "download_asset"
        case .integrityFailure:
            return "verify_asset"
        default:
            return "download_asset"
        }
    }

    private func mappedFailure(_ error: Error) -> CloudAssetError {
        if let cloud = error as? CloudAssetError {
            return cloud
        }
        return .storageFailure("install failed")
    }
}
