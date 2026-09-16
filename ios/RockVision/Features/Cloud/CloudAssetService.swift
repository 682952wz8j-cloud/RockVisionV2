import Foundation

/// Boundary for future localization: consume local validated assets only, never the camera loop.
final class CloudAssetService: @unchecked Sendable {
    let client: CloudAPIClient
    let store: CloudReleaseStore
    let installer: CloudReleaseInstaller
    let diagnostics: CloudInstallDiagnosticsStore?

    init(
        client: CloudAPIClient,
        store: CloudReleaseStore,
        diagnostics: CloudInstallDiagnosticsStore? = nil
    ) {
        self.client = client
        self.store = store
        self.diagnostics = diagnostics
        self.installer = CloudReleaseInstaller(client: client, store: store, diagnostics: diagnostics)
    }

    static func `default`() throws -> CloudAssetService {
        CloudAssetService(
            client: CloudAPIClient(configuration: .default),
            store: try CloudReleaseStore.applicationSupportStore(),
            diagnostics: try? CloudInstallDiagnosticsStore.applicationSupportStore()
        )
    }

    func recordProductionRuntimeCatch(_ error: Error) {
        diagnostics?.recordProductionRuntimeCatch(error)
    }

    func localValidatedRelease(wallId: String) throws -> LocalValidatedRelease {
        try store.currentRelease(wallId: wallId)
    }

    func localValidatedReleaseIfPresent(wallId: String) -> LocalValidatedRelease? {
        store.currentReleaseIfPresent(wallId: wallId)
    }

    func localCurrentReleases() -> [LocalValidatedRelease] {
        store.localCurrentReleases()
    }

    func localAssetURL(wallId: String, assetId: String) throws -> URL {
        try store.validatedAssetURL(wallId: wallId, assetId: assetId)
    }

    func fetchCatalog() async throws -> WallCatalog {
        try await client.fetchCatalog()
    }

    func refreshAndInstall(wallId: String) async throws -> CloudInstallResult {
        try await installer.installPublishedRelease(wallId: wallId)
    }

    /// Debug/test only: install one known immutable release without catalog discovery.
    func installRelease(wallId: String, releaseId: String) async throws -> CloudInstallResult {
        try await installer.installExplicitRelease(wallId: wallId, releaseId: releaseId)
    }
}
