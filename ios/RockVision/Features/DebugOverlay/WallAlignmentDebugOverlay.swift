import RealityKit
import UIKit
import simd

/// Places Gate 4B origin + 1 m XYZ axes in ARWorld.
/// Consumes already-transformed ARWorld endpoints only. No Sim3, no camera-basis flip, no scale offset.
enum WallAlignmentDebugOverlay {
    static func apply(to view: ARView, geometry: WallAlignmentDebugGeometry, root: AnchorEntity) {
        if root.parent == nil {
            view.scene.addAnchor(root)
        }
        root.children.removeAll()
        guard geometry.visible,
              geometry.renderedRoute == false,
              let origin = simd3(geometry.originARWorld),
              let xEnd = simd3(geometry.xAxisEndARWorld),
              let yEnd = simd3(geometry.yAxisEndARWorld),
              let zEnd = simd3(geometry.zAxisEndARWorld)
        else {
            return
        }
        root.addChild(sphere(at: origin, radius: 0.03, color: .white))
        root.addChild(axis(from: origin, to: xEnd, color: .red))
        root.addChild(axis(from: origin, to: yEnd, color: .green))
        root.addChild(axis(from: origin, to: zEnd, color: .blue))
    }

    private static func simd3(_ values: [Double]?) -> SIMD3<Float>? {
        guard let values, values.count == 3, values.allSatisfy(\.isFinite) else { return nil }
        return SIMD3(Float(values[0]), Float(values[1]), Float(values[2]))
    }

    private static func sphere(at position: SIMD3<Float>, radius: Float, color: UIColor) -> ModelEntity {
        let mesh = MeshResource.generateSphere(radius: radius)
        var material = UnlitMaterial()
        material.color = .init(tint: color)
        let entity = ModelEntity(mesh: mesh, materials: [material])
        entity.position = position
        return entity
    }

    private static func axis(from: SIMD3<Float>, to: SIMD3<Float>, color: UIColor) -> ModelEntity {
        let delta = to - from
        let length = simd_length(delta)
        let height = max(length, 0.001)
        let mesh = MeshResource.generateBox(size: SIMD3<Float>(0.024, height, 0.024))
        var material = UnlitMaterial()
        material.color = .init(tint: color)
        let entity = ModelEntity(mesh: mesh, materials: [material])
        entity.position = (from + to) * 0.5
        if length > 1e-6 {
            entity.orientation = simd_quatf(from: SIMD3<Float>(0, 1, 0), to: simd_normalize(delta))
        }
        return entity
    }
}
