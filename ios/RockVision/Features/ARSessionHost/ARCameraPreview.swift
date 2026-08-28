import ARKit
import RealityKit
import SwiftUI

/// Minimal camera preview. Uses the session owned by `ARSessionHost`.
/// Does not run its own configuration or localization.
/// Gate 4B debug axes consume already-transformed ARWorld endpoints only.
/// Gate 5D route overlay consumes current RouteRenderPlan only, on a separate root.
struct ARCameraPreview: UIViewRepresentable {
    let session: ARSession
    var debugGeometry: WallAlignmentDebugGeometry = .hidden
    var routePlan: RouteRenderPlan = .empty

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeUIView(context: Context) -> ARView {
        let view = ARView(frame: .zero)
        view.automaticallyConfigureSession = false
        view.session = session
        view.environment.background = .cameraFeed()
        view.renderOptions.insert(.disableMotionBlur)
        view.renderOptions.insert(.disableDepthOfField)
        view.renderOptions.insert(.disableGroundingShadows)
        view.renderOptions.insert(.disableCameraGrain)
        context.coordinator.attach(to: view)
        context.coordinator.apply(debugGeometry)
        context.coordinator.apply(routePlan)
        return view
    }

    func updateUIView(_ uiView: ARView, context: Context) {
        if uiView.session !== session {
            uiView.session = session
        }
        context.coordinator.apply(debugGeometry)
        context.coordinator.apply(routePlan)
    }

    static func dismantleUIView(_ uiView: ARView, coordinator: Coordinator) {
        coordinator.detach()
        uiView.session.pause()
    }

    final class Coordinator {
        let root = AnchorEntity(world: .zero)
        let routeRoot = AnchorEntity(world: .zero)
        private weak var view: ARView?

        func attach(to view: ARView) {
            self.view = view
            if root.parent == nil {
                view.scene.addAnchor(root)
            }
            if routeRoot.parent == nil {
                view.scene.addAnchor(routeRoot)
            }
        }

        func apply(_ geometry: WallAlignmentDebugGeometry) {
            guard let view else { return }
            WallAlignmentDebugOverlay.apply(to: view, geometry: geometry, root: root)
        }

        func apply(_ plan: RouteRenderPlan) {
            RouteOverlay.apply(plan: plan, root: routeRoot)
        }

        func detach() {
            root.removeFromParent()
            routeRoot.removeFromParent()
            view = nil
        }
    }
}
