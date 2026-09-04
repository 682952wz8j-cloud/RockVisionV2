import Foundation
import SwiftUI

/// Minimal development surface for Cloud Asset Client v1. Not a product wall browser.
@MainActor
final class CloudDebugController: ObservableObject {
    static let jiulongfengDevWallId = "wall_jiulongfeng_01_dev"
    static let jiulongfengDevReleaseId = "r000001"

    @Published var catalogText = "—"
    @Published var releaseId = "—"
    @Published var phase = CloudReleasePhase.notInstalled.rawValue
    @Published var status = "idle"
    @Published var offlineCache = "none"
    @Published var lastError = ""
    @Published var explicitWallId = CloudDebugController.jiulongfengDevWallId
    @Published var explicitReleaseId = "—"
    @Published var explicitPhase = CloudReleasePhase.notInstalled.rawValue
    @Published var explicitSource = "explicit release"

    private let service: CloudAssetService
    private let exampleWallId = "wall_example_01"

    init(service: CloudAssetService? = nil) {
        if let service {
            self.service = service
        } else {
            self.service = (try? CloudAssetService.default()) ?? CloudAssetService(
                client: CloudAPIClient(configuration: .development),
                store: CloudReleaseStore(
                    rootURL: FileManager.default.temporaryDirectory.appendingPathComponent("CloudAssets-fallback", isDirectory: true)
                )
            )
        }
        refreshLocal()
    }

    func fetchCatalog() {
        lastError = ""
        status = "fetching catalog"
        Task {
            do {
                let catalog = try await service.fetchCatalog()
                let names = catalog.walls.map { "\($0.wallId) \($0.latestReleaseId)" }.joined(separator: ", ")
                catalogText = names.isEmpty ? "(empty)" : names
                status = "catalog ok"
                refreshLocal()
            } catch {
                status = "catalog failed"
                lastError = String(describing: error)
                refreshLocal()
            }
        }
    }

    func downloadExample() {
        lastError = ""
        phase = CloudReleasePhase.downloading.rawValue
        status = "downloading"
        Task {
            do {
                let result = try await service.refreshAndInstall(wallId: exampleWallId)
                releaseId = result.release.releaseId
                phase = CloudReleasePhase.current.rawValue
                status = result.optionalFailures.isEmpty
                    ? "READY \(result.release.releaseId)"
                    : "READY \(result.release.releaseId) optional failed: \(result.optionalFailures.joined(separator: ","))"
                refreshLocal()
            } catch {
                phase = CloudReleasePhase.failed.rawValue
                status = "FAILED"
                lastError = String(describing: error)
                refreshLocal()
            }
        }
    }

    func installJiulongfengDev() {
        lastError = ""
        explicitPhase = CloudReleasePhase.downloading.rawValue
        status = "installing explicit release"
        Task {
            do {
                let result = try await service.installRelease(
                    wallId: Self.jiulongfengDevWallId,
                    releaseId: Self.jiulongfengDevReleaseId
                )
                explicitWallId = result.release.wallId
                explicitReleaseId = result.release.releaseId
                explicitPhase = CloudReleasePhase.current.rawValue
                explicitSource = "explicit release"
                status = result.reusedExistingRelease
                    ? "CURRENT \(result.release.releaseId) source=explicit release reused"
                    : "CURRENT \(result.release.releaseId) source=explicit release"
                refreshLocal()
            } catch {
                explicitPhase = CloudReleasePhase.failed.rawValue
                status = "FAILED explicit release"
                lastError = String(describing: error)
                refreshLocal()
            }
        }
    }

    func refreshLocal() {
        if let current = service.localValidatedReleaseIfPresent(wallId: exampleWallId) {
            releaseId = current.releaseId
            offlineCache = "CURRENT \(current.releaseId)"
            if phase != CloudReleasePhase.downloading.rawValue {
                phase = CloudReleasePhase.current.rawValue
            }
        } else {
            offlineCache = "none"
            if phase != CloudReleasePhase.downloading.rawValue && phase != CloudReleasePhase.failed.rawValue {
                phase = CloudReleasePhase.notInstalled.rawValue
                releaseId = "—"
            }
        }
        if let current = service.localValidatedReleaseIfPresent(wallId: Self.jiulongfengDevWallId) {
            explicitWallId = current.wallId
            explicitReleaseId = current.releaseId
            explicitSource = "explicit release"
            if explicitPhase != CloudReleasePhase.downloading.rawValue {
                explicitPhase = CloudReleasePhase.current.rawValue
            }
        } else if explicitPhase != CloudReleasePhase.downloading.rawValue
            && explicitPhase != CloudReleasePhase.failed.rawValue {
            explicitReleaseId = "—"
            explicitPhase = CloudReleasePhase.notInstalled.rawValue
        }
    }
}

struct CloudDebugPanel: View {
    @ObservedObject var controller: CloudDebugController
    var cameraProvenance: ReferenceAssetProvenance = .unavailable
    var onSelectReferenceSourceBundle: () -> Void = {}
    var onSelectReferenceSourceCloudCurrent: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Cloud Client v1")
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
            let referenceSourceLabel: String = {
                guard cameraProvenance.assetState == "available" else { return "—" }
                if cameraProvenance.source == "developmentFixture" { return "Bundle" }
                if cameraProvenance.source == "cloud" { return "Cloud CURRENT" }
                return cameraProvenance.source
            }()
            Text("Reference source: \(referenceSourceLabel)")
            Text("wallId: \(cameraProvenance.wallId)")
            Text("releaseId: \(cameraProvenance.releaseId)")
            Text("asset state: \(cameraProvenance.assetState)")
            Text("catalog: \(controller.catalogText)")
            Text("release: \(controller.releaseId)")
            Text("state: \(controller.phase)")
            Text("cache: \(controller.offlineCache)")
            Text("explicit wallId: \(controller.explicitWallId)")
            Text("explicit releaseId: \(controller.explicitReleaseId)")
            Text("explicit source: \(controller.explicitSource)")
            Text("explicit state: \(controller.explicitPhase)")
            Text(controller.status)
            if !controller.lastError.isEmpty {
                Text(controller.lastError)
                    .foregroundStyle(.red)
            }
            HStack(spacing: 6) {
                cloudButton("Fetch Catalog", action: controller.fetchCatalog)
                cloudButton("Download / Update", action: controller.downloadExample)
            }
            cloudButton("Install Jiulongfeng Dev r000001", action: controller.installJiulongfengDev)
            HStack(spacing: 6) {
                cloudButton("Use Bundle Fixture", action: onSelectReferenceSourceBundle)
                cloudButton("Use Cloud CURRENT r000001", action: onSelectReferenceSourceCloudCurrent)
            }
        }
        .font(.system(size: 10, weight: .regular, design: .monospaced))
        .foregroundStyle(.white)
        .padding(8)
        .frame(maxWidth: 280, alignment: .leading)
        .background(Color.black.opacity(0.62), in: RoundedRectangle(cornerRadius: 6))
        .padding(.top, 10)
        .padding(.trailing, 10)
        .onAppear { controller.refreshLocal() }
    }

    private func cloudButton(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(.white)
                .padding(.horizontal, 6)
                .padding(.vertical, 5)
                .background(Color.white.opacity(0.2), in: RoundedRectangle(cornerRadius: 4))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
    }
}
