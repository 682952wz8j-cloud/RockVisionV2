import Combine
import Foundation

/// Production path: GPS → catalog → wallId → install CURRENT → processor load.
/// Diagnostic local-test remains on CloudDebugPanel only.
@MainActor
final class ProductionRuntimeController: ObservableObject {
    @Published var wallId = "—"
    @Published var cloudAssetsLoaded = false
    @Published var lastError: String?

    var processor: OpenCVFrameProcessor?
    var serviceOverride: CloudAssetService?
    var injectedCoordinate: (latitude: Double, longitude: Double)?
    var injectedCatalog: WallCatalog?

    private let locationProvider = WallLocationProvider()

    func start() async {
        do {
            let service = try serviceOverride ?? CloudAssetService.default()
            let catalog: WallCatalog
            if let injectedCatalog {
                catalog = injectedCatalog
            } else {
                catalog = try await service.fetchCatalog()
            }
            let coordinate: (latitude: Double, longitude: Double)
            if let injectedCoordinate {
                coordinate = injectedCoordinate
            } else if let live = await locationProvider.requestCoordinate() {
                coordinate = (live.latitude, live.longitude)
            } else {
                throw CloudAssetError.offlineNoCache
            }
            guard let selected = WallCandidateSelector.selectWallId(
                latitude: coordinate.latitude,
                longitude: coordinate.longitude,
                catalog: catalog
            ) else {
                wallId = "—"
                cloudAssetsLoaded = false
                lastError = "no wall in GPS range"
                processor?.clearProductionCloudRelease()
                return
            }
            if wallId != selected {
                processor?.clearProductionCloudRelease()
            }
            wallId = selected
            if injectedCatalog == nil {
                _ = try await service.refreshAndInstall(wallId: selected)
            }
            processor?.selectProductionCloudRelease(wallId: selected, service: service)
            let provenance = processor?.referenceAssetProvenance
            cloudAssetsLoaded = provenance?.source == "cloud"
                && provenance?.wallId == selected
                && provenance?.assetState == "available"
            if cloudAssetsLoaded {
                lastError = nil
            } else {
                lastError = provenance?.assetState
            }
        } catch {
            cloudAssetsLoaded = false
            lastError = (error as? LocalizedError)?.errorDescription ?? String(describing: error)
        }
    }
}
