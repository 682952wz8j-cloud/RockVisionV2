import XCTest
@testable import RockVision

final class WallCandidateSelectorTests: XCTestCase {
    func testJinshidongCoordinateSelectsJinshidong() {
        let catalog = WallCatalog(
            schema: CloudAssetSchema.catalog,
            walls: [jinshidongEntry()]
        )
        let location = JinshidongCatalogLocation.location
        XCTAssertEqual(
            WallCandidateSelector.selectWallId(
                latitude: location.latitudeDeg,
                longitude: location.longitudeDeg,
                catalog: catalog
            ),
            JinshidongCatalogLocation.wallId
        )
    }

    func testJiulongfengCoordinateSelectsJiulongfeng() {
        let catalog = WallCatalog(
            schema: CloudAssetSchema.catalog,
            walls: [jinshidongEntry(), jiulongfengEntry()]
        )
        let location = JiulongfengCatalogLocation.location
        XCTAssertEqual(
            WallCandidateSelector.selectWallId(
                latitude: location.latitudeDeg,
                longitude: location.longitudeDeg,
                catalog: catalog
            ),
            JiulongfengCatalogLocation.wallId
        )
    }

    func testFarAwayGPSSelectsNothing() {
        let catalog = WallCatalog(
            schema: CloudAssetSchema.catalog,
            walls: [jinshidongEntry()]
        )
        XCTAssertNil(
            WallCandidateSelector.selectWallId(
                latitude: 31.23,
                longitude: 121.47,
                catalog: catalog
            )
        )
    }

    func testEntryWithoutLocationIsIgnored() {
        let catalog = WallCatalog(
            schema: CloudAssetSchema.catalog,
            walls: [
                WallCatalogEntry(
                    wallId: "wall_example_01",
                    name: "Example Wall",
                    latestReleaseId: "r000001",
                    environment: .production
                )
            ]
        )
        let location = JinshidongCatalogLocation.location
        XCTAssertNil(
            WallCandidateSelector.selectWallId(
                latitude: location.latitudeDeg,
                longitude: location.longitudeDeg,
                catalog: catalog
            )
        )
    }

    func testCatalogLocationRoundTrip() throws {
        let data = Data(
            """
            {"schema":"cragpal.wall-catalog.v1","walls":[{"wallId":"wall_jinshidong_01","name":"金狮洞","latestReleaseId":"r000001","environment":"production","catalogLocation":{"purpose":"wall_candidate_selection_only","latitudeDeg":30.623418333479282,"longitudeDeg":118.72756872205237,"altitudeMeters":211.89499999933113}}]}
            """.utf8
        )
        let catalog = try CloudAssetContract.decodeCatalog(data)
        XCTAssertEqual(catalog.walls[0].wallId, JinshidongCatalogLocation.wallId)
        XCTAssertEqual(catalog.walls[0].name, JinshidongCatalogLocation.displayName)
        XCTAssertEqual(catalog.walls[0].latestReleaseId, JinshidongCatalogLocation.releaseId)
        XCTAssertEqual(catalog.walls[0].environment, .production)
        let location = try XCTUnwrap(catalog.walls[0].catalogLocation)
        XCTAssertEqual(location.purpose, WallCatalogLocation.purpose)
        XCTAssertEqual(location.latitudeDeg, JinshidongCatalogLocation.location.latitudeDeg)
        XCTAssertEqual(location.longitudeDeg, JinshidongCatalogLocation.location.longitudeDeg)
        XCTAssertEqual(location.altitudeMeters, JinshidongCatalogLocation.location.altitudeMeters)
        let encoded = try JSONEncoder().encode(catalog)
        let again = try CloudAssetContract.decodeCatalog(encoded)
        XCTAssertEqual(again.walls[0].catalogLocation, location)
    }

    func testInvalidCatalogLocationPurposeFailsClosed() {
        let data = Data(
            """
            {"schema":"cragpal.wall-catalog.v1","walls":[{"wallId":"wall_jinshidong_01","name":"金狮洞","latestReleaseId":"r000001","environment":"production","catalogLocation":{"purpose":"pose","latitudeDeg":30.62,"longitudeDeg":118.72}}]}
            """.utf8
        )
        XCTAssertThrowsError(try CloudAssetContract.decodeCatalog(data)) { error in
            XCTAssertEqual(error as? CloudAssetError, .decoding)
        }
    }

    func testSelectorDoesNotImportCoreLocation() throws {
        let selector = try readHostSource("RockVision/Features/Cloud/WallCandidateSelector.swift")
        XCTAssertFalse(selector.contains("import CoreLocation"))
        XCTAssertFalse(selector.contains("CLLocation"))
        XCTAssertTrue(selector.contains("wall_candidate_selection_only"))
        let processor = try readHostSource("RockVision/Features/OpenCV/OpenCVFrameProcessor.swift")
        XCTAssertFalse(processor.contains("import CoreLocation"))
        XCTAssertFalse(processor.contains("CLLocation"))
        XCTAssertFalse(processor.contains("fetchCatalog"))
        let provider = try readHostSource("RockVision/Features/Cloud/WallLocationProvider.swift")
        XCTAssertTrue(provider.contains("import CoreLocation"))
        XCTAssertTrue(provider.contains("never used for pose") || provider.contains("Not a localizer"))
    }

    private func jinshidongEntry() -> WallCatalogEntry {
        WallCatalogEntry(
            wallId: JinshidongCatalogLocation.wallId,
            name: JinshidongCatalogLocation.displayName,
            latestReleaseId: JinshidongCatalogLocation.releaseId,
            environment: .production,
            catalogLocation: JinshidongCatalogLocation.location
        )
    }

    private func jiulongfengEntry() -> WallCatalogEntry {
        WallCatalogEntry(
            wallId: JiulongfengCatalogLocation.wallId,
            name: JiulongfengCatalogLocation.displayName,
            latestReleaseId: JiulongfengCatalogLocation.releaseId,
            environment: .production,
            catalogLocation: JiulongfengCatalogLocation.location
        )
    }

    private func readHostSource(_ relative: String) throws -> String {
        let path = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(relative)
            .path
        guard FileManager.default.isReadableFile(atPath: path) else {
            throw XCTSkip("host source tree not readable")
        }
        return try String(contentsOfFile: path, encoding: .utf8)
    }
}
