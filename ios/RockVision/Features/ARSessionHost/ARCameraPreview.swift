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
    var suppressOverlayText = false
    var attemptId: UUID = RouteApplyReceipt.none.attemptId
    var wallId: String = "—"
    var sessionBridge: ScanSessionBridge?

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
        context.coordinator.update(from: self)
        context.coordinator.apply(debugGeometry)
        context.coordinator.apply(routePlan)
        return view
    }

    func updateUIView(_ uiView: ARView, context: Context) {
        if uiView.session !== session {
            uiView.session = session
        }
        context.coordinator.update(from: self)
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
        private var bridge: ScanSessionBridge?
        private var attemptId = RouteApplyReceipt.none.attemptId
        private var wallId = "—"
        private var suppressOverlayText = false

        func attach(to view: ARView) {
            self.view = view
            if root.parent == nil {
                view.scene.addAnchor(root)
            }
            if routeRoot.parent == nil {
                view.scene.addAnchor(routeRoot)
            }
        }

        func update(from preview: ARCameraPreview) {
            bridge = preview.sessionBridge
            attemptId = preview.attemptId
            wallId = preview.wallId
            suppressOverlayText = preview.suppressOverlayText
        }

        func apply(_ geometry: WallAlignmentDebugGeometry) {
            guard let view else { return }
            WallAlignmentDebugOverlay.apply(to: view, geometry: geometry, root: root)
        }

        func apply(_ plan: RouteRenderPlan) {
            guard let view else { return }
            let renderPlan = suppressOverlayText ? plan.geometryOnly() : plan
            let state = RouteOverlay.apply(plan: renderPlan, root: routeRoot)
            var samples: [ProjectedRouteSample] = []
            if state.renderedRoute {
                samples = Self.project(plan: plan, in: view)
            }
            let receipt = RouteApplyReceipt(
                attemptId: attemptId,
                wallId: wallId,
                renderedRoute: state.renderedRoute,
                routeId: state.routeId,
                visibleSegmentCount: state.visibleSegmentCount
            )
            let snapshot = RouteProjectionSnapshot(
                attemptId: attemptId,
                wallId: wallId,
                renderedRoute: state.renderedRoute,
                samples: samples
            )
            bridge?.noteCoordinatorApply(receipt: receipt, snapshot: snapshot)
        }

        func detach() {
            root.removeFromParent()
            routeRoot.removeFromParent()
            view = nil
            bridge = nil
        }

        private static func project(plan: RouteRenderPlan, in view: ARView) -> [ProjectedRouteSample] {
            var polylines: [String: [CGPoint]] = [:]
            var order: [String] = []
            func append(routeId: String, point: CGPoint?) {
                guard let point else { return }
                if polylines[routeId] == nil {
                    order.append(routeId)
                    polylines[routeId] = []
                }
                if let last = polylines[routeId]?.last,
                   abs(last.x - point.x) < 0.5,
                   abs(last.y - point.y) < 0.5
                {
                    return
                }
                polylines[routeId]?.append(point)
            }
            for segment in plan.segments {
                guard let routeId = segment.routeId else { continue }
                append(routeId: routeId, point: project(segment.startARWorld, in: view))
                append(routeId: routeId, point: project(segment.endARWorld, in: view))
            }
            var anchors: [String: CGPoint] = [:]
            for item in plan.labels {
                if let point = project(item.anchorARWorld, in: view), view.bounds.contains(point) {
                    anchors[item.routeId] = point
                    if polylines[item.routeId] == nil {
                        order.append(item.routeId)
                        polylines[item.routeId] = [point]
                    }
                }
            }
            return order.compactMap { routeId in
                let line = polylines[routeId] ?? []
                let anchor = anchors[routeId]
                if anchor == nil && line.isEmpty { return nil }
                return ProjectedRouteSample(routeId: routeId, anchor: anchor, polyline: line)
            }
        }

        private static func project(_ xyz: [Double], in view: ARView) -> CGPoint? {
            guard xyz.count == 3 else { return nil }
            let world = SIMD3<Float>(Float(xyz[0]), Float(xyz[1]), Float(xyz[2]))
            return view.project(world)
        }
    }
}
