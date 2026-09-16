import SwiftUI
import UIKit

/// Camera + Field Test UI. Localization comes from confirmation, not AR alignment.
struct ContentView: View {
    @StateObject private var sessionHost = ARSessionHost()
    @StateObject private var openCV = OpenCVFrameProcessor()
    #if DEBUG
    @StateObject private var fieldTest = FieldTestController()
    @StateObject private var cloudDebug = CloudDebugController()
    #endif
    @StateObject private var productionRuntime = ProductionRuntimeController()
    @StateObject private var scanSession = ScanSessionBridge()
    @StateObject private var cragDirectory = CragDirectoryModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .bottomLeading) {
                ARCameraPreview(
                    session: sessionHost.session,
                    debugGeometry: DebugHUDMode.active.showsStage5HUD ? .hidden : openCV.wallDebugGeometry,
                    routePlan: openCV.routeRenderPlan,
                    suppressOverlayText: DebugHUDMode.active.showsStage5HUD,
                    attemptId: scanSession.attemptId,
                    wallId: productionRuntime.wallId,
                    sessionBridge: DebugHUDMode.active.showsStage5HUD ? scanSession : nil
                )
                    .ignoresSafeArea()
                KeypointOverlayView(
                    points: openCV.siftSnapshot.overlayViewPoints,
                    appearance: DebugHUDMode.active.showsStage5HUD ? .scan : .debug,
                    visible: featureOverlayVisible
                )
                .ignoresSafeArea()
                #if DEBUG
                VStack {
                    HStack {
                        Spacer()
                        if DebugHUDMode.active.showsCloudD5HUD {
                            CloudDebugPanel(
                                controller: cloudDebug,
                                presentation: .d5Discovery
                            )
                            .frame(maxHeight: geo.size.height * 0.78, alignment: .top)
                        } else if DebugHUDMode.active.showsFullCloudDebugHUD {
                            CloudDebugPanel(
                                controller: cloudDebug,
                                presentation: .fullDebug,
                                cameraProvenance: openCV.referenceAssetProvenance,
                                onSelectReferenceSourceBundle: { openCV.selectReferenceSourceBundleDevelopmentFixture() },
                                onSelectReferenceSourceCloudCurrent: { openCV.selectReferenceSourceCloudCurrentJiulongfengDevR000001() },
                                onSelectReferenceSourceJinshidongLocalTest: { openCV.selectReferenceSourceJinshidongLocalTest() }
                            )
                            .frame(maxHeight: geo.size.height * 0.78, alignment: .top)
                        } else if EngineeringDiagnostics.isEnabled {
                            EngineeringDiagnosticsPanel(
                                localization: openCV.confirmationSnapshot.localization,
                                window: openCV.confirmationSnapshot.window,
                                pnp: openCV.pnpSnapshot,
                                wallId: productionRuntime.wallId,
                                cloudAssetsLoaded: productionRuntime.cloudAssetsLoaded,
                                renderedRoute: scanSession.receipt.renderedRoute
                                    && scanSession.receipt.attemptId == scanSession.attemptId,
                                matchingStatus: openCV.matchingSnapshot.status,
                                lastError: productionRuntime.lastError
                            )
                        }
                    }
                    .padding(.top, 10)
                    .padding(.trailing, 10)
                    Spacer()
                }
                .ignoresSafeArea(edges: .top)
                if DebugHUDMode.active.showsGate4BHUD {
                    FieldTestPanel(
                        controller: fieldTest,
                        tracking: sessionHost.snapshot.trackingState,
                        localization: openCV.confirmationSnapshot.localization,
                        confirmationWindow: openCV.confirmationSnapshot.window,
                        alignment: openCV.alignmentSnapshot.status == "yes"
                            ? "yes \(openCV.alignmentSnapshot.frame)"
                            : "none",
                        wallAxes: openCV.wallDebugSnapshot.visible == "yes"
                            ? openCV.wallDebugSnapshot.axisLengths
                            : "hidden",
                        wallMarkers: openCV.wallDebugSnapshot.markers,
                        routeBinding: openCV.runtimeRouteBinding,
                        routePlan: openCV.routeRenderPlan,
                        localTestLegend: openCV.localTestRouteLegend,
                        sift: openCV.siftSnapshot,
                        matching: openCV.matchingSnapshot,
                        pnp: openCV.pnpSnapshot
                    )
                }
                #endif
                if DebugHUDMode.active.showsStage5HUD {
                    ScanLoadingHUD(
                        facts: scanLoadingFacts,
                        routes: openCV.productionFieldRoutes,
                        bridge: scanSession,
                        sidebarOpen: cragDirectory.isOpen,
                        sidebarWidth: CragDirectoryMetrics.panelWidth(
                            groups: cragDirectory.groups,
                            screenWidth: geo.size.width
                        )
                    )
                    .ignoresSafeArea()
                    CragDirectoryOverlay(model: cragDirectory)
                        .ignoresSafeArea()
                }
            }
            .onAppear {
                sessionHost.frameConsumer = openCV
                #if DEBUG
                openCV.fieldSink = fieldTest
                fieldTest.onApplyScene = { openCV.applyFieldTestScene($0) }
                fieldTest.onApplyPreset = { openCV.applyFieldTestPreset($0) }
                fieldTest.onSetLocked = { openCV.setFieldTestLocked($0) }
                fieldTest.onResetConfirmation = { completion in
                    openCV.resetConfirmation(completion: completion)
                }
                fieldTest.enterFieldTest()
                #endif
                productionRuntime.processor = openCV
                openCV.updateViewContext(size: geo.size, orientation: currentOrientation())
                sessionHost.start()
                Task { await productionRuntime.start() }
            }
            .onChange(of: geo.size) { _, size in
                openCV.updateViewContext(size: size, orientation: currentOrientation())
            }
            .onChange(of: scenePhase) { _, phase in
                if phase != .active {
                    #if DEBUG
                    fieldTest.flush()
                    openCV.dumpAllBuckets()
                    #endif
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: UIDevice.orientationDidChangeNotification)) { _ in
                openCV.updateViewContext(size: geo.size, orientation: currentOrientation())
            }
            .onDisappear {
                #if DEBUG
                fieldTest.flush()
                openCV.dumpAllBuckets()
                #endif
                sessionHost.frameConsumer = nil
                sessionHost.pause()
            }
        }
        .ignoresSafeArea()
    }

    private var featureOverlayVisible: Bool {
        if DebugHUDMode.active.showsStage5HUD {
            return VisualFeatureOverlay.isVisible(
                receipt: scanSession.receipt,
                attemptId: scanSession.attemptId,
                sceneActive: scenePhase == .active
            )
        }
        return true
    }

    private var scanLoadingFacts: ScanLoadingFacts {
        ScanLoadingFacts(
            localization: openCV.confirmationSnapshot.localization,
            lostLocalized: openCV.confirmationSnapshot.lostLocalized,
            matchingStatus: openCV.matchingSnapshot.status,
            cloudAssetsLoaded: productionRuntime.cloudAssetsLoaded,
            wallId: productionRuntime.wallId,
            lastError: productionRuntime.lastError,
            receipt: scanSession.receipt,
            sceneActive: scenePhase == .active
        )
    }

    private func currentOrientation() -> UIInterfaceOrientation {
        let scene = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first
        return scene?.interfaceOrientation ?? .portrait
    }
}
