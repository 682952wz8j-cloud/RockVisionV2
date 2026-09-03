import SwiftUI
import UIKit

/// Camera + Field Test UI. Localization comes from confirmation, not AR alignment.
struct ContentView: View {
    @StateObject private var sessionHost = ARSessionHost()
    @StateObject private var openCV = OpenCVFrameProcessor()
    @StateObject private var fieldTest = FieldTestController()
    @StateObject private var cloudDebug = CloudDebugController()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .bottomLeading) {
                ARCameraPreview(
                    session: sessionHost.session,
                    debugGeometry: openCV.wallDebugGeometry,
                    routePlan: openCV.routeRenderPlan
                )
                    .ignoresSafeArea()
                KeypointOverlayView(points: openCV.siftSnapshot.overlayViewPoints)
                    .ignoresSafeArea()
                VStack {
                    HStack {
                        Spacer()
                        CloudDebugPanel(
                            controller: cloudDebug,
                            cameraProvenance: openCV.referenceAssetProvenance
                        )
                    }
                    Spacer()
                }
                .ignoresSafeArea(edges: .top)
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
                    sift: openCV.siftSnapshot,
                    matching: openCV.matchingSnapshot,
                    pnp: openCV.pnpSnapshot
                )
            }
            .onAppear {
                sessionHost.frameConsumer = openCV
                openCV.fieldSink = fieldTest
                fieldTest.onApplyScene = { openCV.applyFieldTestScene($0) }
                fieldTest.onApplyPreset = { openCV.applyFieldTestPreset($0) }
                fieldTest.onSetLocked = { openCV.setFieldTestLocked($0) }
                fieldTest.onResetConfirmation = { completion in
                    openCV.resetConfirmation(completion: completion)
                }
                fieldTest.enterFieldTest()
                openCV.updateViewContext(size: geo.size, orientation: currentOrientation())
                sessionHost.start()
            }
            .onChange(of: geo.size) { _, size in
                openCV.updateViewContext(size: size, orientation: currentOrientation())
            }
            .onChange(of: scenePhase) { _, phase in
                if phase != .active {
                    fieldTest.flush()
                    openCV.dumpAllBuckets()
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: UIDevice.orientationDidChangeNotification)) { _ in
                openCV.updateViewContext(size: geo.size, orientation: currentOrientation())
            }
            .onDisappear {
                fieldTest.flush()
                openCV.dumpAllBuckets()
                sessionHost.frameConsumer = nil
                sessionHost.pause()
            }
        }
        .ignoresSafeArea()
    }

    private func currentOrientation() -> UIInterfaceOrientation {
        let scene = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first
        return scene?.interfaceOrientation ?? .portrait
    }
}
