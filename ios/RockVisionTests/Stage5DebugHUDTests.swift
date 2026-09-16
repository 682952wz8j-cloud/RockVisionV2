import SwiftUI
import XCTest
@testable import RockVision

final class Stage5DebugHUDTests: XCTestCase {
    func testLocalizedStateShowsSuccess() {
        XCTAssertEqual(
            Stage5DebugHUDModel.localizationLine(state: ConfirmationConfig.localizationLocalized),
            "定位成功"
        )
        var pnp = PnPRuntimeSnapshot()
        pnp.inliers = "28"
        pnp.reproj = "1.40 px"
        let line = Stage5DebugHUDModel.diagnosticLine(
            localization: "localized",
            pnp: pnp,
            wallId: "wall_example_01",
            cloudAssetsLoaded: true
        )
        XCTAssertEqual(line, "定位成功 | PnP 28 | 1.40 px | wall_example_01 | 云端已加载")
        XCTAssertEqual(
            Stage5DebugHUDModel.lines(
                localization: "localized",
                pnp: pnp,
                wallId: "wall_example_01",
                cloudAssetsLoaded: true
            ),
            [line]
        )
    }

    func testNonLocalizedStatesShowFailure() {
        for state in [ConfirmationConfig.localizationIdle, ConfirmationConfig.localizationConfirming, "lost"] {
            XCTAssertEqual(Stage5DebugHUDModel.localizationLine(state: state), "定位失败")
        }
        let line = Stage5DebugHUDModel.diagnosticLine(
            localization: "idle",
            pnp: PnPRuntimeSnapshot(),
            wallId: "",
            cloudAssetsLoaded: false
        )
        XCTAssertEqual(line, "定位失败 | PnP — | — px | — | 加载失败")
        XCTAssertEqual(Stage5DebugHUDModel.lines(
            localization: "idle",
            pnp: PnPRuntimeSnapshot(),
            wallId: "",
            cloudAssetsLoaded: false
        ).count, 1)
    }

    func testPnPLineUsesCurrentInliersAndReprojectionMedian() {
        XCTAssertEqual(
            Stage5DebugHUDModel.pnpLine(inliers: "31", reproj: "0.85 px"),
            "PnP 31 | 0.85 px"
        )
        XCTAssertEqual(
            Stage5DebugHUDModel.pnpLine(inliers: "—", reproj: "—"),
            "PnP — | — px"
        )
    }

    func testDiagnosticLineUsesLiveRuntimeFieldsOnly() {
        var pnp = PnPRuntimeSnapshot()
        pnp.inliers = "19"
        pnp.reproj = "0.62 px"
        XCTAssertEqual(
            Stage5DebugHUDModel.diagnosticLine(
                localization: ConfirmationConfig.localizationLocalized,
                pnp: pnp,
                wallId: "wall_other_02",
                cloudAssetsLoaded: true
            ),
            "定位成功 | PnP 19 | 0.62 px | wall_other_02 | 云端已加载"
        )
    }

    func testOfficialRouteCopyOmitsMissingMetadata() {
        let namedOnly = sampleRoute(name: "Alpha", grade: nil, draws: nil, length: nil)
        XCTAssertEqual(ProductionRouteFieldCopy.displayLines(namedOnly), ["Alpha"])
        let unspecified = sampleRoute(name: "白墙测试线", grade: "unspecified", draws: "unspecified", length: nil)
        XCTAssertEqual(ProductionRouteFieldCopy.displayLines(unspecified), ["白墙测试线"])
        XCTAssertNil(ProductionRouteFieldCopy.officialText("unspecified"))
        XCTAssertNil(ProductionRouteFieldCopy.officialText(""))
        XCTAssertNil(ProductionRouteFieldCopy.officialText("  "))
        XCTAssertNil(ProductionRouteFieldCopy.officialLength(nil))
        XCTAssertNil(ProductionRouteFieldCopy.officialLength(0))
        XCTAssertNil(ProductionRouteFieldCopy.quickdrawLine(nil))
        XCTAssertNil(ProductionRouteFieldCopy.quickdrawLine("unspecified"))
        XCTAssertNil(ProductionRouteFieldCopy.quickdrawLine("n/a"))
    }

    func testOfficialRouteCopyShowsGradeLengthAndParsedQuickdraws() {
        let route = sampleRoute(name: "Lucky Baby", grade: "5.7", draws: "3+2", length: 12)
        XCTAssertEqual(
            ProductionRouteFieldCopy.displayLines(route),
            ["Lucky Baby", "5.7", "12 m", "🔗 3+2"]
        )
        XCTAssertEqual(ProductionRouteFieldCopy.quickdrawLine("6"), "🔗 6+2")
        XCTAssertEqual(ProductionRouteFieldCopy.quickdrawLine("6+2"), "🔗 6+2")
        XCTAssertNil(ProductionRouteFieldCopy.quickdrawLine("6+1"))
        XCTAssertEqual(ProductionRouteFieldCopy.officialLength(12), "12 m")
        XCTAssertEqual(ProductionRouteFieldCopy.officialLength(12.5), "12.5 m")
        XCTAssertEqual(ProductionRouteFieldCopy.copyColor, Color.white)
    }

    func testJinshidongProductionPackageDrivesFieldCopy() throws {
        let routes = try XCTUnwrap(
            VerifiedFrozenRoute.loadProductionAsset(
                from: try candidateURL("assets/wall-routes", wallId: JinshidongCatalogLocation.wallId),
                expectedWallId: JinshidongCatalogLocation.wallId,
                expectedReleaseId: JinshidongCatalogLocation.releaseId
            )
        )
        XCTAssertEqual(routes.map(\.routeId), [
            "jinshidong_lucky_baby",
            "jinshidong_shui_tai_shen",
            "jinshidong_mei_xiang_hao",
            "jinshidong_long_zhua_shou"
        ])
        XCTAssertEqual(
            ProductionRouteFieldCopy.displayLines(routes[0]),
            ["Lucky Baby", "5.7", "🔗 3+2"]
        )
        XCTAssertEqual(
            ProductionRouteFieldCopy.displayLines(routes[1]),
            ["水太深", "5.12d", "🔗 6+2"]
        )
        XCTAssertFalse(ProductionRouteFieldCopy.displayLines(routes[0]).contains { $0.hasSuffix(" m") })
    }

    func testJiulongfengProductionPackageOmitsUnspecifiedMetadata() throws {
        let routes = try XCTUnwrap(
            VerifiedFrozenRoute.loadProductionAsset(
                from: try candidateURL("assets/wall-routes", wallId: JiulongfengCatalogLocation.wallId),
                expectedWallId: JiulongfengCatalogLocation.wallId,
                expectedReleaseId: JiulongfengCatalogLocation.releaseId
            )
        )
        XCTAssertEqual(routes.map(\.routeId), [JiulongfengCatalogLocation.routeId])
        XCTAssertEqual(ProductionRouteFieldCopy.displayLines(routes[0]), ["白墙测试线"])
        XCTAssertFalse(ProductionRouteFieldCopy.displayLines(routes[0]).contains("unspecified"))
        XCTAssertFalse(ProductionRouteFieldCopy.displayLines(routes[0]).contains { $0.hasPrefix("🔗") })
        XCTAssertFalse(ProductionRouteFieldCopy.displayLines(routes[0]).contains { $0.hasSuffix(" m") })
    }

    func testStage5HUDSourceContainsOnlyTheTwoEvidenceLines() throws {
        let hud = try readHostSource("RockVision/Features/DebugOverlay/Stage5DebugHUD.swift")
        XCTAssertTrue(hud.contains("定位成功"))
        XCTAssertTrue(hud.contains("定位失败"))
        XCTAssertTrue(hud.contains("PnP \\(pnp.inliers)"))
        XCTAssertTrue(hud.contains("medianToken"))
        XCTAssertTrue(hud.contains("云端已加载"))
        XCTAssertTrue(hud.contains("加载失败"))
        XCTAssertTrue(hud.contains("EmptyView()"))
        XCTAssertFalse(hud.contains("ForEach(routes"))
        XCTAssertFalse(hud.contains("wall_jinshidong_01"))
        XCTAssertFalse(hud.contains("wall_jiulongfeng_01"))
        XCTAssertFalse(hud.contains("Start Measurement"))
        XCTAssertFalse(hud.contains("Gate 4B"))
        XCTAssertFalse(hud.contains("Jinshidong local test"))
        XCTAssertFalse(hud.contains("FieldTestPanel"))
        XCTAssertFalse(hud.contains("localTestLegend"))
        XCTAssertFalse(hud.contains("云端资产：已加载"))
        XCTAssertFalse(hud.contains("云端资产：加载失败"))
    }

    func testContentViewKeepsGate4BPanelOffStage5HUD() throws {
        let content = try readHostSource("RockVision/App/ContentView.swift")
        XCTAssertTrue(content.contains("if DebugHUDMode.active.showsGate4BHUD {"))
        XCTAssertTrue(content.contains("FieldTestPanel("))
        XCTAssertTrue(content.contains("if DebugHUDMode.active.showsStage5HUD {"))
        XCTAssertTrue(content.contains("ScanLoadingHUD("))
        XCTAssertTrue(content.contains("localization: openCV.confirmationSnapshot.localization"))
        XCTAssertTrue(content.contains("pnp: openCV.pnpSnapshot"))
        XCTAssertTrue(content.contains("wallId: productionRuntime.wallId"))
        XCTAssertTrue(content.contains("cloudAssetsLoaded: productionRuntime.cloudAssetsLoaded"))
        XCTAssertTrue(content.contains("showsStage5HUD ? .hidden : openCV.wallDebugGeometry"))
        XCTAssertTrue(content.contains("KeypointOverlayView("))
        XCTAssertTrue(content.contains("appearance: DebugHUDMode.active.showsStage5HUD ? .scan : .debug"))
        XCTAssertFalse(content.contains("if !DebugHUDMode.active.showsStage5HUD"))
        XCTAssertFalse(content.contains("showsGate4BHUD || DebugHUDMode.active.showsStage5HUD"))
        let stageRange = try XCTUnwrap(content.range(of: "if DebugHUDMode.active.showsStage5HUD {"))
        let stageBlock = String(content[stageRange.lowerBound...])
        XCTAssertTrue(stageBlock.contains("ScanLoadingHUD("))
        XCTAssertTrue(stageBlock.contains("productionFieldRoutes"))
        XCTAssertFalse(stageBlock.contains("FieldTestPanel("))
        XCTAssertFalse(stageBlock.contains("localTestLegend"))
        XCTAssertFalse(stageBlock.contains("Stage5DebugHUD("))
        let gateRange = try XCTUnwrap(content.range(of: "if DebugHUDMode.active.showsGate4BHUD {"))
        let between = String(content[gateRange.lowerBound..<stageRange.lowerBound])
        XCTAssertTrue(between.contains("FieldTestPanel("))
        XCTAssertFalse(between.contains("Stage5DebugHUD("))
    }

    func testGate4BPanelSourceUnchangedForReleaseHUD() throws {
        let panel = try readHostSource("RockVision/Features/FieldTest/FieldTestPanel.swift")
        XCTAssertTrue(panel.contains("Gate4BPhysicalValidationHUD.title"))
        XCTAssertTrue(panel.contains("Start Measurement") || panel.contains("startMeasurementTitle"))
        XCTAssertTrue(panel.contains("localTestLegend"))
        XCTAssertFalse(panel.contains("定位成功"))
        XCTAssertFalse(panel.contains("Stage5DebugHUD"))
        let hud = try readHostSource("RockVision/Features/FieldTest/Gate4BPhysicalValidationHUD.swift")
        XCTAssertTrue(hud.contains("Gate 4B — Physical Validation"))
        XCTAssertTrue(hud.contains("Start Measurement"))
    }

    func testPackageRoutePlanIsNotWallSpecific() throws {
        let processor = try readHostSource("RockVision/Features/OpenCV/OpenCVFrameProcessor.swift")
        XCTAssertTrue(processor.contains("makePackageRoutePlan"))
        XCTAssertFalse(processor.contains("makeJinshidongLocalTestRoutePlan"))
        XCTAssertFalse(processor.contains("jinshidong_local_test"))
        XCTAssertTrue(processor.contains("productionFieldRoutes"))
        XCTAssertTrue(processor.contains("clearProductionCloudRelease"))
        let plan = try readHostSource("RockVision/Features/PnP/RouteRenderPlan.swift")
        XCTAssertTrue(plan.contains("package_routes"))
        XCTAssertFalse(plan.contains("jinshidong_local_test"))
        XCTAssertTrue(plan.contains("ProductionRouteFieldCopy.overlayTitle"))
    }

    private func sampleRoute(
        name: String?,
        grade: String?,
        draws: String?,
        length: Double?
    ) -> VerifiedFrozenRoute {
        VerifiedFrozenRoute(
            routeId: "route_sample",
            wallId: "wall_sample_01",
            coordinateFrame: "WallMetricMeters",
            provenance: "IDENTITY_SUPPORTED",
            dummyOriginExcluded: true,
            polylineSha256: String(repeating: "a", count: 64),
            wallMetricMeters: [[1, 2, 3], [4, 5, 6]],
            hashVerified: true,
            developmentValidationOnly: false,
            sourceArtifact: "routes/sample.dxf",
            routeName: name,
            grade: grade,
            displayDraws: draws,
            lengthMeters: length
        )
    }

    private func candidateURL(_ relative: String, wallId: String) throws -> URL {
        let releaseId = wallId == JiulongfengCatalogLocation.wallId
            ? JiulongfengCatalogLocation.releaseId
            : JinshidongCatalogLocation.releaseId
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("offline/packages/\(wallId)/\(releaseId)")
            .appendingPathComponent(relative)
        guard FileManager.default.isReadableFile(atPath: url.path) else {
            throw XCTSkip("production candidate artifact missing: \(relative)")
        }
        return url
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
