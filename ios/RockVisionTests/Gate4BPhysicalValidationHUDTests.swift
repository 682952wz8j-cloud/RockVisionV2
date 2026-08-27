import XCTest
@testable import RockVision

final class Gate4BPhysicalValidationHUDTests: XCTestCase {
    func testVisibleRowsAreGate4BMeasurementFields() {
        let rows = Gate4BPhysicalValidationHUD.visibleRows(
            scene: "A",
            tracking: "normal",
            localization: "localized",
            confirmationWindow: "3/3",
            alignment: "yes 12",
            wallAxes: "X=1.000 Y=1.000 Z=1.000 m",
            wallMarkers: "4/4"
        )
        XCTAssertEqual(rows.map(\.title), Gate4BPhysicalValidationHUD.visibleTitles)
        XCTAssertEqual(rows.first { $0.title == "Scene" }?.value, "A")
        XCTAssertEqual(rows.first { $0.title == "Tracking" }?.value, "normal")
        XCTAssertEqual(rows.first { $0.title == "Localization" }?.value, "localized")
        XCTAssertEqual(rows.first { $0.title == "Confirm" }?.value, "3/3")
        XCTAssertEqual(rows.first { $0.title == "T_ARWorld_Wall" }?.value, "valid")
        XCTAssertEqual(rows.first { $0.title == "Wall axes" }?.value, "visible")
        XCTAssertEqual(rows.first { $0.title == "Markers" }?.value, "4/4")
    }

    func testHiddenDiagnosticTitlesAreNotInVisibleHUD() throws {
        let rows = Gate4BPhysicalValidationHUD.visibleRows(
            scene: "A",
            tracking: "normal",
            localization: "localized",
            confirmationWindow: "3/3",
            alignment: "none",
            wallAxes: "hidden",
            wallMarkers: "0/4"
        )
        let titles = Set(rows.map(\.title))
        for hidden in Gate4BPhysicalValidationHUD.hiddenDiagnosticTitles {
            XCTAssertFalse(titles.contains(hidden), hidden)
        }
        let panel = try? String(
            contentsOfFile: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/FieldTest/FieldTestPanel.swift")
                .path,
            encoding: .utf8
        )
        let body = try XCTUnwrap(panel)
        XCTAssertFalse(body.contains("statusRow(\"Query kp\""))
        XCTAssertFalse(body.contains("statusRow(\"Processing\""))
        XCTAssertFalse(body.contains("Copy Summary"))
        XCTAssertFalse(body.contains("sceneChip"))
    }

    func testMarkersRowUsesMeasurementCountNotValidatedLandmarkCount() {
        let rows = Gate4BPhysicalValidationHUD.visibleRows(
            scene: "A",
            tracking: "normal",
            localization: "localized",
            confirmationWindow: "3/3",
            alignment: "yes 1",
            wallAxes: "visible-source",
            wallMarkers: "4/4"
        )
        XCTAssertEqual(rows.first { $0.title == "Markers" }?.value, "4/4")
        let geometry = WallAlignmentDebugGeometry.evaluate(alignment: .none)
        XCTAssertEqual(geometry.validatedLandmarkCount, 0)
        XCTAssertNotEqual(rows.first { $0.title == "Markers" }?.value, "\(geometry.validatedLandmarkCount)")
    }

    func testValidatedLandmarkCountRemainsZeroWhenMarkersPresent() throws {
        let fixture = try loadFixture()
        let t: [[Double]] = [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ]
        let geom = WallAlignmentDebugGeometry.evaluate(
            alignment: AlignmentFrameResult.aligned(
                transform: t,
                provenance: AlignmentProvenance(
                    confirmedFrameID: 1,
                    confirmedTimestamp: 1,
                    T_opencvCam_colmap: t,
                    arFrameID: 1,
                    arFrameTimestamp: 1,
                    T_ARWorld_arkitCam: t
                ),
                confirmedEqualsLatestRefined: true
            ),
            measurementFixture: fixture,
            currentWallID: Gate4BMeasurementFixture.expectedWallID
        )
        XCTAssertEqual(geom.markerCount, 4)
        XCTAssertEqual(geom.validatedLandmarkCount, 0)
        let snapshot = WallDebugSnapshot.make(geom)
        XCTAssertEqual(snapshot.markers, "4/4")
        let rows = Gate4BPhysicalValidationHUD.visibleRows(
            scene: "A",
            tracking: "normal",
            localization: "localized",
            confirmationWindow: "3/3",
            alignment: "yes 1",
            wallAxes: "yes",
            wallMarkers: snapshot.markers
        )
        XCTAssertEqual(rows.first { $0.title == "Markers" }?.value, "4/4")
    }

    func testSceneChipsHiddenAndPrimaryActionsVisible() {
        let actions = Gate4BPhysicalValidationHUD.actions(hasResumableSession: false)
        XCTAssertFalse(actions.showSceneChips)
        XCTAssertTrue(actions.showNewSession)
        XCTAssertTrue(actions.showShareResults)
        XCTAssertFalse(actions.showCopySummary)
        XCTAssertFalse(actions.showResume)
        XCTAssertFalse(actions.showUnfinishedBanner)
    }

    func testResumeOnlyWhenUnfinishedSession() {
        let unfinished = Gate4BPhysicalValidationHUD.actions(hasResumableSession: true)
        XCTAssertTrue(unfinished.showUnfinishedBanner)
        XCTAssertTrue(unfinished.showResume)
        XCTAssertTrue(unfinished.showNewSession)
        XCTAssertFalse(unfinished.showShareResults)
        XCTAssertFalse(unfinished.showCopySummary)
        XCTAssertFalse(unfinished.showSceneChips)
    }

    func testDiagnosticRowsStillMappedFromSnapshots() {
        var matching = MatchingRuntimeSnapshot()
        matching.status = "active"
        matching.queryKeypoints = "12"
        matching.acceptedAfterRatio = "8"
        matching.acceptedUniquePoint3D = "7"
        matching.matchingMs = "3.2"
        matching.stage3Ms = "4.1"
        var sift = SIFTRuntimeSnapshot()
        sift.siftMs = "5.0"
        var pnp = PnPRuntimeSnapshot()
        pnp.status = "ok"
        pnp.inputCorr = "40"
        pnp.inliers = "30"
        pnp.inlierRatio = "0.75"
        pnp.reproj = "0.4"
        pnp.cWall = "1,2,3"
        pnp.obsDepth = "ok"
        let rows = Gate4BPhysicalValidationHUD.diagnosticRows(
            processing: "960×720",
            valid: "0 / 30",
            matching: matching,
            sift: sift,
            pnp: pnp
        )
        XCTAssertEqual(rows.map(\.title), Gate4BPhysicalValidationHUD.hiddenDiagnosticTitles)
        XCTAssertEqual(rows.first { $0.title == "Query kp" }?.value, "12")
        XCTAssertEqual(rows.first { $0.title == "C_wall" }?.value, "1,2,3")
        XCTAssertEqual(rows.first { $0.title == "obs-depth sanity" }?.value, "ok")
    }

    func testExportSchemaUnchanged() throws {
        XCTAssertEqual(FieldTestExportSchema.version, "gate4b.runtime.1")
        let export = try String(
            contentsOfFile: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/FieldTest/FieldTestExport.swift")
                .path,
            encoding: .utf8
        )
        XCTAssertTrue(export.contains("measurementMarkers:"))
        XCTAssertTrue(export.contains("validatedLandmarks:"))
        XCTAssertTrue(export.contains("FieldTestExportSchema.version"))
        XCTAssertFalse(export.contains("physicalErrorMeters"))
    }

    private func loadFixture() throws -> Gate4BMeasurementFixture {
        if let bundled = Gate4BMeasurementFixture.loadFromBundle(Bundle(for: OpenCVFrameProcessor.self)) {
            return bundled
        }
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("RockVision/Resources/Gate4BMeasurementFixture.json")
        return try Gate4BMeasurementFixture.load(from: url)
    }
}
