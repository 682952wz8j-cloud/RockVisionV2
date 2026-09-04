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
            wallMarkers: "4/4",
            routeId: "route_test_01",
            hashVerified: true,
            boundPointCount: 11,
            rendered: true,
            visibleSegmentCount: 10
        )
        XCTAssertEqual(rows.map(\.title), Gate4BPhysicalValidationHUD.visibleTitles)
        XCTAssertEqual(rows.first { $0.title == "Scene" }?.value, "A")
        XCTAssertEqual(rows.first { $0.title == "Tracking" }?.value, "normal")
        XCTAssertEqual(rows.first { $0.title == "Localization" }?.value, "localized")
        XCTAssertEqual(rows.first { $0.title == "Confirm" }?.value, "3/3")
        XCTAssertEqual(rows.first { $0.title == "Unique 3D" }?.value, "—")
        XCTAssertEqual(rows.first { $0.title == "PnP inliers" }?.value, "—")
        XCTAssertEqual(rows.first { $0.title == "PnP" }?.value, "inactive")
        XCTAssertEqual(rows.first { $0.title == "T_ARWorld_Wall" }?.value, "valid")
        XCTAssertEqual(rows.first { $0.title == "Wall axes" }?.value, "visible")
        XCTAssertEqual(rows.first { $0.title == "Markers" }?.value, "4/4")
        XCTAssertEqual(rows.first { $0.title == "Route" }?.value, "route_test_01")
        XCTAssertEqual(rows.first { $0.title == "Hash" }?.value, "OK")
        XCTAssertEqual(rows.first { $0.title == "Bound" }?.value, "11")
        XCTAssertEqual(rows.first { $0.title == "Rendered" }?.value, "YES")
        XCTAssertEqual(rows.first { $0.title == "Segments" }?.value, "10")
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

    func testUnfinishedSessionShowsResumeAndHidesStartMeasurement() {
        let unfinished = Gate4BPhysicalValidationHUD.actions(
            hasResumableSession: true,
            phase: .readyToStart(.A)
        )
        XCTAssertTrue(unfinished.showUnfinishedBanner)
        XCTAssertTrue(unfinished.showResume)
        XCTAssertTrue(unfinished.showNewSession)
        XCTAssertFalse(unfinished.showStartMeasurement)
        XCTAssertFalse(unfinished.showShareResults)
        XCTAssertFalse(unfinished.showCopySummary)
        XCTAssertFalse(unfinished.showSceneChips)
        XCTAssertFalse(unfinished.showAbort)
    }

    func testReadyToStartShowsStartMeasurement() {
        let actions = Gate4BPhysicalValidationHUD.actions(
            hasResumableSession: false,
            phase: .readyToStart(.A)
        )
        XCTAssertTrue(actions.showStartMeasurement)
        XCTAssertFalse(actions.showResume)
        XCTAssertFalse(actions.showNewSession)
        XCTAssertFalse(actions.showUnfinishedBanner)
        XCTAssertFalse(actions.showSceneChips)
        XCTAssertFalse(actions.showCopySummary)
        XCTAssertFalse(actions.showAbort)
        XCTAssertFalse(actions.showShareResults)
    }

    func testReadyToStartNextShowsStartMeasurement() {
        let actions = Gate4BPhysicalValidationHUD.actions(
            hasResumableSession: false,
            phase: .readyToStartNext(finished: .A, next: .B)
        )
        XCTAssertTrue(actions.showStartMeasurement)
        XCTAssertFalse(actions.showResume)
        XCTAssertFalse(actions.showSceneChips)
        XCTAssertFalse(actions.showCopySummary)
    }

    func testStartMeasurementWiresToStartOfficialNext() throws {
        XCTAssertEqual(Gate4BPhysicalValidationHUD.startMeasurementTitle, "Start Measurement")
        XCTAssertEqual(Gate4BPhysicalValidationHUD.startMeasurementControllerMethod, "startOfficialNext")
        let panel = try String(
            contentsOfFile: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/FieldTest/FieldTestPanel.swift")
                .path,
            encoding: .utf8
        )
        XCTAssertTrue(panel.contains("Gate4BPhysicalValidationHUD.startMeasurementTitle"))
        XCTAssertTrue(panel.contains("action: controller.startOfficialNext"))
        XCTAssertFalse(panel.contains("action: controller.startScene"))
        XCTAssertFalse(panel.contains("Start A"))
        XCTAssertFalse(panel.contains("Continue A"))
    }

    func testSamplingAndWaitingTrackingHideStartMeasurement() {
        let waiting = Gate4BPhysicalValidationHUD.actions(
            hasResumableSession: false,
            phase: .waitingTracking(scene: .A, preset: .low)
        )
        XCTAssertFalse(waiting.showStartMeasurement)
        XCTAssertTrue(waiting.showAbort)
        let sampling = Gate4BPhysicalValidationHUD.actions(
            hasResumableSession: false,
            phase: .sampling(scene: .A, preset: .low)
        )
        XCTAssertFalse(sampling.showStartMeasurement)
        XCTAssertTrue(sampling.showAbort)
        XCTAssertFalse(sampling.showNewSession)
        XCTAssertFalse(sampling.showShareResults)
    }

    func testCompleteShowsNewSessionAndShareResults() {
        let actions = Gate4BPhysicalValidationHUD.actions(
            hasResumableSession: false,
            phase: .complete,
            canExport: true
        )
        XCTAssertFalse(actions.showStartMeasurement)
        XCTAssertTrue(actions.showNewSession)
        XCTAssertTrue(actions.showShareResults)
        XCTAssertFalse(actions.showResume)
        XCTAssertFalse(actions.showSceneChips)
        XCTAssertFalse(actions.showCopySummary)
    }

    func testABCChipsRemainHidden() {
        let phases: [FieldTestPhase] = [
            .readyToStart(.A),
            .readyToStartNext(finished: .A, next: .B),
            .waitingTracking(scene: .A, preset: .low),
            .sampling(scene: .A, preset: .low),
            .complete,
            .idle
        ]
        for phase in phases {
            let actions = Gate4BPhysicalValidationHUD.actions(hasResumableSession: false, phase: phase)
            XCTAssertFalse(actions.showSceneChips, "\(phase)")
        }
        let unfinished = Gate4BPhysicalValidationHUD.actions(hasResumableSession: true, phase: .readyToStart(.A))
        XCTAssertFalse(unfinished.showSceneChips)
    }

    func testCopySummaryRemainsHidden() {
        let phases: [FieldTestPhase] = [
            .readyToStart(.A),
            .readyToStartNext(finished: .A, next: .B),
            .complete,
            .idle
        ]
        for phase in phases {
            let actions = Gate4BPhysicalValidationHUD.actions(
                hasResumableSession: false,
                phase: phase,
                canExport: true
            )
            XCTAssertFalse(actions.showCopySummary, "\(phase)")
        }
        XCTAssertFalse(
            Gate4BPhysicalValidationHUD.actions(hasResumableSession: true).showCopySummary
        )
    }

    func testStartMeasurementKeepsLaunchGate() {
        XCTAssertTrue(
            Gate4BPhysicalValidationHUD.startMeasurementEnabled(
                canStartTest: true,
                storageReady: true,
                tracking: "normal",
                matchingStatus: "active",
                presetLabel: "960×720",
                processingLabel: "960×720"
            )
        )
        XCTAssertFalse(
            Gate4BPhysicalValidationHUD.startMeasurementEnabled(
                canStartTest: true,
                storageReady: true,
                tracking: "limited",
                matchingStatus: "active",
                presetLabel: "960×720",
                processingLabel: "960×720"
            )
        )
        XCTAssertFalse(
            Gate4BPhysicalValidationHUD.startMeasurementEnabled(
                canStartTest: false,
                storageReady: false,
                tracking: "normal",
                matchingStatus: "active",
                presetLabel: "960×720",
                processingLabel: "960×720"
            )
        )
    }

    func testShareResultsDoesNotReplaceStartMeasurementWhenReady() {
        let ready = Gate4BPhysicalValidationHUD.actions(
            hasResumableSession: false,
            phase: .readyToStart(.A),
            canExport: true
        )
        XCTAssertTrue(ready.showStartMeasurement)
        XCTAssertTrue(ready.showShareResults)
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
        XCTAssertEqual(rows.map(\.title), Gate4BPhysicalValidationHUD.mappedDiagnosticTitles)
        XCTAssertEqual(rows.first { $0.title == "Query kp" }?.value, "12")
        XCTAssertEqual(rows.first { $0.title == "Unique 3D" }?.value, "7")
        XCTAssertEqual(rows.first { $0.title == "PnP" }?.value, "ok")
        XCTAssertEqual(rows.first { $0.title == "RANSAC inliers" }?.value, "30")
        XCTAssertEqual(rows.first { $0.title == "C_wall" }?.value, "1,2,3")
        XCTAssertEqual(rows.first { $0.title == "obs-depth sanity" }?.value, "ok")
    }

    func testStage3EvidenceRowsUseExistingSnapshots() {
        var matching = MatchingRuntimeSnapshot()
        matching.acceptedUniquePoint3D = "11"
        matching.acceptedAfterRatio = "20"
        matching.queryKeypoints = "80"
        var pnp = PnPRuntimeSnapshot()
        pnp.inliers = "28"
        pnp.status = "candidate"
        pnp.localization = "idle"
        pnp.inlierRatio = "0.70"
        pnp.reproj = "0.50 px"
        let rows = Gate4BPhysicalValidationHUD.stage3EvidenceRows(matching: matching, pnp: pnp)
        XCTAssertEqual(rows.map(\.title), ["Unique 3D", "PnP inliers", "PnP"])
        XCTAssertEqual(rows.first { $0.title == "Unique 3D" }?.value, matching.acceptedUniquePoint3D)
        XCTAssertEqual(rows.first { $0.title == "PnP inliers" }?.value, pnp.inliers)
        XCTAssertEqual(rows.first { $0.title == "PnP" }?.value, pnp.status)
        XCTAssertNotEqual(rows.first { $0.title == "PnP" }?.value, pnp.localization)
        XCTAssertFalse(rows.contains { $0.title == "Query kp" })
        XCTAssertFalse(rows.contains { $0.title == "Accepted" })
        XCTAssertFalse(rows.contains { $0.title == "Inlier ratio" })
        XCTAssertFalse(rows.contains { $0.title == "Reproj" })
        XCTAssertFalse(rows.contains { $0.title == "RANSAC inliers" })
    }

    func testVisibleHUDKeepsConfirmationStateAndMinimumStage3Evidence() {
        var matching = MatchingRuntimeSnapshot()
        matching.acceptedUniquePoint3D = "9"
        var pnp = PnPRuntimeSnapshot()
        pnp.inliers = "22"
        pnp.status = "candidate"
        pnp.localization = "idle"
        let rows = Gate4BPhysicalValidationHUD.visibleRows(
            scene: "A",
            tracking: "normal",
            localization: "localized",
            confirmationWindow: "3/3",
            alignment: "yes 12",
            wallAxes: "visible",
            wallMarkers: "4/4",
            matching: matching,
            pnp: pnp
        )
        XCTAssertEqual(rows.first { $0.title == "Localization" }?.value, "localized")
        XCTAssertEqual(rows.first { $0.title == "Confirm" }?.value, "3/3")
        XCTAssertEqual(rows.first { $0.title == "Unique 3D" }?.value, "9")
        XCTAssertEqual(rows.first { $0.title == "PnP inliers" }?.value, "22")
        XCTAssertEqual(rows.first { $0.title == "PnP" }?.value, "candidate")
        XCTAssertNotEqual(rows.first { $0.title == "PnP" }?.value, pnp.localization)
        let titles = rows.map(\.title)
        XCTAssertFalse(titles.contains("Query kp"))
        XCTAssertFalse(titles.contains("Accepted"))
        XCTAssertFalse(titles.contains("SIFT"))
        XCTAssertFalse(titles.contains("Match"))
        XCTAssertFalse(titles.contains("Stage3"))
        XCTAssertFalse(titles.contains("PnP in"))
        XCTAssertFalse(titles.contains("RANSAC inliers"))
        XCTAssertFalse(titles.contains("Inlier ratio"))
        XCTAssertFalse(titles.contains("Reproj"))
        XCTAssertFalse(titles.contains("C_wall"))
        XCTAssertFalse(titles.contains("obs-depth sanity"))
    }

    func testStage3EvidenceMappingIsSourceAgnostic() throws {
        var matching = MatchingRuntimeSnapshot()
        matching.acceptedUniquePoint3D = "15"
        var pnp = PnPRuntimeSnapshot()
        pnp.inliers = "31"
        pnp.status = "candidate"
        let bundleRows = Gate4BPhysicalValidationHUD.stage3EvidenceRows(matching: matching, pnp: pnp)
        let cloudRows = Gate4BPhysicalValidationHUD.stage3EvidenceRows(matching: matching, pnp: pnp)
        XCTAssertEqual(bundleRows, cloudRows)
        let hud = try String(
            contentsOfFile: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/FieldTest/Gate4BPhysicalValidationHUD.swift")
                .path,
            encoding: .utf8
        )
        XCTAssertFalse(hud.contains("cloudValidatedRelease"))
        XCTAssertFalse(hud.contains("developmentFixture"))
        XCTAssertFalse(hud.contains("wall_jiulongfeng"))
        let panel = try String(
            contentsOfFile: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/FieldTest/FieldTestPanel.swift")
                .path,
            encoding: .utf8
        )
        XCTAssertTrue(panel.contains("matching: matching"))
        XCTAssertTrue(panel.contains("pnp: pnp"))
        XCTAssertFalse(panel.contains("cloudValidatedRelease"))
        let content = try String(
            contentsOfFile: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/App/ContentView.swift")
                .path,
            encoding: .utf8
        )
        XCTAssertTrue(content.contains("localization: openCV.confirmationSnapshot.localization"))
        XCTAssertTrue(content.contains("confirmationWindow: openCV.confirmationSnapshot.window"))
        XCTAssertFalse(content.contains("pnpSnapshot.localization"))
        XCTAssertTrue(content.contains("matching: openCV.matchingSnapshot"))
        XCTAssertTrue(content.contains("pnp: openCV.pnpSnapshot"))
    }

    func testExportSchemaIsGate5DARuntime() throws {
        XCTAssertEqual(FieldTestExportSchema.version, "gate5da.runtime.1")
        XCTAssertEqual(FieldTestExportSchema.legacyGate4BRuntimeVersion, "gate4b.runtime.1")
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

    func testHUDHasNoRouteCorrectionControls() throws {
        let hud = try String(
            contentsOfFile: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/FieldTest/Gate4BPhysicalValidationHUD.swift")
                .path,
            encoding: .utf8
        )
        let panel = try String(
            contentsOfFile: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/FieldTest/FieldTestPanel.swift")
                .path,
            encoding: .utf8
        )
        for source in [hud, panel] {
            XCTAssertFalse(source.contains("Slider"))
            XCTAssertFalse(source.contains("routeOffset"))
            XCTAssertFalse(source.contains("routeScale"))
            XCTAssertFalse(source.contains("routeYaw"))
            XCTAssertFalse(source.contains("nudge"))
            XCTAssertFalse(source.contains("correction"))
        }
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
