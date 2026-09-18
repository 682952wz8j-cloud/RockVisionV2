import XCTest
@testable import RockVision

final class ScanLoadingTests: XCTestCase {
    func testSessionResetDropsPreviousSuccessAndIgnoresOldReceipt() {
        let old = UUID()
        let next = UUID()
        var state = ScanLoadingState.fresh(attemptId: old, wallId: "wall_a", now: 0)
        let receipt = RouteApplyReceipt(attemptId: old, wallId: "wall_a", renderedRoute: true, routeId: "route_1", visibleSegmentCount: 2)
        ScanLoadingReducer.ingest(&state, facts: facts(localization: ConfirmationConfig.localizationLocalized, matching: "active", cloud: true, wallId: "wall_a", receipt: receipt), now: 1, newAttemptId: { UUID() })
        XCTAssertEqual(state.load, .success)
        ScanLoadingReducer.ingest(&state, facts: facts(localization: "idle", matching: "active", cloud: true, wallId: "wall_a", receipt: receipt), now: 2, newAttemptId: { next })
        XCTAssertEqual(state.attemptId, next)
        XCTAssertEqual(state.identify, .pending)
        XCTAssertEqual(state.load, .pending)
        XCTAssertFalse(state.didJump)
    }

    func testPermissionAndLocationErrorsAreNotNetworkErrors() {
        XCTAssertEqual(ScanLoadingReducer.classifiedError(WallLocationError.permissionDenied.errorDescription), .locationPermission)
        XCTAssertEqual(ScanLoadingReducer.classifiedError(WallLocationError.unavailable.errorDescription), .locationUnavailable)
        XCTAssertEqual(ScanLoadingReducer.classifiedError("camera permission denied"), .cameraPermission)
        XCTAssertEqual(ScanLoadingReducer.classifiedError("camera unavailable"), .cameraUnavailable)
        var state = ScanLoadingState.fresh(attemptId: UUID(), wallId: "—", now: 0)
        ScanLoadingReducer.ingest(&state, facts: facts(localization: "idle", matching: "inactive", cloud: false, wallId: "—", error: "location permission denied"), now: 1, newAttemptId: { UUID() })
        XCTAssertTrue(state.hardError)
        XCTAssertEqual(state.hint, .locationPermission)
        XCTAssertEqual(state.identify, .pending)
    }

    func testCloudReadyDoesNotMarkIdentifySuccess() {
        var state = ScanLoadingState.fresh(attemptId: UUID(), wallId: "wall_a", now: 0)
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(localization: "idle", matching: "active", cloud: true, wallId: "wall_a"),
            now: 1,
            newAttemptId: { UUID() }
        )
        XCTAssertEqual(state.identify, .pending)
        XCTAssertEqual(state.localize, .pending)
        XCTAssertEqual(state.load, .pending)
        XCTAssertFalse(state.didJump)
    }

    func testFirstLocalizedCompletesIdentifyAndLocalizeTogether() {
        var state = ScanLoadingState.fresh(attemptId: UUID(), wallId: "wall_a", now: 0)
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(localization: ConfirmationConfig.localizationLocalized, matching: "active", cloud: true, wallId: "wall_a"),
            now: 1,
            newAttemptId: { UUID() }
        )
        XCTAssertEqual(state.identify, .success)
        XCTAssertEqual(state.localize, .success)
        XCTAssertEqual(state.load, .pending)
        XCTAssertEqual(state.clip, .run)
        XCTAssertFalse(state.didJump)
    }

    func testWouldRenderWithoutApplyReceiptDoesNotJump() {
        var state = ScanLoadingState.fresh(attemptId: UUID(), wallId: "wall_a", now: 0)
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(
                localization: ConfirmationConfig.localizationLocalized,
                matching: "active",
                cloud: true,
                wallId: "wall_a",
                receipt: .none
            ),
            now: 1,
            newAttemptId: { UUID() }
        )
        XCTAssertEqual(state.load, .pending)
        XCTAssertFalse(state.didJump)
    }

    func testRenderedRouteReceiptJumpsOnce() {
        let attempt = UUID()
        var state = ScanLoadingState.fresh(attemptId: attempt, wallId: "wall_a", now: 0)
        let receipt = RouteApplyReceipt(
            attemptId: attempt,
            wallId: "wall_a",
            renderedRoute: true,
            routeId: "route_1",
            visibleSegmentCount: 10
        )
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(
                localization: ConfirmationConfig.localizationLocalized,
                matching: "active",
                cloud: true,
                wallId: "wall_a",
                receipt: receipt
            ),
            now: 1,
            newAttemptId: { UUID() }
        )
        XCTAssertEqual(state.load, .success)
        XCTAssertTrue(state.didJump)
        XCTAssertEqual(state.clip, .jump)
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(
                localization: ConfirmationConfig.localizationLocalized,
                matching: "active",
                cloud: true,
                wallId: "wall_a",
                receipt: receipt
            ),
            now: 2,
            newAttemptId: { UUID() }
        )
        XCTAssertEqual(state.clip, .jump)
        XCTAssertTrue(state.didJump)
    }

    func testStaleReceiptIsIgnored() {
        let attempt = UUID()
        var state = ScanLoadingState.fresh(attemptId: attempt, wallId: "wall_a", now: 0)
        let stale = RouteApplyReceipt(
            attemptId: UUID(),
            wallId: "wall_a",
            renderedRoute: true,
            routeId: "old",
            visibleSegmentCount: 10
        )
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(
                localization: ConfirmationConfig.localizationLocalized,
                matching: "active",
                cloud: true,
                wallId: "wall_a",
                receipt: stale
            ),
            now: 1,
            newAttemptId: { UUID() }
        )
        XCTAssertEqual(state.load, .pending)
        XCTAssertFalse(state.didJump)
    }

    func testElapsedTimeDoesNotMarkSuccess() {
        var state = ScanLoadingState.fresh(attemptId: UUID(), wallId: "wall_a", now: 0)
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(localization: "confirming", matching: "active", cloud: true, wallId: "wall_a"),
            now: 30,
            newAttemptId: { UUID() }
        )
        XCTAssertEqual(state.identify, .pending)
        XCTAssertEqual(state.localize, .pending)
        XCTAssertEqual(state.hint, .aimAtWall)
    }

    func testLostLocalizedResetsOnce() {
        let first = UUID()
        var created: [UUID] = []
        var state = ScanLoadingState.fresh(attemptId: first, wallId: "wall_a", now: 0)
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(localization: ConfirmationConfig.localizationLocalized, matching: "active", cloud: true, wallId: "wall_a"),
            now: 1,
            newAttemptId: { UUID() }
        )
        XCTAssertEqual(state.identify, .success)
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(
                localization: "idle",
                lost: true,
                matching: "active",
                cloud: true,
                wallId: "wall_a"
            ),
            now: 2,
            newAttemptId: {
                let id = UUID()
                created.append(id)
                return id
            }
        )
        XCTAssertEqual(created.count, 1)
        XCTAssertEqual(state.identify, .pending)
        XCTAssertEqual(state.localize, .pending)
        XCTAssertTrue(state.handledLostPulse)
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(
                localization: "idle",
                lost: true,
                matching: "active",
                cloud: true,
                wallId: "wall_a"
            ),
            now: 2.1,
            newAttemptId: {
                let id = UUID()
                created.append(id)
                return id
            }
        )
        XCTAssertEqual(created.count, 1)
    }

    func testNetworkErrorStopsProgressAndDoesNotSucceed() {
        var state = ScanLoadingState.fresh(attemptId: UUID(), wallId: "wall_a", now: 0)
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(
                localization: "idle",
                matching: "inactive",
                cloud: false,
                wallId: "wall_a",
                error: "network NSURLErrorDomain -1009"
            ),
            now: 1,
            newAttemptId: { UUID() }
        )
        XCTAssertTrue(state.hardError)
        XCTAssertEqual(state.identify, .pending)
        XCTAssertEqual(state.hint, .network)
        XCTAssertNotEqual(ScanLoadingReducer.hintText(state.hint), "请对准岩壁重新扫描")
        ScanLoadingReducer.tick(&state, dt: 0.5, matchingActive: false)
        XCTAssertEqual(state.speed, 0, accuracy: 0.02)
    }

    func testWaitingDoesNotCrossIdentifyCap() {
        var state = ScanLoadingState.fresh(attemptId: UUID(), wallId: "wall_a", now: 0)
        state.position = ScanLoadingMotion.identifyCap - 0.01
        state.speed = 0.2
        ScanLoadingReducer.tick(&state, dt: 0.25, matchingActive: true)
        XCTAssertLessThanOrEqual(state.position, ScanLoadingMotion.identifyCap + 1e-9)
        XCTAssertEqual(state.identify, .pending)
    }

    func testGeometryOnlyStripsLabelsWithoutChangingSegments() {
        let route = VerifiedFrozenRoute(
            routeId: "route_1",
            wallId: "wall_a",
            coordinateFrame: "WallMetricMeters",
            provenance: "IDENTITY_SUPPORTED",
            dummyOriginExcluded: true,
            polylineSha256: String(repeating: "a", count: 64),
            wallMetricMeters: [[0, 0, 0], [1, 0, 0]],
            hashVerified: true,
            developmentValidationOnly: false,
            sourceArtifact: "x",
            routeName: "爬爬爬",
            grade: "5.9",
            displayDraws: "3+2"
        )
        let binding = RuntimeRouteBinding(
            routeId: route.routeId,
            hashVerified: true,
            hasBoundRoute: true,
            routeARWorldPointCount: 2,
            routeARWorldPoints: [[0, 0, 0], [1, 0, 0]],
            renderedRoute: false,
            reason: nil
        )
        let plan = RouteRenderPlan.evaluateLocalTest(from: binding, route: route)
        XCTAssertFalse(plan.labels.isEmpty)
        let geometry = plan.geometryOnly()
        XCTAssertTrue(geometry.labels.isEmpty)
        XCTAssertEqual(geometry.segments, plan.segments)
        XCTAssertEqual(geometry.wouldRender, plan.wouldRender)
        XCTAssertEqual(geometry.stroke, .fieldTestRed)
        let card = ProductionRouteFieldCopy.screenCard(route)
        XCTAssertEqual(card.name, "爬爬爬")
        XCTAssertEqual(card.grade, "5.9")
        XCTAssertEqual(card.secondary, ["🔗 3+2"])
        XCTAssertFalse(card.secondary.contains { $0.contains("bolt") })
        XCTAssertEqual(ProductionRouteFieldCopy.quickdrawLine("3+2"), "🔗 3+2")
        XCTAssertNil(ProductionRouteFieldCopy.quickdrawLine("5 bolts"))
    }

    func testExitHidesMascotAndStatusChromeOnly() {
        let attempt = UUID()
        var state = ScanLoadingState.fresh(attemptId: attempt, wallId: "wall_a", now: 0)
        let receipt = RouteApplyReceipt(
            attemptId: attempt,
            wallId: "wall_a",
            renderedRoute: true,
            routeId: "route_1",
            visibleSegmentCount: 10
        )
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(
                localization: ConfirmationConfig.localizationLocalized,
                matching: "active",
                cloud: true,
                wallId: "wall_a",
                receipt: receipt
            ),
            now: 1,
            newAttemptId: { UUID() }
        )
        state.jumpElapsed = ScanLoadingMotion.jumpDuration
        state.clip = .run
        state.position = ScanLoadingMotion.exitPosition - 0.01
        state.speed = ScanLoadingMotion.exitSpeed
        ScanLoadingReducer.tick(&state, dt: 0.05, matchingActive: false)
        XCTAssertTrue(state.mascotHidden)
        XCTAssertTrue(state.hideChrome)
        XCTAssertEqual(state.identify, .success)
        XCTAssertEqual(state.localize, .success)
        XCTAssertEqual(state.load, .success)
        XCTAssertTrue(state.lastConsumedReceipt.renderedRoute)
    }

    func testRouteLabelsStayIndependentOfMascotExit() throws {
        let hud = try String(
            contentsOf: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/ScanLoading/ScanLoadingHUD.swift")
        )
        XCTAssertTrue(hud.contains("RouteScreenLabelOverlay("))
        XCTAssertTrue(hud.contains("liveSamples"))
        XCTAssertTrue(hud.contains("snapshot.isLive"))
        XCTAssertFalse(hud.contains("state.load == .success ? bridge.screenLabels"))
        XCTAssertFalse(hud.contains("if !state.hideChrome {\n                    RouteScreenLabelOverlay"))
        XCTAssertTrue(hud.contains("ScanLoadingCopy.identifyPending"))
        XCTAssertTrue(hud.contains("AppPixelFont.font"))
        let preview = try String(
            contentsOf: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/ARSessionHost/ARCameraPreview.swift")
        )
        XCTAssertTrue(preview.contains("if state.renderedRoute"))
        XCTAssertTrue(preview.contains("view.project(world)"))
        XCTAssertTrue(preview.contains("view.bounds.contains(point)"))
        XCTAssertFalse(preview.contains("mascotHidden"))
        XCTAssertFalse(preview.contains("hideChrome"))
    }

    func testRenderedRouteFalseDoesNotTriggerLoad() {
        let attempt = UUID()
        var state = ScanLoadingState.fresh(attemptId: attempt, wallId: "wall_a", now: 0)
        let receipt = RouteApplyReceipt(
            attemptId: attempt,
            wallId: "wall_a",
            renderedRoute: false,
            routeId: "route_1",
            visibleSegmentCount: 0
        )
        ScanLoadingReducer.ingest(
            &state,
            facts: facts(
                localization: ConfirmationConfig.localizationLocalized,
                matching: "active",
                cloud: true,
                wallId: "wall_a",
                receipt: receipt
            ),
            now: 1,
            newAttemptId: { UUID() }
        )
        XCTAssertEqual(state.load, .pending)
        XCTAssertFalse(state.didJump)
    }

    func testMascotLoaderDoesNotUseDownloadsPaths() throws {
        XCTAssertEqual(MascotSequence.runFrameCount, 8)
        XCTAssertEqual(MascotSequence.jumpFrameCount, 23)
        XCTAssertEqual(MascotSequence.framesPerSecond, 12)
        XCTAssertEqual(MascotSequence.runSourceFrames, [29, 30, 32, 33, 34, 35, 37, 38])
        XCTAssertEqual(MascotSequence.jumpSourceFrames.first, 178)
        XCTAssertEqual(MascotSequence.jumpSourceFrames.last, 232)
        let loader = try String(
            contentsOf: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/ScanLoading/MascotSequence.swift")
        )
        XCTAssertTrue(loader.contains("MascotLime"))
        XCTAssertTrue(loader.contains("Bundle(for: ScanSessionBridge.self)"))
        XCTAssertFalse(loader.contains("Downloads"))
        XCTAssertFalse(loader.contains("/Users/"))
        let pbx = try String(
            contentsOf: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision.xcodeproj/project.pbxproj")
        )
        XCTAssertTrue(pbx.contains("MascotLime in Resources"))
        XCTAssertFalse(pbx.contains("mascot_lime_transparent_png_sequence.zip"))
        XCTAssertFalse(pbx.contains("mascot_lime_transparent_prores4444.mov"))
        XCTAssertFalse(pbx.contains("design-assets"))
        XCTAssertNotNil(MascotSequence.image(clip: .run, index: 0))
        XCTAssertNotNil(MascotSequence.image(clip: .jump, index: 0))
    }

    func testEngineeringDiagnosticsOmitsLimeAndUsesLiveFields() {
        var pnp = PnPRuntimeSnapshot()
        pnp.inliers = "21"
        pnp.reproj = "0.90 px"
        let lines = EngineeringDiagnosticsModel.lines(
            localization: "localized",
            window: "3/3",
            pnp: pnp,
            wallId: "wall_a",
            cloudAssetsLoaded: true,
            renderedRoute: true,
            matchingStatus: "active",
            lastError: nil
        )
        XCTAssertEqual(lines.count, 6)
        XCTAssertTrue(lines[0].contains("定位成功"))
        XCTAssertTrue(lines.contains { $0.contains("route applied") })
        XCTAssertFalse(lines.joined().contains("D7FF3F"))
        XCTAssertTrue(EngineeringDiagnostics.isEnabled)
    }

    func testContentViewDropsFixedRouteCopy() throws {
        let content = try String(
            contentsOf: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/App/ContentView.swift")
        )
        XCTAssertTrue(content.contains("ScanLoadingHUD("))
        XCTAssertTrue(content.contains("EngineeringDiagnosticsPanel("))
        XCTAssertTrue(content.contains("CragDirectoryOverlay("))
        XCTAssertFalse(content.contains("Stage5DebugHUD("))
        XCTAssertTrue(content.contains("suppressOverlayText: DebugHUDMode.active.showsStage5HUD"))
        XCTAssertTrue(content.contains("sessionBridge:"))
        XCTAssertTrue(content.contains("KeypointOverlayView("))
        XCTAssertTrue(content.contains("appearance: DebugHUDMode.active.showsStage5HUD ? .scan : .debug"))
        XCTAssertTrue(content.contains("featureOverlayVisible"))
    }

    func testVisualFeaturesHideAfterRouteRenders() {
        let attempt = UUID()
        XCTAssertTrue(
            VisualFeatureOverlay.isVisible(
                receipt: .none,
                attemptId: attempt,
                sceneActive: true
            )
        )
        let shown = RouteApplyReceipt(
            attemptId: attempt,
            wallId: "wall_a",
            renderedRoute: true,
            routeId: "route_1",
            visibleSegmentCount: 8
        )
        XCTAssertFalse(
            VisualFeatureOverlay.isVisible(
                receipt: shown,
                attemptId: attempt,
                sceneActive: true
            )
        )
        XCTAssertTrue(
            VisualFeatureOverlay.isVisible(
                receipt: shown,
                attemptId: UUID(),
                sceneActive: true
            )
        )
        XCTAssertFalse(
            VisualFeatureOverlay.isVisible(
                receipt: .none,
                attemptId: attempt,
                sceneActive: false
            )
        )
        let points = (0..<200).map { CGPoint(x: CGFloat($0), y: 0) }
        let sampled = VisualFeatureOverlay.sampled(points, maxCount: 64)
        XCTAssertEqual(sampled.count, 64)
        XCTAssertEqual(VisualFeatureOverlay.sampled(Array(points.prefix(10)), maxCount: 64).count, 10)
    }

    private func facts(
        localization: String,
        lost: Bool = false,
        matching: String,
        cloud: Bool,
        wallId: String,
        error: String? = nil,
        receipt: RouteApplyReceipt = .none
    ) -> ScanLoadingFacts {
        ScanLoadingFacts(
            localization: localization,
            lostLocalized: lost,
            matchingStatus: matching,
            cloudAssetsLoaded: cloud,
            wallId: wallId,
            lastError: error,
            receipt: receipt,
            sceneActive: true
        )
    }
}
