import RealityKit
import UIKit
import simd

/// Places Gate 4B origin + 1 m XYZ axes in ARWorld.
/// Consumes already-transformed ARWorld endpoints only. No Sim3, no camera-basis flip, no scale offset.
enum WallAlignmentDebugOverlay {
    static let markerDotRadius: Float = 0.012
    static let markerArmLength: Float = 0.10
    static let markerLineWidth: Float = 0.006
    static let markerLabelLocalOffset = SIMD3<Float>(0, 0.055, 0)

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
        for marker in geometry.markers ?? [] {
            guard let center = simd3(marker.predictedARWorldXYZMeters) else { continue }
            root.addChild(measurementMarker(id: marker.landmarkID, center: center))
        }
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

    /// Places a measurement marker whose entity origin is the predicted ARWorld center.
    /// Label offset is local only. Does not rotate toward camera. Does not move the center.
    private static func measurementMarker(id: String, center: SIMD3<Float>) -> Entity {
        let color = markerColor(id)
        let group = Entity()
        group.position = center
        group.addChild(sphere(at: .zero, radius: markerDotRadius, color: color))
        let half = markerArmLength * 0.5
        group.addChild(crosshairArm(axis: SIMD3<Float>(1, 0, 0), halfLength: half, color: color))
        group.addChild(crosshairArm(axis: SIMD3<Float>(0, 1, 0), halfLength: half, color: color))
        group.addChild(crosshairArm(axis: SIMD3<Float>(0, 0, 1), halfLength: half, color: color))
        group.addChild(markerLabel(id, color: color))
        return group
    }

    private static func crosshairArm(axis: SIMD3<Float>, halfLength: Float, color: UIColor) -> ModelEntity {
        let length = max(halfLength * 2, 0.001)
        let size = SIMD3<Float>(
            abs(axis.x) > 0.5 ? length : markerLineWidth,
            abs(axis.y) > 0.5 ? length : markerLineWidth,
            abs(axis.z) > 0.5 ? length : markerLineWidth
        )
        let mesh = MeshResource.generateBox(size: size)
        var material = UnlitMaterial()
        material.color = .init(tint: color)
        let entity = ModelEntity(mesh: mesh, materials: [material])
        entity.position = .zero
        return entity
    }

    private static func markerLabel(_ id: String, color: UIColor) -> ModelEntity {
        let mesh = MeshResource.generateText(
            id,
            extrusionDepth: 0.001,
            font: .systemFont(ofSize: 0.04),
            containerFrame: CGRect(x: -0.08, y: 0, width: 0.16, height: 0.05),
            alignment: .center,
            lineBreakMode: .byClipping
        )
        var material = UnlitMaterial()
        material.color = .init(tint: color)
        let entity = ModelEntity(mesh: mesh, materials: [material])
        entity.position = markerLabelLocalOffset
        return entity
    }

    private static func markerColor(_ id: String) -> UIColor {
        switch id {
        case "W01": return UIColor(red: 0.12, green: 0.47, blue: 0.71, alpha: 1)
        case "W02": return UIColor(red: 1.0, green: 0.50, blue: 0.05, alpha: 1)
        case "W03": return UIColor(red: 0.17, green: 0.63, blue: 0.17, alpha: 1)
        case "W04": return UIColor(red: 0.84, green: 0.15, blue: 0.16, alpha: 1)
        default: return .white
        }
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
