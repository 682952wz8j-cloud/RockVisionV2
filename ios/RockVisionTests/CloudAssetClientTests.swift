import Foundation
import XCTest
@testable import RockVision

final class MockCloudTransport: CloudHTTPTransport, @unchecked Sendable {
    var catalogJSON: Data?
    var manifestJSONByWall: [String: Data] = [:]
    var assetBytes: [String: Data] = [:]
    var statusByPath: [String: Int] = [:]
    var networkError = false
    var failNetworkAfterAssetRequests: Int?
    private var assetRequestCount = 0
    private(set) var requestedPaths: [String] = []

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
        if path.hasSuffix("/manifest") {
            let wallId = path.split(separator: "/").dropFirst(2).first.map(String.init) ?? ""
            return try ok(manifestJSONByWall[wallId] ?? Data(), url)
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
        releaseId: String,
        bytes: Data,
        shaOverride: String? = nil,
        bytesOverride: Int? = nil
    ) -> Data {
        let sha = shaOverride ?? CloudIntegrity.sha256Hex(bytes)
        let count = bytesOverride ?? bytes.count
        return Data(
            """
            {"schema":"\(schema)","wallId":"\(wallId)","releaseId":"\(releaseId)","createdAt":"2026-09-02T15:30:00Z","assets":[{"assetId":"\(assetId)","type":"reference_map","required":true,"sha256":"\(sha)","bytes":\(count)}]}
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
}
