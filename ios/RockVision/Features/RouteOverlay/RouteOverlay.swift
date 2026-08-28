import RealityKit
import UIKit
import simd

/// Independent Gate 5D RealityKit overlay. Consumes RouteRenderPlan only.
/// Does not read frozen wall-metric geometry, validation fixtures, or CAD files,
/// and does not reconstruct Wall→ARWorld placement.
enum RouteOverlay {
    /// Applies current PLAN to an independent Gate 5D root. Clears the root when
    /// the plan is not renderable. Does not mutate RuntimeRouteBinding.
    @discardableResult
    static func apply(plan: RouteRenderPlan, root: AnchorEntity) -> RouteRenderState {
        root.children.removeAll()
        let state = RouteRenderState.afterApplying(plan)
        guard state.renderedRoute else { return state }
        for segment in plan.segments {
            root.addChild(segmentEntity(segment))
        }
        return state
    }

    private static func segmentEntity(_ segment: RouteRenderSegment) -> ModelEntity {
        let start = simd3(segment.startFloat)
        let end = simd3(segment.endFloat)
        let delta = end - start
        let length = simd_length(delta)
        let height = Float(segment.lengthMeters)
        let thickness = Float(segment.thicknessMeters)
        let mesh = MeshResource.generateBox(size: SIMD3<Float>(thickness, max(height, 0), thickness))
        var material = UnlitMaterial()
        material.color = .init(tint: UIColor(red: 1.0, green: 0.84, blue: 0.0, alpha: 1))
        let entity = ModelEntity(mesh: mesh, materials: [material])
        entity.position = (start + end) * 0.5
        if length > 1e-6 {
            entity.orientation = simd_quatf(from: SIMD3<Float>(0, 1, 0), to: simd_normalize(delta))
        }
        return entity
    }

    private static func simd3(_ values: [Float]) -> SIMD3<Float> {
        SIMD3(values[0], values[1], values[2])
    }
}
