import XCTest
@testable import RockVision

final class JinshidongLocalTestAssetTests: XCTestCase {
    func testLocalizationPackageLoadsForDevelopmentRuntime() throws {
        let directory = try XCTUnwrap(JinshidongLocalTestAssets.resourceDirectory(in: Bundle(for: OpenCVFrameProcessor.self)))
        let descriptors = directory.appendingPathComponent("descriptors.bin")
        let landmarks = directory.appendingPathComponent("landmarks.json")
        if !FileManager.default.fileExists(atPath: descriptors.path)
            || !FileManager.default.fileExists(atPath: landmarks.path) {
            throw XCTSkip("Run ios/scripts/sync_jinshidong_local_test_assets.sh")
        }
        let pack = try JinshidongLocalTestAssets.load(from: directory)
        XCTAssertEqual(pack.provenance.source, "jinshidongLocalTest")
        XCTAssertEqual(pack.provenance.wallId, "wall_jinshidong_01")
        XCTAssertEqual(pack.provenance.releaseId, "r000000")
        XCTAssertEqual(pack.database.wallId, "wall_jinshidong_01")
        XCTAssertGreaterThan(pack.database.descriptorCount, 0)
        XCTAssertEqual(pack.sim3.status, "VALIDATED")
        XCTAssertEqual(pack.sim3.scale, JinshidongLocalTestAssets.expectedSim3Scale, accuracy: 1e-9)
        XCTAssertTrue(pack.notACatalogRelease)
        XCTAssertTrue(pack.notAProductionRelease)
        XCTAssertNotEqual(pack.provenance.source, "cloud")
        XCTAssertNotEqual(pack.database.wallId, "wall_jiulongfeng_01")
    }

    func testFourRoutesParseWithStableIdentity() throws {
        let directory = try XCTUnwrap(JinshidongLocalTestAssets.resourceDirectory(in: Bundle(for: OpenCVFrameProcessor.self)))
        let loaded = try JinshidongLocalTestAssets.loadRoutes(from: directory)
        XCTAssertEqual(loaded.routes.count, 4)
        XCTAssertEqual(loaded.legend.count, 4)
        XCTAssertTrue(loaded.bundle.notAProductionRoutePackage)
        XCTAssertTrue(loaded.bundle.notAStage5Release)
        XCTAssertTrue(loaded.bundle.developmentValidationOnly)

        let expected: [(String, String, String, String, Int, String)] = [
            ("jinshidong_lucky_baby", "Lucky Baby", "5.7", "3+2", 6, "9473023e60e9fd5a2003ead60d5e7134d0b1386e81b861457e1de569ae62b407"),
            ("jinshidong_shui_tai_shen", "水太深", "5.12d", "6+2", 3, "83e5a754ff42ddc30739d0b52d05cb54f94c74725541af612623b1d9a7ebc509"),
            ("jinshidong_mei_xiang_hao", "没想好", "5.11b", "7+2", 6, "98a08ad0608795a1a2d1b0c48028870b22b33c20257913ffcc8557239e8b173d"),
            ("jinshidong_long_zhua_shou", "龙抓手", "5.11b", "5+2", 4, "0534fd4a3babefdfb02bb994c15956491052fcf852fa8d1d1c55b4e12006eea7"),
        ]
        for (index, item) in expected.enumerated() {
            let route = loaded.routes[index]
            XCTAssertEqual(route.routeId, item.0)
            XCTAssertEqual(route.routeName, item.1)
            XCTAssertEqual(route.grade, item.2)
            XCTAssertEqual(route.displayDraws, item.3)
            XCTAssertEqual(route.wallMetricMeters.count, item.4)
            XCTAssertEqual(route.polylineSha256, item.5)
            XCTAssertEqual(loaded.legend[index].displayDraws, item.3)
            XCTAssertNotEqual(route.routeId, VerifiedFrozenRoute.expectedRouteId)
            XCTAssertNotEqual(route.wallId, VerifiedFrozenRoute.expectedWallId)
            XCTAssertNotEqual(route.provenance, VerifiedFrozenRoute.expectedProvenance)
            XCTAssertTrue(route.developmentValidationOnly)
            XCTAssertTrue(route.hashVerified)
        }
    }

    func testLocalTestIsNotAProductionRelease() throws {
        let directory = try XCTUnwrap(JinshidongLocalTestAssets.resourceDirectory(in: Bundle(for: OpenCVFrameProcessor.self)))
        let manifest = try JinshidongLocalTestAssets.loadManifest(from: directory)
        XCTAssertTrue(manifest.developmentLocalTestOnly)
        XCTAssertTrue(manifest.notAProductionRelease)
        XCTAssertTrue(manifest.notACatalogRelease)
        XCTAssertTrue(manifest.notAProductionRoutePackage)
        XCTAssertEqual(manifest.releaseId, "r000000")
        XCTAssertEqual(manifest.wallId, "wall_jinshidong_01")
        let processor = OpenCVFrameProcessor()
        #if DEBUG
        XCTAssertEqual(processor.debugDesiredReferenceSourceMode, "jinshidongLocalTest")
        #endif
        XCTAssertEqual(DebugHUDMode.stage5.showsStage5HUD, true)
        #if DEBUG
        XCTAssertEqual(DebugHUDMode.active, .stage5)
        XCTAssertTrue(DebugHUDMode.active.showsStage5HUD)
        XCTAssertFalse(DebugHUDMode.active.showsCloudD5HUD)
        #endif
    }

    func testProcessorDefaultDoesNotSelectJiulongfengFixture() throws {
        let processor = OpenCVFrameProcessor()
        #if DEBUG
        XCTAssertEqual(processor.debugDesiredReferenceSourceMode, "jinshidongLocalTest")
        XCTAssertNotEqual(processor.debugDesiredReferenceSourceMode, "bundleDevelopmentFixture")
        #else
        throw XCTSkip("Only meaningful in DEBUG test builds.")
        #endif
    }
}
