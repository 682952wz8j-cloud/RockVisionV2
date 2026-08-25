import XCTest
@testable import RockVision

final class DevelopmentFixtureTests: XCTestCase {
    func testCommittedManifestMatchesFrozenIdentity() throws {
        let manifest = try JSONDecoder().decode(
            DevelopmentFixture.Manifest.self,
            from: try Data(contentsOf: committedManifestURL())
        )
        XCTAssertEqual(manifest.descriptorsSha256, DevelopmentFixture.expectedDescriptorsSha256)
        XCTAssertEqual(manifest.landmarksSha256, DevelopmentFixture.expectedLandmarksSha256)
        XCTAssertEqual(manifest.descriptorCount, DevelopmentFixture.expectedDescriptorCount)
        XCTAssertEqual(manifest.uniquePoint3D, DevelopmentFixture.expectedUniquePoint3D)
        XCTAssertEqual(manifest.referenceImages, DevelopmentFixture.expectedReferenceImages)
        XCTAssertEqual(manifest.wallId, DevelopmentFixture.expectedWallId)
        XCTAssertTrue(manifest.developmentFixtureOnly)
        XCTAssertTrue(manifest.notAWallPackage)
        XCTAssertEqual(manifest.matcherHotPath, ["descriptor", "point3DID"])
        XCTAssertTrue(manifest.xyzNotUsedInMatching)
        try DevelopmentFixture.verifyIdentity(manifest)
    }

    func testMissingBinariesAreInactiveWithoutCrashing() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("fixture-missing-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        try Data(contentsOf: committedManifestURL()).write(to: dir.appendingPathComponent("manifest.json"))
        let status = DevelopmentFixture.loadIfPresent(from: dir)
        if case .inactive(let reason) = status {
            XCTAssertTrue(reason.contains("binaries not installed"))
        } else {
            XCTFail("expected inactive fixture, got \(status)")
        }
    }

    func testSHA256MismatchIsRejected() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("fixture-badsha-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        try Data(contentsOf: committedManifestURL()).write(to: dir.appendingPathComponent("manifest.json"))
        try Data("not-the-frozen-descriptors".utf8).write(to: dir.appendingPathComponent("descriptors.bin"))
        try Data("not-the-frozen-landmarks".utf8).write(to: dir.appendingPathComponent("landmarks.json"))
        XCTAssertThrowsError(try DevelopmentFixture.loadVerified(from: dir)) { error in
            guard let matchingError = error as? MatchingError,
                  case .sha256Mismatch(let file, _, _) = matchingError else {
                return XCTFail("expected sha256Mismatch, got \(error)")
            }
            XCTAssertEqual(file, "descriptors.bin")
        }
    }

    func testCopiedBinariesMatchManifestSHA256() throws {
        let dir = fixtureDirectoryFromSource()
        let descriptors = dir.appendingPathComponent("descriptors.bin")
        let landmarks = dir.appendingPathComponent("landmarks.json")
        try XCTSkipUnless(
            FileManager.default.fileExists(atPath: descriptors.path)
                && FileManager.default.fileExists(atPath: landmarks.path),
            "run ios/scripts/install_development_fixture.sh"
        )
        XCTAssertEqual(try DevelopmentFixture.sha256Hex(ofFile: descriptors), DevelopmentFixture.expectedDescriptorsSha256)
        XCTAssertEqual(try DevelopmentFixture.sha256Hex(ofFile: landmarks), DevelopmentFixture.expectedLandmarksSha256)
        let rvs1 = try RVS1Artifact.read(from: descriptors)
        XCTAssertEqual(rvs1.count, DevelopmentFixture.expectedDescriptorCount)
        XCTAssertEqual(rvs1.dim, MatchingConfig.descriptorDim)
        XCTAssertEqual(rvs1.data.count, DevelopmentFixture.expectedDescriptorCount * MatchingConfig.descriptorDim * 4)
    }

    func testLoadVerifiedProductionFixture() throws {
        let dir = fixtureDirectoryFromSource()
        try XCTSkipUnless(
            FileManager.default.fileExists(atPath: dir.appendingPathComponent("descriptors.bin").path)
                && FileManager.default.fileExists(atPath: dir.appendingPathComponent("landmarks.json").path),
            "run ios/scripts/install_development_fixture.sh"
        )
        let database = try DevelopmentFixture.loadVerified(from: dir)
        XCTAssertEqual(database.descriptorCount, DevelopmentFixture.expectedDescriptorCount)
        XCTAssertEqual(Set(database.point3dIds).count, DevelopmentFixture.expectedUniquePoint3D)
        XCTAssertEqual(database.wallId, DevelopmentFixture.expectedWallId)
        XCTAssertTrue(database.developmentFixtureOnly)
        XCTAssertTrue(database.notAWallPackage)
        XCTAssertEqual(database.matcherHotPath, ["descriptor", "point3DID"])
        let record = MatchRecord(queryIndex: 0, reason: .acceptedAfterRatio, point3DID: database.point3dIds[0], referenceRow: 0)
        XCTAssertNotNil(database.provenance(for: record))
    }

    private func committedManifestURL() throws -> URL {
        let url = fixtureDirectoryFromSource().appendingPathComponent("manifest.json")
        XCTAssertTrue(FileManager.default.fileExists(atPath: url.path), "committed manifest.json missing")
        return url
    }

    private func fixtureDirectoryFromSource() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("RockVision/Resources/DevelopmentFixture", isDirectory: true)
    }
}
