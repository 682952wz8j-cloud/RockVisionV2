import Foundation
import XCTest
@testable import RockVision

final class MockCloudTransport: CloudHTTPTransport, @unchecked Sendable {
    var catalogJSON: Data?
    var manifestJSONByWall: [String: Data] = [:]
    var manifestJSONByRelease: [String: Data] = [:]
    var assetBytes: [String: Data] = [:]
    var statusByPath: [String: Int] = [:]
    var networkError = false
    var failNetworkAfterAssetRequests: Int?
    private var assetRequestCount = 0
    private(set) var requestedPaths: [String] = []

    func resetRequestedPaths() {
        requestedPaths = []
    }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        guard let url = request.url else { throw CloudAssetError.network }
        let path = url.path
        requestedPaths.append(path)
        if path.contains("/assets/") {
            assetRequestCount += 1
            if let limit = failNetworkAfterAssetRequests, assetRequestCount > limit {
                throw CloudAssetError.network
            }
        }
        if networkError {
            throw CloudAssetError.network
        }
        if let status = statusByPath[path] {
            return (Data("err".utf8), HTTPURLResponse(url: url, statusCode: status, httpVersion: nil, headerFields: nil)!)
        }
        if path == "/v1/walls" {
            return try ok(catalogJSON ?? Data(), url)
        }
        let parts = path.split(separator: "/").map(String.init)
        if parts.count == 6,
           parts[0] == "v1",
           parts[1] == "walls",
           parts[3] == "releases",
           parts[5] == "manifest" {
            let key = "\(parts[2])/\(parts[4])"
            if let payload = manifestJSONByRelease[key] {
                return try ok(payload, url)
            }
            return (Data(), HTTPURLResponse(url: url, statusCode: 404, httpVersion: nil, headerFields: nil)!)
        }
        if parts.count == 4,
           parts[0] == "v1",
           parts[1] == "walls",
           parts[3] == "manifest" {
            return try ok(manifestJSONByWall[parts[2]] ?? Data(), url)
        }
        if let payload = assetBytes[path] {
            return try ok(payload, url)
        }
        return (Data(), HTTPURLResponse(url: url, statusCode: 404, httpVersion: nil, headerFields: nil)!)
    }

    private func ok(_ data: Data, _ url: URL) throws -> (Data, URLResponse) {
        (data, HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!)
    }
}

final class CloudAssetClientTests: XCTestCase {
    private let wallId = "wall_example_01"
    private let release1 = "r000001"
    private let release2 = "r000002"
    private let assetId = "reference-map"
    private let exampleBytes = Data("cragpal-example-reference-map-v1\n".utf8)
    private let exampleBytesV2 = Data("cragpal-example-reference-map-v2\n".utf8)
    private let liveFixtureSHA = "02291c0368a9d1b3ce3e02459b50674ef6ab58d00888b9894356ef1f7aa43491"

    func testCatalogDecodePass() throws {
        let catalog = try CloudAssetContract.decodeCatalog(catalogJSON(latest: release1))
        XCTAssertEqual(catalog.schema, CloudAssetSchema.catalog)
        XCTAssertEqual(catalog.walls.first?.wallId, wallId)
        XCTAssertEqual(catalog.walls.first?.latestReleaseId, release1)
    }

    func testUnsupportedCatalogSchemaFails() {
        XCTAssertThrowsError(
            try CloudAssetContract.decodeCatalog(catalogJSON(schema: "cragpal.wall-catalog.v0", latest: release1))
        ) { error in
            XCTAssertEqual(error as? CloudAssetError, .unsupportedSchema("cragpal.wall-catalog.v0"))
        }
    }

    func testManifestDecodePass() throws {
        let manifest = try CloudAssetContract.decodeManifest(manifestJSON(releaseId: release1, bytes: exampleBytes))
        XCTAssertEqual(manifest.schema, CloudAssetSchema.manifest)
        XCTAssertEqual(manifest.releaseId, release1)
        XCTAssertEqual(manifest.assets.first?.assetId, assetId)
        XCTAssertEqual(manifest.assets.first?.bytes, exampleBytes.count)
    }

    func testUnsupportedManifestSchemaFails() {
        XCTAssertThrowsError(
            try CloudAssetContract.decodeManifest(manifestJSON(schema: "nope", releaseId: release1, bytes: exampleBytes))
        ) { error in
            XCTAssertEqual(error as? CloudAssetError, .unsupportedSchema("nope"))
        }
    }

    func testAssetURLUsesWallReleaseAndAssetIds() throws {
        let client = CloudAPIClient(configuration: .development, transport: MockCloudTransport())
        let url = try client.assetURL(wallId: wallId, releaseId: release1, assetId: assetId)
        XCTAssertEqual(
            url.absoluteString,
            "http://124.223.178.91/v1/walls/wall_example_01/releases/r000001/assets/reference-map"
        )
        XCTAssertTrue(url.path.contains("/releases/\(release1)/assets/\(assetId)"))
    }

    func testOldNonReleaseScopedURLIsNeverUsed() async throws {
        let transport = MockCloudTransport()
        transport.catalogJSON = catalogJSON(latest: release1)
        transport.manifestJSONByWall[wallId] = manifestJSON(releaseId: release1, bytes: exampleBytes)
        transport.assetBytes[assetPath(release1)] = exampleBytes
        let client = CloudAPIClient(configuration: .development, transport: transport)
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let installer = CloudReleaseInstaller(client: client, store: store)
        _ = try await installer.installPublishedRelease(wallId: wallId)
        XCTAssertFalse(transport.requestedPaths.contains { $0 == "/v1/walls/\(wallId)/assets/\(assetId)" })
        XCTAssertFalse(transport.requestedPaths.contains { $0.contains("/assets/") && !$0.contains("/releases/") })
        let source = try String(contentsOf: clientSourceURL())
        XCTAssertFalse(source.contains("/v1/walls/\\(wallId)/assets/\\(assetId)"))
        XCTAssertTrue(source.contains("releases"))
    }

    func testBytesExactMatchPass() throws {
        try CloudIntegrity.verify(
            data: exampleBytes,
            descriptor: descriptor(bytes: exampleBytes.count, sha: CloudIntegrity.sha256Hex(exampleBytes))
        )
    }

    func testBytesMismatchFail() {
        XCTAssertThrowsError(
            try CloudIntegrity.verify(
                data: exampleBytes,
                descriptor: descriptor(bytes: 37, sha: CloudIntegrity.sha256Hex(exampleBytes))
            )
        ) { error in
            guard case .integrityFailure = error as? CloudAssetError else {
                return XCTFail("expected integrityFailure")
            }
        }
    }

    func testSHA256ExactMatchPass() throws {
        try CloudIntegrity.verify(
            data: exampleBytes,
            descriptor: descriptor(bytes: exampleBytes.count, sha: CloudIntegrity.sha256Hex(exampleBytes))
        )
        XCTAssertEqual(liveFixtureSHA.count, 64)
    }

    func testSHA256MismatchFail() {
        XCTAssertThrowsError(
            try CloudIntegrity.verify(
                data: exampleBytes,
                descriptor: descriptor(bytes: exampleBytes.count, sha: String(repeating: "a", count: 64))
            )
        ) { error in
            guard case .integrityFailure = error as? CloudAssetError else {
                return XCTFail("expected integrityFailure")
            }
        }
    }

    func testRequiredAssetFailurePreventsActivation() async throws {
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(releaseId: release1, bytes: exampleBytes)
        transport.assetBytes[assetPath(release1)] = Data("wrong-bytes-wrong-bytes-wrong!!".utf8)
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: store
        )
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected failure")
        } catch {
            XCTAssertNil(store.currentReleaseIfPresent(wallId: wallId))
        }
    }

    func testOptionalAssetFailureDoesNotDestroyValidRequiredRelease() async throws {
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = twoAssetManifest(requiredBytes: exampleBytes, optionalRequired: false)
        transport.assetBytes[assetPath(release1)] = exampleBytes
        transport.statusByPath["/v1/walls/\(wallId)/releases/\(release1)/assets/notes"] = 404
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: store
        )
        let result = try await installer.installPublishedRelease(wallId: wallId)
        XCTAssertEqual(result.release.releaseId, release1)
        XCTAssertEqual(result.optionalFailures, ["notes"])
        XCTAssertEqual(try store.currentRelease(wallId: wallId).releaseId, release1)
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: store
        )
        XCTAssertThrowsError(try service.localAssetURL(wallId: wallId, assetId: "notes")) { error in
            XCTAssertEqual(error as? CloudAssetError, .notInstalled)
        }
    }

    func testSuccessfulReleaseBecomesCurrent() async throws {
        let result = try await installExample()
        XCTAssertEqual(result.release.releaseId, release1)
        XCTAssertEqual(result.release.manifest.releaseId, release1)
        let current = try result.store.currentRelease(wallId: wallId)
        XCTAssertEqual(current.releaseId, release1)
        let pointer = try JSONDecoder().decode(
            CloudCurrentPointer.self,
            from: try Data(contentsOf: result.store.currentPointerURL(wallId: wallId))
        )
        XCTAssertEqual(pointer.state, "READY")
        XCTAssertEqual(pointer.releaseId, release1)
    }

    func testFailedNewReleaseKeepsOldCurrent() async throws {
        let first = try await installExample()
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(releaseId: release2, bytes: exampleBytesV2)
        transport.assetBytes[assetPath(release2)] = Data("corrupt".utf8)
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: first.store
        )
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected failure")
        } catch {
            let current = try first.store.currentRelease(wallId: wallId)
            XCTAssertEqual(current.releaseId, release1)
            XCTAssertEqual(try Data(contentsOf: current.fileURL(forAssetId: assetId)), exampleBytes)
        }
    }

    func testInterruptedDownloadKeepsOldCurrent() async throws {
        let first = try await installExample()
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(releaseId: release2, bytes: exampleBytesV2)
        transport.networkError = true
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: first.store
        )
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected failure")
        } catch {
            XCTAssertEqual(try first.store.currentRelease(wallId: wallId).releaseId, release1)
        }
    }

    func testDownloadStaysPinnedWhenLatestChanges() async throws {
        let transport = MockCloudTransport()
        transport.catalogJSON = catalogJSON(latest: release2)
        transport.manifestJSONByWall[wallId] = manifestJSON(releaseId: release1, bytes: exampleBytes)
        transport.assetBytes[assetPath(release1)] = exampleBytes
        transport.assetBytes[assetPath(release2)] = exampleBytesV2
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: store
        )
        let result = try await installer.installPublishedRelease(wallId: wallId)
        XCTAssertEqual(result.release.releaseId, release1)
        XCTAssertTrue(transport.requestedPaths.contains(assetPath(release1)))
        XCTAssertFalse(transport.requestedPaths.contains(assetPath(release2)))
        XCTAssertEqual(try Data(contentsOf: result.release.fileURL(forAssetId: assetId)), exampleBytes)
    }

    func testRequiredAssetsFromTwoReleasesCannotBeCombined() async throws {
        let first = try await installExample()
        let r1URL = try first.store.releaseURL(wallId: wallId, releaseId: release1)
        let staging = try first.store.prepareStaging(wallId: wallId, releaseId: release2)
        var mixed = try JSONDecoder().decode(
            WallManifest.self,
            from: manifestJSON(releaseId: release2, bytes: exampleBytesV2)
        )
        mixed.assets = [
            WallAssetDescriptor(
                assetId: assetId,
                type: "reference_map",
                required: true,
                sha256: CloudIntegrity.sha256Hex(exampleBytesV2),
                bytes: exampleBytesV2.count
            ),
        ]
        try first.store.writeManifest(mixed, toReleaseRoot: staging)
        try FileManager.default.copyItem(
            at: r1URL.appendingPathComponent("assets").appendingPathComponent(assetId),
            to: staging.appendingPathComponent("assets").appendingPathComponent(assetId)
        )
        XCTAssertThrowsError(
            try first.store.activateVerifiedStaging(wallId: wallId, releaseId: release2, manifest: mixed)
        )
        XCTAssertEqual(try first.store.currentRelease(wallId: wallId).releaseId, release1)
    }

    func testOfflineExistingCurrentIsUsable() async throws {
        let installed = try await installExample()
        let service = CloudAssetService(
            client: CloudAPIClient(
                configuration: .custom(URL(string: "https://cloud.test")!),
                transport: {
                    let t = MockCloudTransport()
                    t.networkError = true
                    return t
                }()
            ),
            store: installed.store
        )
        let local = try service.localValidatedRelease(wallId: wallId)
        XCTAssertEqual(local.releaseId, release1)
        XCTAssertEqual(try Data(contentsOf: try service.localAssetURL(wallId: wallId, assetId: assetId)), exampleBytes)
    }

    func testOfflineWithNoCurrentFailsExplicitly() async {
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: MockCloudTransport()),
            store: store
        )
        XCTAssertThrowsError(try service.localValidatedRelease(wallId: wallId)) { error in
            XCTAssertEqual(error as? CloudAssetError, .notInstalled)
        }
        let transport = MockCloudTransport()
        transport.networkError = true
        let offlineService = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: store
        )
        do {
            _ = try await offlineService.fetchCatalog()
            XCTFail("expected network failure")
        } catch {
            XCTAssertEqual(error as? CloudAssetError, .network)
        }
    }

    func testCorruptStagingCannotBecomeCurrent() throws {
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let staging = try store.prepareStaging(wallId: wallId, releaseId: release1)
        let manifest = try CloudAssetContract.decodeManifest(manifestJSON(releaseId: release1, bytes: exampleBytes))
        try store.writeManifest(manifest, toReleaseRoot: staging)
        try store.writeAsset(Data("nope".utf8), assetId: assetId, toReleaseRoot: staging)
        XCTAssertThrowsError(try store.activateVerifiedStaging(wallId: wallId, releaseId: release1, manifest: manifest))
        XCTAssertNil(store.currentReleaseIfPresent(wallId: wallId))
    }

    func testCurrentPointerUpdatesOnlyAfterFullVerification() async throws {
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        XCTAssertNil(store.currentReleaseIfPresent(wallId: wallId))
        _ = try await installExample(store: store)
        let pointer = try JSONDecoder().decode(
            CloudCurrentPointer.self,
            from: try Data(contentsOf: store.currentPointerURL(wallId: wallId))
        )
        XCTAssertEqual(pointer.releaseId, release1)
        XCTAssertEqual(pointer.state, "READY")
    }

    func testBaseURLIsInjectable() throws {
        let custom = CloudAPIConfiguration.custom(URL(string: "https://example.invalid")!)
        let client = CloudAPIClient(configuration: custom, transport: MockCloudTransport())
        XCTAssertEqual(try client.catalogURL().absoluteString, "https://example.invalid/v1/walls")
        XCTAssertEqual(CloudAPIConfiguration.production.baseURL, CloudAPIConfiguration.productionHTTPSURL)
        XCTAssertNotEqual(CloudAPIConfiguration.production.baseURL, CloudAPIConfiguration.developmentTemporaryHTTPURL)
    }

    func testHTTPStatusIsNotSwallowedAsEmpty() async {
        let transport = MockCloudTransport()
        transport.statusByPath["/v1/walls"] = 503
        let client = CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport)
        do {
            _ = try await client.fetchCatalog()
            XCTFail("expected httpStatus")
        } catch {
            XCTAssertEqual(error as? CloudAssetError, .httpStatus(503))
        }
    }

    func testSameReleaseReuseDoesNotReplaceBytes() async throws {
        let first = try await installExample()
        let original = try Data(contentsOf: first.release.fileURL(forAssetId: assetId))
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(releaseId: release1, bytes: exampleBytes)
        transport.assetBytes[assetPath(release1)] = Data("should-not-be-written".utf8)
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: first.store
        )
        let result = try await installer.installPublishedRelease(wallId: wallId)
        XCTAssertTrue(result.reusedExistingRelease)
        XCTAssertEqual(result.release.releaseId, release1)
        XCTAssertEqual(try Data(contentsOf: first.release.fileURL(forAssetId: assetId)), original)
        XCTAssertFalse(transport.requestedPaths.contains { $0.contains("/assets/") })
        XCTAssertEqual(try first.store.currentRelease(wallId: wallId).releaseId, release1)
    }

    func testSameReleaseConflictFailsClosed() async throws {
        let first = try await installExample()
        let original = try Data(contentsOf: first.release.fileURL(forAssetId: assetId))
        let pointerBefore = try Data(contentsOf: first.store.currentPointerURL(wallId: wallId))
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(releaseId: release1, bytes: exampleBytesV2)
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: first.store
        )
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected conflict")
        } catch {
            XCTAssertEqual(error as? CloudAssetError, .immutableReleaseConflict)
        }
        XCTAssertEqual(try Data(contentsOf: first.release.fileURL(forAssetId: assetId)), original)
        XCTAssertEqual(try Data(contentsOf: first.store.currentPointerURL(wallId: wallId)), pointerBefore)
        XCTAssertFalse(transport.requestedPaths.contains { $0.contains("/assets/") })
    }

    func testCorruptSameIdReleaseFailsClosedWithoutReplacement() async throws {
        let first = try await installExample()
        let assetURL = first.release.fileURL(forAssetId: assetId)
        try Data("corrupt-local-release".utf8).write(to: assetURL)
        let corrupt = try Data(contentsOf: assetURL)
        let pointerBefore = try Data(contentsOf: first.store.currentPointerURL(wallId: wallId))
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(releaseId: release1, bytes: exampleBytes)
        transport.assetBytes[assetPath(release1)] = exampleBytes
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: first.store
        )
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected storage failure")
        } catch {
            XCTAssertEqual(error as? CloudAssetError, .storageFailure("local immutable release is corrupt"))
        }
        XCTAssertEqual(try Data(contentsOf: assetURL), corrupt)
        XCTAssertEqual(try Data(contentsOf: first.store.currentPointerURL(wallId: wallId)), pointerBefore)
        XCTAssertFalse(transport.requestedPaths.contains { $0.contains("/assets/") })
    }

    func testOptionalPostWriteIntegrityFailureDeletesFile() async throws {
        let notes = Data("note".utf8)
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let staging = try store.prepareStaging(wallId: wallId, releaseId: release1)
        let manifest = try CloudAssetContract.decodeManifest(
            twoAssetManifest(requiredBytes: exampleBytes, notes: notes)
        )
        try store.writeManifest(manifest, toReleaseRoot: staging)
        try store.commitVerifiedAsset(exampleBytes, descriptor: manifest.assets[0], toReleaseRoot: staging)
        try store.writeAsset(Data("bad!".utf8), assetId: "notes", toReleaseRoot: staging)
        let notesDesc = manifest.assets[1]
        XCTAssertFalse(try store.verifyOrDeleteAsset(descriptor: notesDesc, inReleaseRoot: staging))
        let notesURL = staging.appendingPathComponent("assets").appendingPathComponent("notes")
        XCTAssertFalse(FileManager.default.fileExists(atPath: notesURL.path))
        let activated = try store.activateVerifiedStaging(wallId: wallId, releaseId: release1, manifest: manifest)
        XCTAssertEqual(activated.releaseId, release1)
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: MockCloudTransport()),
            store: store
        )
        XCTAssertThrowsError(try service.localAssetURL(wallId: wallId, assetId: "notes")) { error in
            XCTAssertEqual(error as? CloudAssetError, .notInstalled)
        }
        XCTAssertEqual(try Data(contentsOf: try service.localAssetURL(wallId: wallId, assetId: assetId)), exampleBytes)
    }

    func testOptionalValidAssetIsRetrievable() async throws {
        let notes = Data("note".utf8)
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = twoAssetManifest(requiredBytes: exampleBytes, notes: notes)
        transport.assetBytes[assetPath(release1)] = exampleBytes
        transport.assetBytes["/v1/walls/\(wallId)/releases/\(release1)/assets/notes"] = notes
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: store
        )
        let result = try await installer.installPublishedRelease(wallId: wallId)
        XCTAssertEqual(result.optionalFailures, [])
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: store
        )
        let url = try service.localAssetURL(wallId: wallId, assetId: "notes")
        let data = try Data(contentsOf: url)
        XCTAssertEqual(data, notes)
        try CloudIntegrity.verify(data: data, descriptor: result.release.manifest.assets[1])
    }

    func testSHAOnlyUpdateFailureKeepsOldCurrent() async throws {
        let first = try await installExample()
        let original = try Data(contentsOf: first.release.fileURL(forAssetId: assetId))
        let payload = Data(repeating: 0x07, count: exampleBytesV2.count)
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(
            releaseId: release2,
            bytes: exampleBytesV2,
            shaOverride: CloudIntegrity.sha256Hex(exampleBytesV2),
            bytesOverride: exampleBytesV2.count
        )
        transport.assetBytes[assetPath(release2)] = payload
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: first.store
        )
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected integrity failure")
        } catch {
            guard case .integrityFailure = error as? CloudAssetError else {
                return XCTFail("expected integrityFailure, got \(error)")
            }
        }
        XCTAssertEqual(try first.store.currentRelease(wallId: wallId).releaseId, release1)
        XCTAssertEqual(try Data(contentsOf: first.release.fileURL(forAssetId: assetId)), original)
    }

    func testByteOnlyUpdateFailureKeepsOldCurrent() async throws {
        let first = try await installExample()
        let original = try Data(contentsOf: first.release.fileURL(forAssetId: assetId))
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(releaseId: release2, bytes: exampleBytesV2)
        transport.assetBytes[assetPath(release2)] = exampleBytesV2 + Data([0x00])
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: first.store
        )
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected integrity failure")
        } catch {
            guard case .integrityFailure = error as? CloudAssetError else {
                return XCTFail("expected integrityFailure, got \(error)")
            }
        }
        XCTAssertEqual(try first.store.currentRelease(wallId: wallId).releaseId, release1)
        XCTAssertEqual(try Data(contentsOf: first.release.fileURL(forAssetId: assetId)), original)
    }

    func testMidAssetNetworkFailureKeepsOldCurrent() async throws {
        let first = try await installExample()
        let extra = Data("second-required-asset".utf8)
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = twoRequiredManifest(releaseId: release2, first: exampleBytesV2, second: extra)
        transport.assetBytes[assetPath(release2)] = exampleBytesV2
        transport.assetBytes["/v1/walls/\(wallId)/releases/\(release2)/assets/extra-map"] = extra
        transport.failNetworkAfterAssetRequests = 1
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: first.store
        )
        do {
            _ = try await installer.installPublishedRelease(wallId: wallId)
            XCTFail("expected network failure")
        } catch {
            XCTAssertEqual(error as? CloudAssetError, .network)
        }
        XCTAssertEqual(try first.store.currentRelease(wallId: wallId).releaseId, release1)
        let r2 = try first.store.releaseURL(wallId: wallId, releaseId: release2)
        XCTAssertFalse(FileManager.default.fileExists(atPath: r2.path))
        let pointer = try JSONDecoder().decode(
            CloudCurrentPointer.self,
            from: try Data(contentsOf: first.store.currentPointerURL(wallId: wallId))
        )
        XCTAssertEqual(pointer.releaseId, release1)
    }

    func testExplicitManifestURLUsesWallAndReleaseIds() throws {
        let client = CloudAPIClient(configuration: .development, transport: MockCloudTransport())
        let url = try client.releaseManifestURL(wallId: wallId, releaseId: release1)
        XCTAssertEqual(
            url.absoluteString,
            "http://124.223.178.91/v1/walls/wall_example_01/releases/r000001/manifest"
        )
        XCTAssertTrue(url.path.contains("/v1/walls/\(wallId)/releases/\(release1)/manifest"))
        XCTAssertEqual(try client.manifestURL(wallId: wallId).path, "/v1/walls/\(wallId)/manifest")
    }

    func testExplicitManifestRequestPathDoesNotUseCatalogOrConvenienceRoute() async throws {
        let transport = MockCloudTransport()
        transport.manifestJSONByRelease["\(wallId)/\(release1)"] = manifestJSON(releaseId: release1, bytes: exampleBytes)
        let client = CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport)
        let manifest = try await client.fetchManifest(wallId: wallId, releaseId: release1)
        XCTAssertEqual(manifest.wallId, wallId)
        XCTAssertEqual(manifest.releaseId, release1)
        XCTAssertEqual(transport.requestedPaths, ["/v1/walls/\(wallId)/releases/\(release1)/manifest"])
        XCTAssertFalse(transport.requestedPaths.contains("/v1/walls"))
        XCTAssertFalse(transport.requestedPaths.contains("/v1/walls/\(wallId)/manifest"))
    }

    func testConvenienceFetchManifestPathUnchanged() async throws {
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(releaseId: release1, bytes: exampleBytes)
        let client = CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport)
        let manifest = try await client.fetchManifest(wallId: wallId)
        XCTAssertEqual(manifest.releaseId, release1)
        XCTAssertEqual(transport.requestedPaths, ["/v1/walls/\(wallId)/manifest"])
        XCTAssertFalse(transport.requestedPaths.contains("/v1/walls/\(wallId)/releases/\(release1)/manifest"))
    }

    func testExplicitManifestWallIdMismatchRejected() async {
        let transport = MockCloudTransport()
        transport.manifestJSONByRelease["\(wallId)/\(release1)"] = manifestJSON(
            wallId: "wall_other_01",
            releaseId: release1,
            bytes: exampleBytes
        )
        let client = CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport)
        do {
            _ = try await client.fetchManifest(wallId: wallId, releaseId: release1)
            XCTFail("expected mismatch")
        } catch {
            XCTAssertEqual(error as? CloudAssetError, .decoding)
        }
    }

    func testExplicitManifestReleaseIdMismatchRejected() async {
        let transport = MockCloudTransport()
        transport.manifestJSONByRelease["\(wallId)/\(release1)"] = manifestJSON(releaseId: release2, bytes: exampleBytes)
        let client = CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport)
        do {
            _ = try await client.fetchManifest(wallId: wallId, releaseId: release1)
            XCTFail("expected mismatch")
        } catch {
            XCTAssertEqual(error as? CloudAssetError, .decoding)
        }
    }

    func testExplicitReleaseInstallSucceedsWithoutCatalog() async throws {
        let transport = MockCloudTransport()
        transport.manifestJSONByRelease["\(wallId)/\(release1)"] = manifestJSON(releaseId: release1, bytes: exampleBytes)
        transport.assetBytes[assetPath(release1)] = exampleBytes
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: store
        )
        let result = try await service.installRelease(wallId: wallId, releaseId: release1)
        XCTAssertFalse(result.reusedExistingRelease)
        XCTAssertEqual(result.release.wallId, wallId)
        XCTAssertEqual(result.release.releaseId, release1)
        let current = try service.localValidatedRelease(wallId: wallId)
        XCTAssertEqual(current.releaseId, release1)
        let pointer = try JSONDecoder().decode(
            CloudCurrentPointer.self,
            from: try Data(contentsOf: store.currentPointerURL(wallId: wallId))
        )
        XCTAssertEqual(pointer.state, "READY")
        XCTAssertEqual(pointer.releaseId, release1)
        let data = try Data(contentsOf: try service.localAssetURL(wallId: wallId, assetId: assetId))
        XCTAssertEqual(data, exampleBytes)
        try CloudIntegrity.verify(data: data, descriptor: result.release.manifest.assets[0])
        XCTAssertFalse(transport.requestedPaths.contains("/v1/walls"))
        XCTAssertFalse(transport.requestedPaths.contains("/v1/walls/\(wallId)/manifest"))
        XCTAssertTrue(transport.requestedPaths.contains("/v1/walls/\(wallId)/releases/\(release1)/manifest"))
        XCTAssertTrue(transport.requestedPaths.contains(assetPath(release1)))
    }

    func testExplicitSameReleaseReuseDoesNotReplaceBytes() async throws {
        let first = try await installExplicitExample()
        let original = try Data(contentsOf: first.release.fileURL(forAssetId: assetId))
        let transport = MockCloudTransport()
        transport.manifestJSONByRelease["\(wallId)/\(release1)"] = manifestJSON(releaseId: release1, bytes: exampleBytes)
        transport.assetBytes[assetPath(release1)] = Data("should-not-be-written".utf8)
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: first.store
        )
        let result = try await service.installRelease(wallId: wallId, releaseId: release1)
        XCTAssertTrue(result.reusedExistingRelease)
        XCTAssertEqual(try Data(contentsOf: first.release.fileURL(forAssetId: assetId)), original)
        XCTAssertFalse(transport.requestedPaths.contains { $0.contains("/assets/") })
    }

    func testExplicitSameReleaseConflictFailsClosed() async throws {
        let first = try await installExplicitExample()
        let original = try Data(contentsOf: first.release.fileURL(forAssetId: assetId))
        let pointerBefore = try Data(contentsOf: first.store.currentPointerURL(wallId: wallId))
        let transport = MockCloudTransport()
        transport.manifestJSONByRelease["\(wallId)/\(release1)"] = manifestJSON(releaseId: release1, bytes: exampleBytesV2)
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: first.store
        )
        do {
            _ = try await service.installRelease(wallId: wallId, releaseId: release1)
            XCTFail("expected conflict")
        } catch {
            XCTAssertEqual(error as? CloudAssetError, .immutableReleaseConflict)
        }
        XCTAssertEqual(try Data(contentsOf: first.release.fileURL(forAssetId: assetId)), original)
        XCTAssertEqual(try Data(contentsOf: first.store.currentPointerURL(wallId: wallId)), pointerBefore)
        XCTAssertFalse(transport.requestedPaths.contains { $0.contains("/assets/") })
    }

    func testUnknownExplicitReleaseFails() async {
        let transport = MockCloudTransport()
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: CloudReleaseStore(rootURL: uniqueRoot())
        )
        do {
            _ = try await service.installRelease(wallId: wallId, releaseId: release1)
            XCTFail("expected unknown release")
        } catch {
            XCTAssertEqual(error as? CloudAssetError, .httpStatus(404))
        }
        XCTAssertFalse(transport.requestedPaths.contains("/v1/walls"))
    }

    func testNormalCatalogDoesNotIncludeDevelopmentWall() throws {
        let catalog = try CloudAssetContract.decodeCatalog(catalogJSON(latest: release1))
        XCTAssertEqual(catalog.walls.map(\.wallId), [wallId])
        XCTAssertFalse(catalog.walls.contains { $0.wallId == "wall_jiulongfeng_01_dev" })
    }

    func testDebugExplicitInstallDoesNotCallCatalog() throws {
        let source = try String(contentsOf: debugPanelSourceURL())
        XCTAssertTrue(source.contains("Install Jiulongfeng Dev r000001"))
        XCTAssertTrue(source.contains("installRelease("))
        XCTAssertTrue(source.contains("wall_jiulongfeng_01_dev"))
        XCTAssertTrue(source.contains("r000001"))
        XCTAssertTrue(source.contains("explicit release"))
        XCTAssertFalse(source.contains("ReferenceAssetSession.load(.cloudValidatedRelease"))
        let installRange = source.range(of: "func installJiulongfengDev()")!
        let refreshRange = source.range(of: "func refreshLocal()")!
        let installBody = String(source[installRange.lowerBound..<refreshRange.lowerBound])
        XCTAssertFalse(installBody.contains("fetchCatalog"))
        XCTAssertFalse(installBody.contains("refreshAndInstall"))
    }

    private struct Installed {
        var store: CloudReleaseStore
        var release: LocalValidatedRelease
    }

    private func installExample(store: CloudReleaseStore? = nil) async throws -> Installed {
        let transport = MockCloudTransport()
        transport.manifestJSONByWall[wallId] = manifestJSON(releaseId: release1, bytes: exampleBytes)
        transport.assetBytes[assetPath(release1)] = exampleBytes
        let usedStore = store ?? CloudReleaseStore(rootURL: uniqueRoot())
        let installer = CloudReleaseInstaller(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: usedStore
        )
        let result = try await installer.installPublishedRelease(wallId: wallId)
        return Installed(store: usedStore, release: result.release)
    }

    private func installExplicitExample(store: CloudReleaseStore? = nil) async throws -> Installed {
        let transport = MockCloudTransport()
        transport.manifestJSONByRelease["\(wallId)/\(release1)"] = manifestJSON(releaseId: release1, bytes: exampleBytes)
        transport.assetBytes[assetPath(release1)] = exampleBytes
        let usedStore = store ?? CloudReleaseStore(rootURL: uniqueRoot())
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: usedStore
        )
        let result = try await service.installRelease(wallId: wallId, releaseId: release1)
        return Installed(store: usedStore, release: result.release)
    }

    private func uniqueRoot() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("cloud-client-\(UUID().uuidString)", isDirectory: true)
    }

    private func assetPath(_ releaseId: String) -> String {
        "/v1/walls/\(wallId)/releases/\(releaseId)/assets/\(assetId)"
    }

    private func descriptor(bytes: Int, sha: String) -> WallAssetDescriptor {
        WallAssetDescriptor(assetId: assetId, type: "reference_map", required: true, sha256: sha, bytes: bytes)
    }

    private func catalogJSON(schema: String = CloudAssetSchema.catalog, latest: String) -> Data {
        Data(
            """
            {"schema":"\(schema)","walls":[{"wallId":"\(wallId)","name":"Example Wall","latestReleaseId":"\(latest)"}]}
            """.utf8
        )
    }

    private func manifestJSON(
        schema: String = CloudAssetSchema.manifest,
        wallId overrideWallId: String? = nil,
        releaseId: String,
        bytes: Data,
        shaOverride: String? = nil,
        bytesOverride: Int? = nil
    ) -> Data {
        let sha = shaOverride ?? CloudIntegrity.sha256Hex(bytes)
        let count = bytesOverride ?? bytes.count
        let id = overrideWallId ?? wallId
        return Data(
            """
            {"schema":"\(schema)","wallId":"\(id)","releaseId":"\(releaseId)","createdAt":"2026-09-02T15:30:00Z","assets":[{"assetId":"\(assetId)","type":"reference_map","required":true,"sha256":"\(sha)","bytes":\(count)}]}
            """.utf8
        )
    }

    private func twoAssetManifest(requiredBytes: Data, optionalRequired: Bool = false, notes: Data = Data("note".utf8)) -> Data {
        let sha = CloudIntegrity.sha256Hex(requiredBytes)
        let notesSha = CloudIntegrity.sha256Hex(notes)
        return Data(
            """
            {"schema":"\(CloudAssetSchema.manifest)","wallId":"\(wallId)","releaseId":"\(release1)","createdAt":"2026-09-02T15:30:00Z","assets":[{"assetId":"\(assetId)","type":"reference_map","required":true,"sha256":"\(sha)","bytes":\(requiredBytes.count)},{"assetId":"notes","type":"note","required":\(optionalRequired),"sha256":"\(notesSha)","bytes":\(notes.count)}]}
            """.utf8
        )
    }

    private func twoRequiredManifest(releaseId: String, first: Data, second: Data) -> Data {
        let sha1 = CloudIntegrity.sha256Hex(first)
        let sha2 = CloudIntegrity.sha256Hex(second)
        return Data(
            """
            {"schema":"\(CloudAssetSchema.manifest)","wallId":"\(wallId)","releaseId":"\(releaseId)","createdAt":"2026-09-02T15:30:00Z","assets":[{"assetId":"\(assetId)","type":"reference_map","required":true,"sha256":"\(sha1)","bytes":\(first.count)},{"assetId":"extra-map","type":"reference_map","required":true,"sha256":"\(sha2)","bytes":\(second.count)}]}
            """.utf8
        )
    }

    private func clientSourceURL() throws -> URL {
        let tests = URL(fileURLWithPath: #filePath)
        return tests
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("RockVision/Features/Cloud/CloudAPIClient.swift")
    }

    private func debugPanelSourceURL() throws -> URL {
        let tests = URL(fileURLWithPath: #filePath)
        return tests
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("RockVision/Features/Cloud/CloudDebugPanel.swift")
    }
}

@MainActor
final class CloudCatalogDiscoveryInstallTests: XCTestCase {
    private let exampleWallId = "wall_example_01"
    private let publisherWallId = "wall_publisher_e2e_01"
    private let jiulongfengWallId = "wall_jiulongfeng_01_dev"
    private let release1 = "r000001"
    private let release2 = "r000002"
    private let assetId = "reference-map"
    private let exampleBytes = Data("cragpal-example-reference-map-v1\n".utf8)
    private let publisherBytes = Data("cragpal-publisher-e2e-reference-map-v1\n".utf8)
    private let jiulongfengBytes = Data("cragpal-jiulongfeng-dev-reference-map-v1\n".utf8)

    func testFetchedCatalogRetainsBothReturnedEntries() async throws {
        let harness = makeHarness()
        let catalog = try await fetchCatalog(harness.controller)
        XCTAssertEqual(harness.controller.catalogWalls.map(\.wallId), [exampleWallId, publisherWallId])
        XCTAssertEqual(catalog.walls.map(\.wallId), [exampleWallId, publisherWallId])
        XCTAssertEqual(harness.controller.catalogWalls, catalog.walls)
        XCTAssertEqual(
            harness.controller.catalogWalls.first { $0.wallId == publisherWallId }?.name,
            "CragPal Publisher E2E Test Wall"
        )
        XCTAssertEqual(
            harness.controller.catalogWalls.first { $0.wallId == publisherWallId }?.latestReleaseId,
            release1
        )
    }

    func testInstallActionUsesWallIdFromFetchedCatalogEntry() async throws {
        let harness = makeHarness()
        _ = try await fetchCatalog(harness.controller)
        let entry = try XCTUnwrap(harness.controller.catalogWalls.first { $0.wallId == publisherWallId })
        let result = try await installDiscovered(harness.controller, entry)
        XCTAssertEqual(result.release.wallId, entry.wallId)
        XCTAssertEqual(harness.controller.discoveredWallId, entry.wallId)
        XCTAssertEqual(harness.controller.discoveredName, entry.name)
        XCTAssertEqual(harness.controller.catalogLatestReleaseId, entry.latestReleaseId)
        XCTAssertEqual(harness.controller.installedReleaseId, release1)
        XCTAssertEqual(harness.controller.discoveryCurrentWallId, publisherWallId)
        XCTAssertEqual(harness.controller.discoveryCurrentReleaseId, release1)
        XCTAssertTrue(harness.transport.requestedPaths.contains("/v1/walls/\(entry.wallId)/manifest"))
        XCTAssertFalse(harness.transport.requestedPaths.contains("/v1/walls/\(exampleWallId)/manifest"))
    }

    func testDiscoveryInstallUsesConvenienceManifestAndDoesNotSupplyReleaseId() async throws {
        let harness = makeHarness()
        _ = try await fetchCatalog(harness.controller)
        let entry = try XCTUnwrap(harness.controller.catalogWalls.first { $0.wallId == publisherWallId })
        _ = try await installDiscovered(harness.controller, entry)
        XCTAssertTrue(harness.transport.requestedPaths.contains("/v1/walls"))
        XCTAssertTrue(harness.transport.requestedPaths.contains("/v1/walls/\(publisherWallId)/manifest"))
        XCTAssertFalse(
            harness.transport.requestedPaths.contains("/v1/walls/\(publisherWallId)/releases/\(release1)/manifest")
        )
        XCTAssertTrue(
            harness.transport.requestedPaths.contains(
                "/v1/walls/\(publisherWallId)/releases/\(release1)/assets/\(assetId)"
            )
        )
        let source = try String(contentsOf: debugPanelSourceURL())
        let installRange = source.range(of: "func installDiscoveredAsync(_ entry: WallCatalogEntry)")!
        let panelRange = source.range(of: "struct CloudDebugPanel")!
        let installBody = String(source[installRange.lowerBound..<panelRange.lowerBound])
        XCTAssertTrue(installBody.contains("refreshAndInstall(wallId: entry.wallId)"))
        XCTAssertFalse(installBody.contains("installRelease("))
        XCTAssertFalse(installBody.contains("refreshAndInstall(wallId: entry.latestReleaseId"))
        XCTAssertFalse(installBody.contains("installRelease(wallId:"))
        XCTAssertFalse(source.contains("let publisherE2EWallId"))
        XCTAssertFalse(source.contains("\"wall_publisher_e2e_01\""))
    }

    func testManifestReturnedReleaseBecomesFrozenInstalledCurrent() async throws {
        let harness = makeHarness()
        _ = try await fetchCatalog(harness.controller)
        let entry = try XCTUnwrap(harness.controller.catalogWalls.first { $0.wallId == publisherWallId })
        let result = try await installDiscovered(harness.controller, entry)
        XCTAssertEqual(result.release.releaseId, release1)
        XCTAssertEqual(result.release.manifest.releaseId, release1)
        XCTAssertEqual(harness.controller.catalogLatestReleaseId, release1)
        XCTAssertEqual(harness.controller.installedReleaseId, release1)
        XCTAssertEqual(harness.controller.discoveryPhase, CloudReleasePhase.current.rawValue)
        XCTAssertEqual(harness.controller.discoveryReused, "NO")
        let current = try XCTUnwrap(harness.service.localValidatedReleaseIfPresent(wallId: publisherWallId))
        XCTAssertEqual(current.wallId, publisherWallId)
        XCTAssertEqual(current.releaseId, release1)
        let data = try Data(contentsOf: try harness.service.localAssetURL(wallId: publisherWallId, assetId: assetId))
        XCTAssertEqual(data, publisherBytes)
        try CloudIntegrity.verify(data: data, descriptor: result.release.manifest.assets[0])
    }

    func testFailedRequiredAssetDoesNotBecomeCurrentAndLeavesJiulongfeng() async throws {
        let harness = makeHarness()
        _ = try await harness.service.installRelease(wallId: jiulongfengWallId, releaseId: release1)
        harness.transport.assetBytes[publisherAssetPath(release1)] = Data("tampered-required-asset".utf8)
        _ = try await fetchCatalog(harness.controller)
        let entry = try XCTUnwrap(harness.controller.catalogWalls.first { $0.wallId == publisherWallId })
        let result = await harness.controller.installDiscoveredAsync(entry)
        XCTAssertNil(result)
        XCTAssertEqual(harness.controller.discoveryPhase, CloudReleasePhase.failed.rawValue)
        XCTAssertNil(harness.service.localValidatedReleaseIfPresent(wallId: publisherWallId))
        let jiulongfeng = try XCTUnwrap(harness.service.localValidatedReleaseIfPresent(wallId: jiulongfengWallId))
        XCTAssertEqual(jiulongfeng.wallId, jiulongfengWallId)
        XCTAssertEqual(jiulongfeng.releaseId, release1)
        XCTAssertEqual(
            try Data(contentsOf: try harness.service.localAssetURL(wallId: jiulongfengWallId, assetId: assetId)),
            jiulongfengBytes
        )
    }

    func testSuccessfulSyntheticInstallBecomesCurrentWithoutTouchingJiulongfeng() async throws {
        let harness = makeHarness()
        _ = try await harness.service.installRelease(wallId: jiulongfengWallId, releaseId: release1)
        let jiuBefore = try Data(contentsOf: harness.store.currentPointerURL(wallId: jiulongfengWallId))
        _ = try await fetchCatalog(harness.controller)
        let entry = try XCTUnwrap(harness.controller.catalogWalls.first { $0.wallId == publisherWallId })
        _ = try await installDiscovered(harness.controller, entry)
        let publisher = try XCTUnwrap(harness.service.localValidatedReleaseIfPresent(wallId: publisherWallId))
        XCTAssertEqual(publisher.wallId, publisherWallId)
        XCTAssertEqual(publisher.releaseId, release1)
        let jiulongfeng = try XCTUnwrap(harness.service.localValidatedReleaseIfPresent(wallId: jiulongfengWallId))
        XCTAssertEqual(jiulongfeng.wallId, jiulongfengWallId)
        XCTAssertEqual(jiulongfeng.releaseId, release1)
        XCTAssertEqual(try Data(contentsOf: harness.store.currentPointerURL(wallId: jiulongfengWallId)), jiuBefore)
        let currents = harness.service.localCurrentReleases()
        XCTAssertEqual(Set(currents.map(\.wallId)), [publisherWallId, jiulongfengWallId])
        XCTAssertTrue(harness.controller.localCurrentSummary.contains("\(publisherWallId)/\(release1) CURRENT"))
        XCTAssertTrue(harness.controller.localCurrentSummary.contains("\(jiulongfengWallId)/\(release1) CURRENT"))
    }

    func testTwoWallScopedCurrentPointersCoexist() async throws {
        let harness = makeHarness()
        _ = try await harness.service.installRelease(wallId: jiulongfengWallId, releaseId: release1)
        _ = try await harness.service.refreshAndInstall(wallId: publisherWallId)
        let currents = harness.service.localCurrentReleases()
        XCTAssertEqual(currents.count, 2)
        XCTAssertEqual(
            try JSONDecoder().decode(
                CloudCurrentPointer.self,
                from: try Data(contentsOf: harness.store.currentPointerURL(wallId: publisherWallId))
            ).releaseId,
            release1
        )
        XCTAssertEqual(
            try JSONDecoder().decode(
                CloudCurrentPointer.self,
                from: try Data(contentsOf: harness.store.currentPointerURL(wallId: jiulongfengWallId))
            ).releaseId,
            release1
        )
        XCTAssertNotEqual(
            try harness.store.currentPointerURL(wallId: publisherWallId).path,
            try harness.store.currentPointerURL(wallId: jiulongfengWallId).path
        )
    }

    func testRepeatedDiscoveryInstallReusesIdenticalImmutableRelease() async throws {
        let harness = makeHarness()
        _ = try await fetchCatalog(harness.controller)
        let entry = try XCTUnwrap(harness.controller.catalogWalls.first { $0.wallId == publisherWallId })
        let first = try await installDiscovered(harness.controller, entry)
        XCTAssertFalse(first.reusedExistingRelease)
        let original = try Data(contentsOf: first.release.fileURL(forAssetId: assetId))
        harness.transport.assetBytes[publisherAssetPath(release1)] = Data("should-not-be-written".utf8)
        harness.transport.resetRequestedPaths()
        let second = try await installDiscovered(harness.controller, entry)
        XCTAssertTrue(second.reusedExistingRelease)
        XCTAssertEqual(harness.controller.discoveryReused, "YES")
        XCTAssertEqual(try Data(contentsOf: first.release.fileURL(forAssetId: assetId)), original)
        XCTAssertFalse(harness.transport.requestedPaths.contains { $0.contains("/assets/") })
        XCTAssertTrue(harness.transport.requestedPaths.contains("/v1/walls/\(publisherWallId)/manifest"))
        XCTAssertFalse(
            harness.transport.requestedPaths.contains("/v1/walls/\(publisherWallId)/releases/\(release1)/manifest")
        )
    }

    func testCatalogLatestChangeDoesNotMutateOlderImmutableRelease() async throws {
        let harness = makeHarness()
        _ = try await fetchCatalog(harness.controller)
        let firstEntry = try XCTUnwrap(harness.controller.catalogWalls.first { $0.wallId == publisherWallId })
        let first = try await installDiscovered(harness.controller, firstEntry)
        let original = try Data(contentsOf: first.release.fileURL(forAssetId: assetId))
        harness.transport.catalogJSON = twoWallCatalogJSON(publisherLatest: release2)
        harness.transport.assetBytes[publisherAssetPath(release1)] = Data("mutated-r000001".utf8)
        _ = try await fetchCatalog(harness.controller)
        let updatedEntry = try XCTUnwrap(harness.controller.catalogWalls.first { $0.wallId == publisherWallId })
        XCTAssertEqual(updatedEntry.latestReleaseId, release2)
        let second = try await installDiscovered(harness.controller, updatedEntry)
        XCTAssertEqual(harness.controller.catalogLatestReleaseId, release2)
        XCTAssertEqual(harness.controller.installedReleaseId, release1)
        XCTAssertEqual(second.release.releaseId, release1)
        XCTAssertTrue(second.reusedExistingRelease)
        XCTAssertEqual(try Data(contentsOf: first.release.fileURL(forAssetId: assetId)), original)
        XCTAssertEqual(harness.controller.discoveryCurrentReleaseId, release1)
    }

    func testCameraLoopRemainsNetworkFreeAndDiscoveryDoesNotSelectLocalization() throws {
        let processor = try String(contentsOf: sourceFile("RockVision/Features/OpenCV/OpenCVFrameProcessor.swift"))
        XCTAssertFalse(processor.contains("fetchCatalog"))
        XCTAssertFalse(processor.contains("refreshAndInstall"))
        XCTAssertFalse(processor.contains("wall_publisher_e2e_01"))
        XCTAssertTrue(processor.contains("cloudCurrentJiulongfengDevR000001"))
        XCTAssertFalse(processor.contains("cloudCurrentPublisher"))
        let matching = try String(contentsOf: sourceFile("RockVision/Features/Matching/MatchingRuntime.swift"))
        XCTAssertFalse(matching.contains("fetchCatalog"))
        XCTAssertFalse(matching.contains("CloudAPIClient"))
        let panel = try String(contentsOf: debugPanelSourceURL())
        let installRange = panel.range(of: "func installDiscoveredAsync(_ entry: WallCatalogEntry)")!
        let panelRange = panel.range(of: "struct CloudDebugPanel")!
        let installBody = String(panel[installRange.lowerBound..<panelRange.lowerBound])
        XCTAssertFalse(installBody.contains("selectReferenceSource"))
        XCTAssertFalse(installBody.contains("ReferenceDatabase"))
        XCTAssertTrue(panel.contains("Use Cloud CURRENT r000001"))
        XCTAssertTrue(panel.contains("Install Jiulongfeng Dev r000001"))
        let content = try String(contentsOf: sourceFile("RockVision/App/ContentView.swift"))
        XCTAssertTrue(content.contains("selectReferenceSourceCloudCurrentJiulongfengDevR000001()"))
        XCTAssertFalse(content.contains("wall_publisher_e2e_01"))
    }

    func testExplicitJiulongfengDebugInstallPathUnchanged() throws {
        let source = try String(contentsOf: debugPanelSourceURL())
        XCTAssertTrue(source.contains("Install Jiulongfeng Dev r000001"))
        let installRange = source.range(of: "func installJiulongfengDev()")!
        let refreshRange = source.range(of: "func refreshLocal()")!
        let installBody = String(source[installRange.lowerBound..<refreshRange.lowerBound])
        XCTAssertTrue(installBody.contains("installRelease("))
        XCTAssertTrue(installBody.contains("Self.jiulongfengDevWallId"))
        XCTAssertTrue(installBody.contains("Self.jiulongfengDevReleaseId"))
        XCTAssertFalse(installBody.contains("fetchCatalog"))
        XCTAssertFalse(installBody.contains("refreshAndInstall"))
    }

    func testSyntheticWallIsNeverAutomaticallySelectedAsLocalizationSource() throws {
        let processor = OpenCVFrameProcessor()
        #if DEBUG
        XCTAssertEqual(processor.debugDesiredReferenceSourceMode, "bundleDevelopmentFixture")
        #else
        throw XCTSkip("Only meaningful in DEBUG test builds.")
        #endif
    }

    private func fetchCatalog(_ controller: CloudDebugController) async throws -> WallCatalog {
        let catalog = await controller.fetchCatalogAsync()
        return try XCTUnwrap(catalog)
    }

    private func installDiscovered(
        _ controller: CloudDebugController,
        _ entry: WallCatalogEntry
    ) async throws -> CloudInstallResult {
        let result = await controller.installDiscoveredAsync(entry)
        return try XCTUnwrap(result)
    }

    private struct Harness {
        var controller: CloudDebugController
        var service: CloudAssetService
        var store: CloudReleaseStore
        var transport: MockCloudTransport
    }

    private func makeHarness() -> Harness {
        let transport = MockCloudTransport()
        transport.catalogJSON = twoWallCatalogJSON(publisherLatest: release1)
        transport.manifestJSONByWall[exampleWallId] = manifestJSON(wallId: exampleWallId, bytes: exampleBytes)
        transport.manifestJSONByWall[publisherWallId] = manifestJSON(wallId: publisherWallId, bytes: publisherBytes)
        transport.manifestJSONByRelease["\(jiulongfengWallId)/\(release1)"] =
            manifestJSON(wallId: jiulongfengWallId, bytes: jiulongfengBytes)
        transport.assetBytes[assetPath(wallId: exampleWallId, releaseId: release1)] = exampleBytes
        transport.assetBytes[publisherAssetPath(release1)] = publisherBytes
        transport.assetBytes[assetPath(wallId: jiulongfengWallId, releaseId: release1)] = jiulongfengBytes
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: transport),
            store: store
        )
        return Harness(
            controller: CloudDebugController(service: service),
            service: service,
            store: store,
            transport: transport
        )
    }

    private func twoWallCatalogJSON(publisherLatest: String) -> Data {
        Data(
            """
            {"schema":"\(CloudAssetSchema.catalog)","walls":[{"wallId":"\(exampleWallId)","name":"Example Wall","latestReleaseId":"\(release1)"},{"wallId":"\(publisherWallId)","name":"CragPal Publisher E2E Test Wall","latestReleaseId":"\(publisherLatest)"}]}
            """.utf8
        )
    }

    private func manifestJSON(wallId: String, bytes: Data) -> Data {
        let sha = CloudIntegrity.sha256Hex(bytes)
        return Data(
            """
            {"schema":"\(CloudAssetSchema.manifest)","wallId":"\(wallId)","releaseId":"\(release1)","createdAt":"2026-09-02T15:30:00Z","assets":[{"assetId":"\(assetId)","type":"reference_map","required":true,"sha256":"\(sha)","bytes":\(bytes.count)}]}
            """.utf8
        )
    }

    private func assetPath(wallId: String, releaseId: String) -> String {
        "/v1/walls/\(wallId)/releases/\(releaseId)/assets/\(assetId)"
    }

    private func publisherAssetPath(_ releaseId: String) -> String {
        assetPath(wallId: publisherWallId, releaseId: releaseId)
    }

    private func uniqueRoot() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("cloud-d5-\(UUID().uuidString)", isDirectory: true)
    }

    private func debugPanelSourceURL() -> URL {
        sourceFile("RockVision/Features/Cloud/CloudDebugPanel.swift")
    }

    private func sourceFile(_ relative: String) -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(relative)
    }
}
