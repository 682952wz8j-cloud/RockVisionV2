import Foundation

enum WallAlignmentDebugConfig {
    static let kind = "WallAlignmentDebugGeometry"
    static let axisLengthMeters = 1.0
    static let originWall = [0.0, 0.0, 0.0]
    static let xAxisWall = [1.0, 0.0, 0.0]
    static let yAxisWall = [0.0, 1.0, 0.0]
    static let zAxisWall = [0.0, 0.0, 1.0]
}

/// Gate 4B metric Wall test fixture. Isolated from Stage 5 polylines. Not a persistent lock.
struct WallAlignmentDebugGeometry: Codable, Equatable, Sendable {
    var kind: String
    var visible: Bool
    var reason: String?
    var consumedProductionT_ARWorld_Wall: Bool
    var renderedRoute: Bool
    var validatedLandmarkCount: Int
    var sourceFrameID: UInt64?
    var sourceTimestamp: TimeInterval?
    var T_ARWorld_Wall: [[Double]]?
    var originARWorld: [Double]?
    var xAxisEndARWorld: [Double]?
    var yAxisEndARWorld: [Double]?
    var zAxisEndARWorld: [Double]?
    var axisLengthX: Double?
    var axisLengthY: Double?
    var axisLengthZ: Double?
    var dotXY: Double?
    var dotXZ: Double?
    var dotYZ: Double?
    var rotationDeterminant: Double?
    var finite: Bool

    static let hidden = WallAlignmentDebugGeometry(
        kind: WallAlignmentDebugConfig.kind,
        visible: false,
        reason: "noT_ARWorld_Wall",
        consumedProductionT_ARWorld_Wall: false,
        renderedRoute: false,
        validatedLandmarkCount: 0,
        sourceFrameID: nil,
        sourceTimestamp: nil,
        T_ARWorld_Wall: nil,
        originARWorld: nil,
        xAxisEndARWorld: nil,
        yAxisEndARWorld: nil,
        zAxisEndARWorld: nil,
        axisLengthX: nil,
        axisLengthY: nil,
        axisLengthZ: nil,
        dotXY: nil,
        dotXZ: nil,
        dotYZ: nil,
        rotationDeterminant: nil,
        finite: true
    )

    /// Only path: p_ARWorld = T_ARWorld_Wall * p_wall, with T from productionAlignment.
    static func evaluate(alignment: AlignmentFrameResult) -> WallAlignmentDebugGeometry {
        guard alignment.hasT_ARWorld_Wall,
              alignment.productionAlignmentCalled,
              let transform = alignment.T_ARWorld_Wall,
              let provenance = alignment.provenance
        else {
            return hidden
        }
        do {
            let origin = try CoordinateTransforms.apply(transform, point: WallAlignmentDebugConfig.originWall)
            let xEnd = try CoordinateTransforms.apply(transform, point: WallAlignmentDebugConfig.xAxisWall)
            let yEnd = try CoordinateTransforms.apply(transform, point: WallAlignmentDebugConfig.yAxisWall)
            let zEnd = try CoordinateTransforms.apply(transform, point: WallAlignmentDebugConfig.zAxisWall)
            let x = sub(xEnd, origin)
            let y = sub(yEnd, origin)
            let z = sub(zEnd, origin)
            let lenX = norm(x)
            let lenY = norm(y)
            let lenZ = norm(z)
            let det = rotationDeterminant(transform)
            let finite = origin.allSatisfy(\.isFinite)
                && xEnd.allSatisfy(\.isFinite)
                && yEnd.allSatisfy(\.isFinite)
                && zEnd.allSatisfy(\.isFinite)
                && lenX.isFinite && lenY.isFinite && lenZ.isFinite
                && det.isFinite
            guard finite else {
                return refused(reason: "nonFinite", provenance: provenance, transform: transform)
            }
            return WallAlignmentDebugGeometry(
                kind: WallAlignmentDebugConfig.kind,
                visible: true,
                reason: nil,
                consumedProductionT_ARWorld_Wall: true,
                renderedRoute: false,
                validatedLandmarkCount: 0,
                sourceFrameID: provenance.confirmedFrameID,
                sourceTimestamp: provenance.confirmedTimestamp,
                T_ARWorld_Wall: transform,
                originARWorld: origin,
                xAxisEndARWorld: xEnd,
                yAxisEndARWorld: yEnd,
                zAxisEndARWorld: zEnd,
                axisLengthX: lenX,
                axisLengthY: lenY,
                axisLengthZ: lenZ,
                dotXY: dot(x, y),
                dotXZ: dot(x, z),
                dotYZ: dot(y, z),
                rotationDeterminant: det,
                finite: true
            )
        } catch {
            return refused(reason: "nonFinite", provenance: provenance, transform: transform)
        }
    }

    private static func refused(
        reason: String,
        provenance: AlignmentProvenance,
        transform: [[Double]]
    ) -> WallAlignmentDebugGeometry {
        var next = hidden
        next.reason = reason
        next.finite = false
        next.sourceFrameID = provenance.confirmedFrameID
        next.sourceTimestamp = provenance.confirmedTimestamp
        next.T_ARWorld_Wall = transform
        return next
    }

    private static func sub(_ a: [Double], _ b: [Double]) -> [Double] {
        [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
    }

    private static func norm(_ v: [Double]) -> Double {
        sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    }

    private static func dot(_ a: [Double], _ b: [Double]) -> Double {
        a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    }

    private static func rotationDeterminant(_ t: [[Double]]) -> Double {
        let a = t[0][0], b = t[0][1], c = t[0][2]
        let d = t[1][0], e = t[1][1], f = t[1][2]
        let g = t[2][0], h = t[2][1], i = t[2][2]
        return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    }
}

struct WallDebugRuntimeSnapshot: Equatable, Sendable {
    var visible: String = "no"
    var axisLengths: String = "—"
}

enum WallDebugSnapshot {
    static func make(_ geometry: WallAlignmentDebugGeometry) -> WallDebugRuntimeSnapshot {
        guard geometry.visible,
              let x = geometry.axisLengthX,
              let y = geometry.axisLengthY,
              let z = geometry.axisLengthZ
        else {
            return WallDebugRuntimeSnapshot()
        }
        return WallDebugRuntimeSnapshot(
            visible: "yes",
            axisLengths: String(format: "X=%.3f Y=%.3f Z=%.3f m", x, y, z)
        )
    }
}
