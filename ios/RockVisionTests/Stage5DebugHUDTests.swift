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
        let lines = Stage5DebugHUDModel.lines(
            localization: "localized",
            pnp: pnp,
            wallId: "wall_jinshidong_01",
            cloudAssetsLoaded: true
        )
        XCTAssertEqual(lines, [
            "定位成功",
            "PnP 28 | 1.40 px",
            "wall_jinshidong_01",
            "云端资产：已加载"
        ])
    }

    func testNonLocalizedStatesShowFailure() {
        for state in [ConfirmationConfig.localizationIdle, ConfirmationConfig.localizationConfirming, "lost"] {
            XCTAssertEqual(Stage5DebugHUDModel.localizationLine(state: state), "定位失败")
        }
        let lines = Stage5DebugHUDModel.lines(
            localization: "idle",
            pnp: PnPRuntimeSnapshot(),
            wallId: "",
            cloudAssetsLoaded: false
        )
        XCTAssertEqual(lines.first, "定位失败")
        XCTAssertEqual(lines.count, 4)
        XCTAssertEqual(lines[2], "—")
        XCTAssertEqual(lines[3], "云端资产：加载失败")
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

    func testStage5HUDSourceContainsOnlyTheTwoEvidenceLines() throws {
        let hud = try readHostSource("RockVision/Features/DebugOverlay/Stage5DebugHUD.swift")
        XCTAssertTrue(hud.contains("定位成功"))
        XCTAssertTrue(hud.contains("定位失败"))
        XCTAssertTrue(hud.contains("PnP \\(inliers)"))
        XCTAssertTrue(hud.contains("medianToken"))
        XCTAssertTrue(hud.contains("云端资产：已加载"))
        XCTAssertTrue(hud.contains("云端资产：加载失败"))
        XCTAssertFalse(hud.contains("Start Measurement"))
        XCTAssertFalse(hud.contains("Gate 4B"))
        XCTAssertFalse(hud.contains("Jinshidong local test"))
        XCTAssertFalse(hud.contains("FieldTestPanel"))
        XCTAssertFalse(hud.contains("localTestLegend"))
    }

    func testContentViewKeepsGate4BPanelOffStage5HUD() throws {
        let content = try readHostSource("RockVision/App/ContentView.swift")
        XCTAssertTrue(content.contains("if DebugHUDMode.active.showsGate4BHUD {"))
        XCTAssertTrue(content.contains("FieldTestPanel("))
        XCTAssertTrue(content.contains("if DebugHUDMode.active.showsStage5HUD {"))
        XCTAssertTrue(content.contains("Stage5DebugHUD("))
        XCTAssertTrue(content.contains("localization: openCV.confirmationSnapshot.localization"))
        XCTAssertTrue(content.contains("pnp: openCV.pnpSnapshot"))
        XCTAssertTrue(content.contains("wallId: productionRuntime.wallId"))
        XCTAssertTrue(content.contains("cloudAssetsLoaded: productionRuntime.cloudAssetsLoaded"))
        XCTAssertFalse(content.contains("showsGate4BHUD || DebugHUDMode.active.showsStage5HUD"))
        let stageRange = try XCTUnwrap(content.range(of: "if DebugHUDMode.active.showsStage5HUD {"))
        let stageBlock = String(content[stageRange.lowerBound...])
        XCTAssertTrue(stageBlock.contains("Stage5DebugHUD("))
        XCTAssertFalse(stageBlock.contains("FieldTestPanel("))
        XCTAssertFalse(stageBlock.contains("localTestLegend"))
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
