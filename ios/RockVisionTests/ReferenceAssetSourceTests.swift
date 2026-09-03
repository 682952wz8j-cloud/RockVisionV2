import Foundation
import XCTest
@testable import RockVision

final class ReferenceAssetSourceTests: XCTestCase {
    private let wallId = "wall_bridge_01"
    private let releaseId = "r000001"
    /// Opaque identifiers — not filenames and not frozen Stage 3 names.
    private let descriptorsAssetId = "alpha-pack"
    private let landmarksAssetId = "omega-meta"

    func testBundleSourceResolvesSameFilesAsDevelopmentFixture() throws {
        let dir = fixtureDirectoryFromSource()
        try XCTSkipUnless(
            FileManager.default.fileExists(atPath: dir.appendingPathComponent("descriptors.bin").path)
                && FileManager.default.fileExists(atPath: dir.appendingPathComponent("landmarks.json").path),
            "run ios/scripts/install_development_fixture.sh"
        )
        let verified = try DevelopmentFixture.verifiedAssetURLs(from: dir)
        let loaded = try ReferenceAssetSession.load(.developmentFixture(directory: dir))
        XCTAssertEqual(loaded.descriptorsURL.standardizedFileURL, verified.descriptors.standardizedFileURL)
        XCTAssertEqual(loaded.landmarksURL.standardizedFileURL, verified.landmarks.standardizedFileURL)
        XCTAssertEqual(loaded.provenance.source, "developmentFixture")
        XCTAssertEqual(loaded.provenance.wallId, DevelopmentFixture.expectedWallId)
        XCTAssertEqual(loaded.provenance.releaseId, "—")
        XCTAssertEqual(loaded.provenance.assetState, "available")
        let direct = try DevelopmentFixture.loadVerified(from: dir)
        XCTAssertEqual(loaded.database.descriptorCount, direct.descriptorCount)
        XCTAssertEqual(loaded.database.wallId, direct.wallId)
        XCTAssertEqual(loaded.database.point3dIds, direct.point3dIds)
    }

    func testExactlyOneRequiredSemanticPairResolves() throws {
        let env = try installStage3Release()
        let loaded = try ReferenceAssetSession.load(
            .cloudValidatedRelease(wallId: wallId, service: env.service)
        )
        XCTAssertEqual(loaded.provenance.source, "cloud")
        XCTAssertEqual(loaded.provenance.wallId, wallId)
        XCTAssertEqual(loaded.provenance.releaseId, releaseId)
        XCTAssertEqual(loaded.provenance.descriptorsAssetId, descriptorsAssetId)
        XCTAssertEqual(loaded.provenance.landmarksAssetId, landmarksAssetId)
        XCTAssertEqual(loaded.provenance.assetState, "available")
        XCTAssertFalse(loaded.descriptorsURL.path.contains("/staging/"))
        XCTAssertEqual(
            loaded.descriptorsURL,
            try env.service.localAssetURL(wallId: wallId, assetId: descriptorsAssetId)
        )
        XCTAssertEqual(
            loaded.landmarksURL,
            try env.service.localAssetURL(wallId: wallId, assetId: landmarksAssetId)
        )
    }

    func testAssetIdsAreOpaqueAndNotFilenames() throws {
        XCTAssertNotEqual(descriptorsAssetId, "descriptors.bin")
        XCTAssertNotEqual(landmarksAssetId, "landmarks.json")
        XCTAssertNotEqual(descriptorsAssetId, "stage3-descriptors")
        XCTAssertNotEqual(landmarksAssetId, "stage3-landmarks")
        let env = try installStage3Release(
            descriptorsId: "pkgA42",
            landmarksId: "pkgB99"
        )
        let loaded = try ReferenceAssetSession.load(
            .cloudValidatedRelease(wallId: wallId, service: env.service)
        )
        XCTAssertEqual(loaded.provenance.descriptorsAssetId, "pkgA42")
        XCTAssertEqual(loaded.provenance.landmarksAssetId, "pkgB99")
        XCTAssertFalse(loaded.descriptorsURL.lastPathComponent.contains("."))
        XCTAssertFalse(loaded.landmarksURL.lastPathComponent.contains("."))
    }

    func testMissingDescriptorsSemanticTypeFails() throws {
        let env = try installStage3Release(includeDescriptors: false)
        XCTAssertThrowsError(
            try ReferenceAssetSession.load(.cloudValidatedRelease(wallId: wallId, service: env.service))
        ) { error in
            XCTAssertEqual(
                error as? ReferenceAssetError,
                .missingRequiredSemanticType(CloudAssetType.referenceDescriptorsRVS1)
            )
        }
    }

    func testMissingLandmarksSemanticTypeFails() throws {
        let env = try installStage3Release(includeLandmarks: false)
        XCTAssertThrowsError(
            try ReferenceAssetSession.load(.cloudValidatedRelease(wallId: wallId, service: env.service))
        ) { error in
            XCTAssertEqual(
                error as? ReferenceAssetError,
                .missingRequiredSemanticType(CloudAssetType.referenceLandmarksJSON)
            )
        }
    }

    func testDescriptorsRequiredFalseFails() throws {
        let env = try installStage3Release(descriptorsRequired: false)
        XCTAssertThrowsError(
            try ReferenceAssetSession.load(.cloudValidatedRelease(wallId: wallId, service: env.service))
        ) { error in
            XCTAssertEqual(
                error as? ReferenceAssetError,
                .semanticTypeNotRequired(CloudAssetType.referenceDescriptorsRVS1)
            )
        }
    }

    func testLandmarksRequiredFalseFails() throws {
        let env = try installStage3Release(landmarksRequired: false)
        XCTAssertThrowsError(
            try ReferenceAssetSession.load(.cloudValidatedRelease(wallId: wallId, service: env.service))
        ) { error in
            XCTAssertEqual(
                error as? ReferenceAssetError,
                .semanticTypeNotRequired(CloudAssetType.referenceLandmarksJSON)
            )
        }
    }

    func testDuplicateDescriptorsSemanticTypeFailsClosed() throws {
        let env = try installStage3Release(duplicateDescriptors: true)
        XCTAssertThrowsError(
            try ReferenceAssetSession.load(.cloudValidatedRelease(wallId: wallId, service: env.service))
        ) { error in
            XCTAssertEqual(
                error as? ReferenceAssetError,
                .duplicateSemanticType(CloudAssetType.referenceDescriptorsRVS1)
            )
        }
    }

    func testDuplicateLandmarksSemanticTypeFailsClosed() throws {
        let env = try installStage3Release(duplicateLandmarks: true)
        XCTAssertThrowsError(
            try ReferenceAssetSession.load(.cloudValidatedRelease(wallId: wallId, service: env.service))
        ) { error in
            XCTAssertEqual(
                error as? ReferenceAssetError,
                .duplicateSemanticType(CloudAssetType.referenceLandmarksJSON)
            )
        }
    }

    func testOpaqueReferenceMapCannotBecomeStage3Input() throws {
        let env = try installOpaqueReferenceMapOnly()
        XCTAssertThrowsError(
            try ReferenceAssetSession.load(.cloudValidatedRelease(wallId: wallId, service: env.service))
        ) { error in
            XCTAssertEqual(
                error as? ReferenceAssetError,
                .missingRequiredSemanticType(CloudAssetType.referenceDescriptorsRVS1)
            )
        }
    }

    func testResolvedAssetIdsGoThroughCloudAssetServiceValidation() throws {
        let env = try installStage3Release()
        let resolved = try CloudValidatedReleaseSource(wallId: wallId, service: env.service).resolve()
        XCTAssertEqual(
            resolved.descriptorsURL,
            try env.service.localAssetURL(wallId: wallId, assetId: resolved.provenance.descriptorsAssetId)
        )
        XCTAssertEqual(
            resolved.landmarksURL,
            try env.service.localAssetURL(wallId: wallId, assetId: resolved.provenance.landmarksAssetId)
        )
        try Data("corrupt-required-asset".utf8).write(to: resolved.descriptorsURL)
        XCTAssertThrowsError(
            try ReferenceAssetSession.load(.cloudValidatedRelease(wallId: wallId, service: env.service))
        ) { error in
            guard let asset = error as? ReferenceAssetError else {
                return XCTFail("expected ReferenceAssetError, got \(error)")
            }
            switch asset {
            case .notInstalled, .integrityRejected:
                break
            default:
                XCTFail("CloudAssetService should reject corrupt required bytes, got \(asset)")
            }
        }
    }

    func testLoaderReusesReferenceDatabaseParser() throws {
        let env = try installStage3Release()
        let resolved = try CloudValidatedReleaseSource(wallId: wallId, service: env.service).resolve()
        let parsed = try ReferenceDatabase.load(
            descriptorsURL: resolved.descriptorsURL,
            landmarksURL: resolved.landmarksURL
        )
        let loaded = try ReferenceAssetLoader.load(
            from: CloudValidatedReleaseSource(wallId: wallId, service: env.service)
        )
        XCTAssertEqual(loaded.database, parsed)
        XCTAssertEqual(loaded.descriptorsURL, resolved.descriptorsURL)
        XCTAssertEqual(loaded.landmarksURL, resolved.landmarksURL)
    }

    func testCloudSourceNeverReadsStaging() throws {
        let env = try installStage3Release()
        let staging = try env.store.prepareStaging(wallId: wallId, releaseId: releaseId)
        let bait = Data("staging-bait".utf8)
        try env.store.writeAsset(bait, assetId: descriptorsAssetId, toReleaseRoot: staging)
        let loaded = try ReferenceAssetSession.load(
            .cloudValidatedRelease(wallId: wallId, service: env.service)
        )
        XCTAssertNotEqual(try Data(contentsOf: loaded.descriptorsURL), bait)
        XCTAssertFalse(loaded.descriptorsURL.path.contains("/staging/"))
        XCTAssertTrue(loaded.descriptorsURL.path.contains("/releases/\(releaseId)/"))
    }

    func testCloudSourceDoesNotConstructRawCachePaths() throws {
        let source = try String(contentsOf: cloudSourceURL())
        XCTAssertFalse(source.contains("CloudAssets"))
        XCTAssertFalse(source.contains("Application Support"))
        XCTAssertFalse(source.contains("appendingPathComponent(\"staging\""))
        XCTAssertFalse(source.contains("appendingPathComponent(\"releases\""))
        XCTAssertFalse(source.contains("/staging/"))
        XCTAssertFalse(source.contains("iosBridge"))
        XCTAssertFalse(source.contains("reference_descriptors\""))
        XCTAssertFalse(source.contains("\"descriptors\""))
        XCTAssertTrue(source.contains("localValidatedRelease"))
        XCTAssertTrue(source.contains("localAssetURL"))
        XCTAssertTrue(source.contains("CloudStage3AssetSemantics"))
    }

    func testMissingCloudCurrentFailsExplicitly() {
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: MockCloudTransport()),
            store: store
        )
        XCTAssertThrowsError(
            try ReferenceAssetSession.load(.cloudValidatedRelease(wallId: wallId, service: service))
        ) { error in
            XCTAssertEqual(error as? ReferenceAssetError, .notInstalled)
        }
    }

    func testCloudModeDoesNotFallBackToBundle() throws {
        let fixtureDir = fixtureDirectoryFromSource()
        let bundleAvailable = FileManager.default.fileExists(
            atPath: fixtureDir.appendingPathComponent("descriptors.bin").path
        )
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: MockCloudTransport()),
            store: store
        )
        XCTAssertThrowsError(
            try ReferenceAssetSession.load(.cloudValidatedRelease(wallId: wallId, service: service))
        ) { error in
            XCTAssertEqual(error as? ReferenceAssetError, .notInstalled)
        }
        if bundleAvailable {
            let bundleLoaded = try ReferenceAssetSession.load(.developmentFixture(directory: fixtureDir))
            XCTAssertEqual(bundleLoaded.provenance.source, "developmentFixture")
            XCTAssertNotEqual(bundleLoaded.database.wallId, wallId)
        }
    }

    func testFrameLoopHasNoCloudNetworkCalls() throws {
        let processor = try String(contentsOf: processorURL())
        XCTAssertFalse(processor.contains("fetchCatalog"))
        XCTAssertFalse(processor.contains("fetchManifest"))
        XCTAssertFalse(processor.contains("downloadAsset"))
        XCTAssertFalse(processor.contains("URLSession"))
        XCTAssertFalse(processor.contains("CloudAPIClient"))
        XCTAssertFalse(processor.contains("refreshAndInstall"))
        let matching = try String(contentsOf: matchingRuntimeURL())
        XCTAssertFalse(matching.contains("fetchCatalog"))
        XCTAssertFalse(matching.contains("CloudAPIClient"))
        XCTAssertFalse(matching.contains("URLSession"))
        let cloudSource = try String(contentsOf: cloudSourceURL())
        XCTAssertFalse(cloudSource.contains("fetchCatalog"))
        XCTAssertFalse(cloudSource.contains("downloadAsset"))
        XCTAssertFalse(cloudSource.contains("URLSession"))
        XCTAssertFalse(cloudSource.contains("CloudAPIClient"))
    }

    func testDefaultLocalizationSourceRemainsDevelopmentFixture() throws {
        let processor = try String(contentsOf: processorURL())
        XCTAssertTrue(processor.contains("ReferenceAssetSession.load(.developmentFixture())"))
        XCTAssertFalse(processor.contains("cloudValidatedRelease"))
        XCTAssertFalse(processor.contains("installRelease"))
        XCTAssertFalse(processor.contains("installExplicitRelease"))
        XCTAssertFalse(processor.contains("installJiulongfengDev"))
    }

    func testUndocumentedLocalTypeConventionIsGone() throws {
        let source = try String(contentsOf: cloudSourceURL())
        XCTAssertFalse(source.contains("CloudStage3AssetMapping"))
        XCTAssertFalse(source.contains("iosBridge"))
        let contract = try String(contentsOf: sourceFile("RockVision/Features/Cloud/CloudAssetContract.swift"))
        XCTAssertTrue(contract.contains("reference_descriptors_rvs1"))
        XCTAssertTrue(contract.contains("reference_landmarks_json"))
        XCTAssertFalse(contract.contains("static let iosBridge"))
    }

    private struct Installed {
        var store: CloudReleaseStore
        var service: CloudAssetService
        var descriptors: Data
        var landmarks: Data
    }

    private func installStage3Release(
        descriptorsId: String? = nil,
        landmarksId: String? = nil,
        includeDescriptors: Bool = true,
        includeLandmarks: Bool = true,
        descriptorsRequired: Bool = true,
        landmarksRequired: Bool = true,
        duplicateDescriptors: Bool = false,
        duplicateLandmarks: Bool = false
    ) throws -> Installed {
        let descriptors = try makeDescriptors()
        let landmarks = try makeLandmarksJSON()
        let descId = descriptorsId ?? descriptorsAssetId
        let landId = landmarksId ?? landmarksAssetId
        var assets: [(WallAssetDescriptor, Data)] = []
        if includeDescriptors {
            assets.append(
                (
                    WallAssetDescriptor(
                        assetId: descId,
                        type: CloudAssetType.referenceDescriptorsRVS1,
                        required: descriptorsRequired,
                        sha256: CloudIntegrity.sha256Hex(descriptors),
                        bytes: descriptors.count
                    ),
                    descriptors
                )
            )
        }
        if includeLandmarks {
            assets.append(
                (
                    WallAssetDescriptor(
                        assetId: landId,
                        type: CloudAssetType.referenceLandmarksJSON,
                        required: landmarksRequired,
                        sha256: CloudIntegrity.sha256Hex(landmarks),
                        bytes: landmarks.count
                    ),
                    landmarks
                )
            )
        }
        if duplicateDescriptors {
            assets.append(
                (
                    WallAssetDescriptor(
                        assetId: "dup-desc",
                        type: CloudAssetType.referenceDescriptorsRVS1,
                        required: true,
                        sha256: CloudIntegrity.sha256Hex(descriptors),
                        bytes: descriptors.count
                    ),
                    descriptors
                )
            )
        }
        if duplicateLandmarks {
            assets.append(
                (
                    WallAssetDescriptor(
                        assetId: "dup-land",
                        type: CloudAssetType.referenceLandmarksJSON,
                        required: true,
                        sha256: CloudIntegrity.sha256Hex(landmarks),
                        bytes: landmarks.count
                    ),
                    landmarks
                )
            )
        }
        if !descriptorsRequired || !landmarksRequired {
            let dummy = Data("keep-current-required".utf8)
            assets.append(
                (
                    WallAssetDescriptor(
                        assetId: "keep-current",
                        type: CloudAssetType.referenceMap,
                        required: true,
                        sha256: CloudIntegrity.sha256Hex(dummy),
                        bytes: dummy.count
                    ),
                    dummy
                )
            )
        }
        let store = try activate(assets: assets)
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: MockCloudTransport()),
            store: store
        )
        return Installed(store: store, service: service, descriptors: descriptors, landmarks: landmarks)
    }

    private func installOpaqueReferenceMapOnly() throws -> Installed {
        let blob = Data("cragpal-example-reference-map-v1\n".utf8)
        let store = try activate(assets: [
            (
                WallAssetDescriptor(
                    assetId: "reference-map",
                    type: CloudAssetType.referenceMap,
                    required: true,
                    sha256: CloudIntegrity.sha256Hex(blob),
                    bytes: blob.count
                ),
                blob
            )
        ])
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .custom(URL(string: "https://cloud.test")!), transport: MockCloudTransport()),
            store: store
        )
        return Installed(store: store, service: service, descriptors: blob, landmarks: Data())
    }

    private func activate(assets: [(WallAssetDescriptor, Data)]) throws -> CloudReleaseStore {
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let manifest = WallManifest(
            schema: CloudAssetSchema.manifest,
            wallId: wallId,
            releaseId: releaseId,
            createdAt: "2026-09-03T00:00:00Z",
            assets: assets.map(\.0)
        )
        let staging = try store.prepareStaging(wallId: wallId, releaseId: releaseId)
        try store.writeManifest(manifest, toReleaseRoot: staging)
        for (descriptor, data) in assets {
            try store.commitVerifiedAsset(data, descriptor: descriptor, toReleaseRoot: staging)
        }
        _ = try store.activateVerifiedStaging(wallId: wallId, releaseId: releaseId, manifest: manifest)
        return store
    }

    private func makeDescriptors() throws -> Data {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("rvs1-\(UUID().uuidString).bin")
        var row = [Float](repeating: 0, count: MatchingConfig.descriptorDim)
        row[0] = 1
        let payload = row.withUnsafeBufferPointer { Data(buffer: $0) }
        try RVS1Artifact.write(descriptors: payload, to: tmp)
        return try Data(contentsOf: tmp)
    }

    private func makeLandmarksJSON() throws -> Data {
        let landmarks: [String: Any] = [
            "schema": 1,
            "wallId": wallId,
            "developmentFixtureOnly": true,
            "notAWallPackage": true,
            "matcherHotPath": ["descriptor", "point3DID"],
            "landmarks": [[
                "index": 0,
                "referenceImageID": 1,
                "referenceImageName": "bridge.JPG",
                "referenceKeypointX": 1.0,
                "referenceKeypointY": 2.0,
                "point3DID": 7,
                "colmapXYZ": [0.0, 0.0, 0.0],
            ]],
        ]
        return try JSONSerialization.data(withJSONObject: landmarks)
    }

    private func uniqueRoot() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("ref-source-\(UUID().uuidString)", isDirectory: true)
    }

    private func fixtureDirectoryFromSource() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("RockVision/Resources/DevelopmentFixture", isDirectory: true)
    }

    private func cloudSourceURL() throws -> URL {
        sourceFile("RockVision/Features/Matching/ReferenceAssetSource.swift")
    }

    private func processorURL() throws -> URL {
        sourceFile("RockVision/Features/OpenCV/OpenCVFrameProcessor.swift")
    }

    private func matchingRuntimeURL() throws -> URL {
        sourceFile("RockVision/Features/Matching/MatchingRuntime.swift")
    }

    private func sourceFile(_ relative: String) -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(relative)
    }
}
