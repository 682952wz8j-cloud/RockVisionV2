import Foundation
import XCTest
@testable import RockVision

final class OpenCVReferenceSourceSelectionTests: XCTestCase {
    private let expectedWallId = "wall_jiulongfeng_01_dev"
    private let expectedReleaseId = "r000001"

    func testDefaultReferenceSourceRemainsBundleDevelopmentFixture() throws {
        let processor = OpenCVFrameProcessor()
        #if DEBUG
        XCTAssertEqual(processor.debugDesiredReferenceSourceMode, "bundleDevelopmentFixture")
        #else
        throw XCTSkip("Only meaningful in DEBUG test builds.")
        #endif
    }

    func testCloudCurrentSelectionLoadsExactWallAndRelease() throws {
        let (service, store) = try makeCloudCurrentStore(
            wallId: expectedWallId,
            releaseId: expectedReleaseId,
            duplicateDescriptors: false,
            duplicateLandmarks: false,
            includeDescriptors: true,
            includeLandmarks: true
        )

        let processor = OpenCVFrameProcessor()
        #if DEBUG
        processor.debugSetCloudAssetServiceOverrideForSelection(service)
        #endif
        processor.selectReferenceSourceCloudCurrentJiulongfengDevR000001()
        #if DEBUG
        processor.debugForceReferenceSourceLoadForTesting()
        #endif

        XCTAssertEqual(processor.referenceAssetProvenance.source, "cloud")
        XCTAssertEqual(processor.referenceAssetProvenance.wallId, expectedWallId)
        XCTAssertEqual(processor.referenceAssetProvenance.releaseId, expectedReleaseId)
        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "available")
        _ = store // silence unused warning
    }

    func testCloudCurrentIdentityMismatchFailsClosed() throws {
        let (service, _) = try makeCloudCurrentStore(
            wallId: expectedWallId,
            releaseId: "r000002",
            duplicateDescriptors: false,
            duplicateLandmarks: false,
            includeDescriptors: true,
            includeLandmarks: true
        )

        let processor = OpenCVFrameProcessor()
        #if DEBUG
        processor.debugSetCloudAssetServiceOverrideForSelection(service)
        #endif
        processor.selectReferenceSourceCloudCurrentJiulongfengDevR000001()
        #if DEBUG
        processor.debugForceReferenceSourceLoadForTesting()
        #endif

        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "unavailable")
        XCTAssertEqual(processor.referenceAssetProvenance.wallId, "—")
        XCTAssertEqual(processor.referenceAssetProvenance.releaseId, "—")
    }

    func testCloudCurrentWrongWallFailsClosed() throws {
        let (service, _) = try makeCloudCurrentStore(
            wallId: "wall_other_01",
            releaseId: expectedReleaseId,
            duplicateDescriptors: false,
            duplicateLandmarks: false,
            includeDescriptors: true,
            includeLandmarks: true
        )

        let processor = OpenCVFrameProcessor()
        #if DEBUG
        processor.debugSetCloudAssetServiceOverrideForSelection(service)
        #endif
        processor.selectReferenceSourceCloudCurrentJiulongfengDevR000001()
        #if DEBUG
        processor.debugForceReferenceSourceLoadForTesting()
        #endif

        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "unavailable")
    }

    func testCloudCurrentDuplicateDescriptorSemanticTypeFailsClosed() throws {
        let (service, _) = try makeCloudCurrentStore(
            wallId: expectedWallId,
            releaseId: expectedReleaseId,
            duplicateDescriptors: true,
            duplicateLandmarks: false,
            includeDescriptors: true,
            includeLandmarks: true
        )

        let processor = OpenCVFrameProcessor()
        #if DEBUG
        processor.debugSetCloudAssetServiceOverrideForSelection(service)
        #endif
        processor.selectReferenceSourceCloudCurrentJiulongfengDevR000001()
        #if DEBUG
        processor.debugForceReferenceSourceLoadForTesting()
        #endif

        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "unavailable")
    }

    func testCloudCurrentDuplicateLandmarksSemanticTypeFailsClosed() throws {
        let (service, _) = try makeCloudCurrentStore(
            wallId: expectedWallId,
            releaseId: expectedReleaseId,
            duplicateDescriptors: false,
            duplicateLandmarks: true,
            includeDescriptors: true,
            includeLandmarks: true
        )

        let processor = OpenCVFrameProcessor()
        #if DEBUG
        processor.debugSetCloudAssetServiceOverrideForSelection(service)
        #endif
        processor.selectReferenceSourceCloudCurrentJiulongfengDevR000001()
        #if DEBUG
        processor.debugForceReferenceSourceLoadForTesting()
        #endif

        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "unavailable")
    }

    func testCloudCurrentMissingLandmarksFailsClosed() throws {
        let (service, _) = try makeCloudCurrentStore(
            wallId: expectedWallId,
            releaseId: expectedReleaseId,
            duplicateDescriptors: false,
            duplicateLandmarks: false,
            includeDescriptors: true,
            includeLandmarks: false
        )

        let processor = OpenCVFrameProcessor()
        #if DEBUG
        processor.debugSetCloudAssetServiceOverrideForSelection(service)
        #endif
        processor.selectReferenceSourceCloudCurrentJiulongfengDevR000001()
        #if DEBUG
        processor.debugForceReferenceSourceLoadForTesting()
        #endif

        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "unavailable")
    }

    func testCloudCurrentMissingDescriptorsFailsClosed() throws {
        let (service, _) = try makeCloudCurrentStore(
            wallId: expectedWallId,
            releaseId: expectedReleaseId,
            duplicateDescriptors: false,
            duplicateLandmarks: false,
            includeDescriptors: false,
            includeLandmarks: true
        )

        let processor = OpenCVFrameProcessor()
        #if DEBUG
        processor.debugSetCloudAssetServiceOverrideForSelection(service)
        #endif
        processor.selectReferenceSourceCloudCurrentJiulongfengDevR000001()
        #if DEBUG
        processor.debugForceReferenceSourceLoadForTesting()
        #endif

        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "unavailable")
    }

    func testSourceSwitchReloadsAndDoesNotMixDatabases() throws {
        let fixtureDir = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("RockVision/Resources/DevelopmentFixture", isDirectory: true)
        let bundleHasBinaries = FileManager.default.fileExists(
            atPath: fixtureDir.appendingPathComponent("descriptors.bin").path
        ) && FileManager.default.fileExists(
            atPath: fixtureDir.appendingPathComponent("landmarks.json").path
        )
        if !bundleHasBinaries {
            throw XCTSkip("Run ios/scripts/install_development_fixture.sh")
        }

        let (cloudService, _) = try makeCloudCurrentStore(
            wallId: expectedWallId,
            releaseId: expectedReleaseId,
            duplicateDescriptors: false,
            duplicateLandmarks: false,
            includeDescriptors: true,
            includeLandmarks: true
        )

        let processor = OpenCVFrameProcessor()
        #if DEBUG
        processor.debugSetCloudAssetServiceOverrideForSelection(cloudService)
        #endif

        // Bundle first (default).
        processor.selectReferenceSourceBundleDevelopmentFixture()
        #if DEBUG
        processor.debugForceReferenceSourceLoadForTesting()
        #endif
        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "available")
        XCTAssertEqual(processor.referenceAssetProvenance.releaseId, "—")

        // Switch to Cloud CURRENT.
        processor.selectReferenceSourceCloudCurrentJiulongfengDevR000001()
        #if DEBUG
        processor.debugForceReferenceSourceLoadForTesting()
        #endif
        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "available")
        XCTAssertEqual(processor.referenceAssetProvenance.releaseId, expectedReleaseId)

        // Back to Bundle: ensure reloaded, not stale.
        processor.selectReferenceSourceBundleDevelopmentFixture()
        #if DEBUG
        processor.debugForceReferenceSourceLoadForTesting()
        #endif
        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "available")
        XCTAssertEqual(processor.referenceAssetProvenance.releaseId, "—")
    }

    private func makeCloudCurrentStore(
        wallId: String,
        releaseId: String,
        duplicateDescriptors: Bool,
        duplicateLandmarks: Bool,
        includeDescriptors: Bool,
        includeLandmarks: Bool
    ) throws -> (service: CloudAssetService, store: CloudReleaseStore) {
        let descriptors = try makeDescriptorsPayload()
        let landmarks = try makeLandmarksJSONPayload(wallId: wallId)

        let descriptorsDescriptor = WallAssetDescriptor(
            assetId: "alpha-pack",
            type: CloudAssetType.referenceDescriptorsRVS1,
            required: true,
            sha256: CloudIntegrity.sha256Hex(descriptors),
            bytes: descriptors.count
        )
        let landmarksDescriptor = WallAssetDescriptor(
            assetId: "omega-meta",
            type: CloudAssetType.referenceLandmarksJSON,
            required: true,
            sha256: CloudIntegrity.sha256Hex(landmarks),
            bytes: landmarks.count
        )

        var assets: [(WallAssetDescriptor, Data)] = []
        if includeDescriptors {
            assets.append((descriptorsDescriptor, descriptors))
            if duplicateDescriptors {
                let dup = WallAssetDescriptor(
                    assetId: "alpha-pack-dup",
                    type: CloudAssetType.referenceDescriptorsRVS1,
                    required: true,
                    sha256: CloudIntegrity.sha256Hex(descriptors),
                    bytes: descriptors.count
                )
                assets.append((dup, descriptors))
            }
        }
        if includeLandmarks {
            assets.append((landmarksDescriptor, landmarks))
            if duplicateLandmarks {
                let dup = WallAssetDescriptor(
                    assetId: "omega-meta-dup",
                    type: CloudAssetType.referenceLandmarksJSON,
                    required: true,
                    sha256: CloudIntegrity.sha256Hex(landmarks),
                    bytes: landmarks.count
                )
                assets.append((dup, landmarks))
            }
        }

        let store = try activateCloudRelease(wallId: wallId, releaseId: releaseId, assets: assets)
        let service = CloudAssetService(
            client: CloudAPIClient(
                configuration: .custom(URL(string: "https://cloud.test")!),
                transport: MockCloudTransport()
            ),
            store: store
        )
        return (service, store)
    }

    private func activateCloudRelease(
        wallId: String,
        releaseId: String,
        assets: [(WallAssetDescriptor, Data)]
    ) throws -> CloudReleaseStore {
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

    private func makeDescriptorsPayload() throws -> Data {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("rvs1-\(UUID().uuidString).bin")
        var row = [Float](repeating: 0, count: MatchingConfig.descriptorDim)
        row[0] = 1
        let payload = row.withUnsafeBufferPointer { Data(buffer: $0) }
        try RVS1Artifact.write(descriptors: payload, to: tmp)
        return try Data(contentsOf: tmp)
    }

    private func makeLandmarksJSONPayload(wallId: String) throws -> Data {
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
}

