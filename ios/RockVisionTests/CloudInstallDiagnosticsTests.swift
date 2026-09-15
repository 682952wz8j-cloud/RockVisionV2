import Foundation
import XCTest
@testable import RockVision

final class CloudInstallDiagnosticsTests: XCTestCase {
    private let wallId = "wall_example_01"
    private let releaseId = "r000001"
    private let assetId = "reference-map"
    private let exampleBytes = Data("cragpal-example-reference-map-v1\n".utf8)

    func testHTTPErrorRecordsStatus() async throws {
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(bytes: exampleBytes)
        transport.statusByPath[assetPath(assetId)] = 503
        let (store, diagnostics, installer) = makeInstaller(transport: transport)
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected HTTP failure")
        } catch {
            XCTAssertEqual(error as? CloudAssetError, .httpStatus(503))
        }
        let report = try decodeSoleReport(in: diagnostics)
        XCTAssertEqual(report.schema, CloudInstallDiagnosticsSchema.name)
        XCTAssertEqual(report.wallId, wallId)
        XCTAssertEqual(report.releaseId, releaseId)
        XCTAssertEqual(
            report.manifestURL,
            "https://cloud.test\(convenienceManifestPath)"
        )
        XCTAssertEqual(report.failureStage, "download_asset")
        XCTAssertEqual(report.cloudAssetError?.errorCase, "httpStatus")
        XCTAssertEqual(report.cloudAssetError?.associatedValue, "503")
        XCTAssertEqual(report.currentActivationStarted, false)
        XCTAssertEqual(report.assets.count, 1)
        XCTAssertEqual(report.assets[0].assetId, assetId)
        XCTAssertEqual(report.assets[0].httpStatus, 503)
        XCTAssertEqual(report.assets[0].result, "http_error")
        XCTAssertEqual(report.assets[0].expectedBytes, exampleBytes.count)
        XCTAssertEqual(report.assets[0].url, "https://cloud.test\(assetPath(assetId))")
        XCTAssertNotNil(report.assets[0].downloadStartedAt)
        XCTAssertNil(store.currentReleaseIfPresent(wallId: wallId))
        XCTAssertFalse(reportJSON(in: diagnostics).contains("cragpal-example-reference-map"))
    }

    func testNetworkErrorPreservesUnderlyingNSError() async throws {
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(bytes: exampleBytes)
        let nsError = NSError(
            domain: NSURLErrorDomain,
            code: NSURLErrorTimedOut,
            userInfo: [NSLocalizedDescriptionKey: "The request timed out."]
        )
        transport.urlSessionErrorOnAssets = nsError
        let (_, diagnostics, installer) = makeInstaller(transport: transport)
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected network failure")
        } catch {
            XCTAssertEqual(error as? CloudAssetError, .network)
        }
        let report = try decodeSoleReport(in: diagnostics)
        XCTAssertEqual(report.failureStage, "download_asset")
        XCTAssertEqual(report.cloudAssetError?.errorCase, "network")
        XCTAssertEqual(report.assets[0].result, "network")
        XCTAssertEqual(report.urlSessionError?.domain, NSURLErrorDomain)
        XCTAssertEqual(report.urlSessionError?.code, NSURLErrorTimedOut)
        XCTAssertEqual(report.urlSessionError?.description, "The request timed out.")
        XCTAssertEqual(report.currentActivationStarted, false)
    }

    func testBytesMismatchLocatesAsset() async throws {
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(bytes: exampleBytes)
        let wrong = Data("short".utf8)
        transport.assetBytes[assetPath(assetId)] = wrong
        let (_, diagnostics, installer) = makeInstaller(transport: transport)
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected bytes mismatch")
        } catch {
            guard case .integrityFailure(let message) = error as? CloudAssetError else {
                return XCTFail("expected integrityFailure")
            }
            XCTAssertTrue(message.contains(assetId))
        }
        let report = try decodeSoleReport(in: diagnostics)
        XCTAssertEqual(report.failureStage, "verify_asset")
        XCTAssertEqual(report.cloudAssetError?.errorCase, "integrityFailure")
        XCTAssertEqual(report.cloudAssetError?.associatedValue, "bytes mismatch for \(assetId)")
        XCTAssertEqual(report.assets[0].assetId, assetId)
        XCTAssertEqual(report.assets[0].result, "bytes_mismatch")
        XCTAssertEqual(report.assets[0].expectedBytes, exampleBytes.count)
        XCTAssertEqual(report.assets[0].actualBytes, wrong.count)
        XCTAssertEqual(report.assets[0].actualSha256, CloudIntegrity.sha256Hex(wrong))
        XCTAssertEqual(report.assets[0].httpStatus, 200)
        XCTAssertNotEqual(report.assets[0].actualBytes, report.assets[0].expectedBytes)
    }

    func testSHAMismatchLocatesAsset() async throws {
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(bytes: exampleBytes)
        var wrong = exampleBytes
        wrong[wrong.startIndex] = wrong[wrong.startIndex] ^ 0xff
        XCTAssertEqual(wrong.count, exampleBytes.count)
        XCTAssertNotEqual(CloudIntegrity.sha256Hex(wrong), CloudIntegrity.sha256Hex(exampleBytes))
        transport.assetBytes[assetPath(assetId)] = wrong
        let (_, diagnostics, installer) = makeInstaller(transport: transport)
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected sha mismatch")
        } catch {
            guard case .integrityFailure(let message) = error as? CloudAssetError else {
                return XCTFail("expected integrityFailure")
            }
            XCTAssertTrue(message.contains(assetId))
            XCTAssertTrue(message.contains("sha256"))
        }
        let report = try decodeSoleReport(in: diagnostics)
        XCTAssertEqual(report.failureStage, "verify_asset")
        XCTAssertEqual(report.cloudAssetError?.errorCase, "integrityFailure")
        XCTAssertEqual(report.cloudAssetError?.associatedValue, "sha256 mismatch for \(assetId)")
        XCTAssertEqual(report.assets[0].assetId, assetId)
        XCTAssertEqual(report.assets[0].result, "sha256_mismatch")
        XCTAssertEqual(report.assets[0].expectedBytes, exampleBytes.count)
        XCTAssertEqual(report.assets[0].actualBytes, wrong.count)
        XCTAssertEqual(report.assets[0].expectedSha256, CloudIntegrity.sha256Hex(exampleBytes))
        XCTAssertEqual(report.assets[0].actualSha256, CloudIntegrity.sha256Hex(wrong))
        XCTAssertNotEqual(report.assets[0].actualSha256, report.assets[0].expectedSha256)
    }

    func testStagingInventoryIsRecordedBeforeDiscard() async throws {
        let first = exampleBytes
        let second = Data("cragpal-second-required-asset-v1\n".utf8)
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = twoRequiredManifest(first: first, second: second)
        transport.assetBytes[assetPath(assetId)] = first
        transport.statusByPath[assetPath("extra-map")] = 404
        let (store, diagnostics, installer) = makeInstaller(transport: transport)
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected required extra-map failure")
        } catch {
            XCTAssertEqual(error as? CloudAssetError, .httpStatus(404))
        }
        let report = try decodeSoleReport(in: diagnostics)
        XCTAssertEqual(report.failureStage, "download_asset")
        XCTAssertEqual(report.assets.map(\.assetId), [assetId, "extra-map"])
        XCTAssertEqual(report.assets[0].result, "ok")
        XCTAssertEqual(report.assets[1].result, "http_error")
        XCTAssertEqual(report.assets[1].httpStatus, 404)
        let paths = report.stagingBeforeDiscard?.map(\.path) ?? []
        XCTAssertTrue(paths.contains("manifest.json"), "staging inventory missing manifest.json: \(paths)")
        XCTAssertTrue(paths.contains("assets/\(assetId)"), "staging inventory missing first asset: \(paths)")
        XCTAssertFalse(paths.contains("assets/extra-map"))
        XCTAssertGreaterThan(report.stagingBeforeDiscard?.first(where: { $0.path == "assets/\(assetId)" })?.bytes ?? 0, 0)
        XCTAssertNil(store.currentReleaseIfPresent(wallId: wallId))
        let staging = try store.stagingURL(wallId: wallId, releaseId: releaseId)
        XCTAssertFalse(FileManager.default.fileExists(atPath: staging.path))
    }

    func testSuccessfulInstallBehaviorUnchangedAndDoesNotWriteDiagnostics() async throws {
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(bytes: exampleBytes)
        transport.assetBytes[assetPath(assetId)] = exampleBytes
        let (store, diagnostics, installer) = makeInstaller(transport: transport)
        let result = try await installer.installPublishedRelease(wallId: wallId)
        XCTAssertEqual(result.release.releaseId, releaseId)
        XCTAssertFalse(result.reusedExistingRelease)
        XCTAssertEqual(result.optionalFailures, [])
        let current = try store.currentRelease(wallId: wallId)
        XCTAssertEqual(current.releaseId, releaseId)
        XCTAssertEqual(try Data(contentsOf: current.fileURL(forAssetId: assetId)), exampleBytes)
        let pointer = try JSONDecoder().decode(
            CloudCurrentPointer.self,
            from: try Data(contentsOf: store.currentPointerURL(wallId: wallId))
        )
        XCTAssertEqual(pointer.state, "READY")
        XCTAssertEqual(pointer.releaseId, releaseId)
        XCTAssertEqual(try files(in: diagnostics.directory).count, 0)
    }

    @MainActor
    func testProductionRuntimeCatchRecordsFinalError() async throws {
        let transport = MockCloudTransport()
        let location = WallCatalogLocation(
            purpose: WallCatalogLocation.purpose,
            latitudeDeg: 30.13,
            longitudeDeg: 118.02,
            altitudeMeters: 350
        )
        let catalog = WallCatalog(
            schema: CloudAssetSchema.catalog,
            walls: [
                WallCatalogEntry(
                    wallId: wallId,
                    name: "Example Wall",
                    latestReleaseId: releaseId,
                    environment: .production,
                    catalogLocation: location
                )
            ]
        )
        transport.catalogJSON = try JSONEncoder().encode(catalog)
        transport.manifestJSONByWall[wallId] = manifestJSON(bytes: exampleBytes)
        transport.statusByPath[assetPath(assetId)] = 502
        let diagnostics = CloudInstallDiagnosticsStore(directory: uniqueRoot().appendingPathComponent("diag"))
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: CloudReleaseStore(rootURL: uniqueRoot()),
            diagnostics: diagnostics
        )
        let runtime = ProductionRuntimeController()
        runtime.serviceOverride = service
        runtime.injectedCoordinate = (location.latitudeDeg, location.longitudeDeg)
        await runtime.start()
        XCTAssertFalse(runtime.cloudAssetsLoaded)
        XCTAssertEqual(runtime.wallId, wallId)
        let report = try decodeSoleReport(in: diagnostics)
        XCTAssertEqual(report.failureStage, "download_asset")
        XCTAssertEqual(report.cloudAssetError?.errorCase, "httpStatus")
        XCTAssertEqual(report.cloudAssetError?.associatedValue, "502")
        XCTAssertEqual(report.productionRuntimeError, String(describing: CloudAssetError.httpStatus(502)))
        XCTAssertEqual(report.currentActivationStarted, false)
    }

    func testApplicationSupportDiagnosticsPathIsCopyable() throws {
        XCTAssertEqual(CloudInstallDiagnosticsSchema.directoryComponents, ["diagnostics", "cloud-install"])
        let source = try String(
            contentsOf: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/Cloud/CloudInstallDiagnostics.swift")
        )
        XCTAssertTrue(source.contains("applicationSupportDirectory"))
        XCTAssertTrue(source.contains("diagnostics"))
        XCTAssertTrue(source.contains("cloud-install"))
        let verify = try String(
            contentsOf: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("offline/verify.py")
        )
        XCTAssertFalse(verify.contains("cloud-install-diagnostics"))
        XCTAssertFalse(verify.contains("CloudInstallDiagnostics"))
    }

    private func makeInstaller(
        transport: MockCloudTransport
    ) -> (CloudReleaseStore, CloudInstallDiagnosticsStore, CloudReleaseInstaller) {
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let diagnostics = CloudInstallDiagnosticsStore(directory: uniqueRoot().appendingPathComponent("diag", isDirectory: true))
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: store,
            diagnostics: diagnostics
        )
        return (store, diagnostics, installer)
    }

    private func decodeSoleReport(in diagnostics: CloudInstallDiagnosticsStore) throws -> CloudInstallDiagnosticReport {
        let urls = try files(in: diagnostics.directory)
        XCTAssertEqual(urls.count, 1, "expected one session file, found \(urls.map(\.lastPathComponent))")
        return try JSONDecoder().decode(CloudInstallDiagnosticReport.self, from: try Data(contentsOf: urls[0]))
    }

    private func reportJSON(in diagnostics: CloudInstallDiagnosticsStore) -> String {
        let urls = (try? files(in: diagnostics.directory)) ?? []
        guard let url = urls.first, let data = try? Data(contentsOf: url) else { return "" }
        return String(decoding: data, as: UTF8.self)
    }

    private func files(in directory: URL) throws -> [URL] {
        guard FileManager.default.fileExists(atPath: directory.path) else { return [] }
        return try FileManager.default.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: nil
        )
        .filter { $0.pathExtension == "json" }
        .sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    private var convenienceManifestPath: String {
        CloudAPIConfiguration.usesDebugCatalogDiscovery
            ? "/v1/debug/walls/\(wallId)/manifest"
            : "/v1/walls/\(wallId)/manifest"
    }

    private func uniqueRoot() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("cloud-install-diag-\(UUID().uuidString)", isDirectory: true)
    }

    private func assetPath(_ id: String) -> String {
        "/v1/walls/\(wallId)/releases/\(releaseId)/assets/\(id)"
    }

    private func manifestJSON(bytes: Data) -> Data {
        let sha = CloudIntegrity.sha256Hex(bytes)
        return Data(
            """
            {"schema":"\(CloudAssetSchema.manifest)","wallId":"\(wallId)","releaseId":"\(releaseId)","createdAt":"2026-09-02T15:30:00Z","assets":[{"assetId":"\(assetId)","type":"reference_map","required":true,"sha256":"\(sha)","bytes":\(bytes.count)}]}
            """.utf8
        )
    }

    private func twoRequiredManifest(first: Data, second: Data) -> Data {
        let sha1 = CloudIntegrity.sha256Hex(first)
        let sha2 = CloudIntegrity.sha256Hex(second)
        return Data(
            """
            {"schema":"\(CloudAssetSchema.manifest)","wallId":"\(wallId)","releaseId":"\(releaseId)","createdAt":"2026-09-02T15:30:00Z","assets":[{"assetId":"\(assetId)","type":"reference_map","required":true,"sha256":"\(sha1)","bytes":\(first.count)},{"assetId":"extra-map","type":"reference_map","required":true,"sha256":"\(sha2)","bytes":\(second.count)}]}
            """.utf8
        )
    }
}
