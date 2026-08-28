import Foundation

/// Pure Gate 5D-A renderer plan. Consumes current RuntimeRouteBinding B only.
/// No RealityKit ownership, no wall-metric conversion, no spatial transform.
struct RouteRenderSegment: Equatable, Sendable {
    var index: Int
    var startARWorld: [Double]
    var endARWorld: [Double]
    var midpointARWorld: [Double]
    var directionARWorld: [Double]
    var lengthMeters: Double
    var thicknessMeters: Double
    var startFloat: [Float]
    var endFloat: [Float]
    var floatConversionErrorMeters: Double

    /// Longitudinal endpoints implied by center + length along direction.
    /// Thickness is orthogonal and must not appear here.
    var reconstructedStart: [Double] {
        scaled(midpointARWorld, plus: directionARWorld, scale: -0.5)
    }

    var reconstructedEnd: [Double] {
        scaled(midpointARWorld, plus: directionARWorld, scale: 0.5)
    }

    private func scaled(_ origin: [Double], plus delta: [Double], scale: Double) -> [Double] {
        [
            origin[0] + delta[0] * scale,
            origin[1] + delta[1] * scale,
            origin[2] + delta[2] * scale
        ]
    }
}

/// PLAN — current-frame renderable geometry derived from B. Not apply/C.
struct RouteRenderPlan: Equatable, Sendable {
    static let expectedPointCount = 11
    static let expectedSegmentCount = 10
    static let visualThicknessMeters = 0.020
    static let floatErrorBoundMeters = 1e-5

    var routeId: String?
    var wouldRender: Bool
    var pointCount: Int
    var segmentCount: Int
    var arWorldEndpoints: [[Double]]
    var segments: [RouteRenderSegment]
    var maxFloatConversionErrorMeters: Double

    static let empty = RouteRenderPlan(
        routeId: nil,
        wouldRender: false,
        pointCount: 0,
        segmentCount: 0,
        arWorldEndpoints: [],
        segments: [],
        maxFloatConversionErrorMeters: 0
    )

    /// Copies current ARWorld endpoints from B. Does not mutate B.
    /// Does not convert wall-metric geometry or reconstruct the frozen production transform.
    static func evaluate(from binding: RuntimeRouteBinding) -> RouteRenderPlan {
        guard binding.hasBoundRoute,
              binding.routeARWorldPointCount == expectedPointCount,
              binding.routeARWorldPoints.count == expectedPointCount,
              binding.routeARWorldPoints.allSatisfy({ $0.count == 3 && $0.allSatisfy(\.isFinite) })
        else {
            return RouteRenderPlan(
                routeId: binding.routeId,
                wouldRender: false,
                pointCount: 0,
                segmentCount: 0,
                arWorldEndpoints: [],
                segments: [],
                maxFloatConversionErrorMeters: 0
            )
        }
        let points = binding.routeARWorldPoints.map { [$0[0], $0[1], $0[2]] }
        var segments: [RouteRenderSegment] = []
        segments.reserveCapacity(expectedSegmentCount)
        var maxError = 0.0
        for index in 0..<expectedSegmentCount {
            let start = points[index]
            let end = points[index + 1]
            let direction = [end[0] - start[0], end[1] - start[1], end[2] - start[2]]
            let midpoint = [
                (start[0] + end[0]) / 2.0,
                (start[1] + end[1]) / 2.0,
                (start[2] + end[2]) / 2.0
            ]
            let length = hypot3(direction)
            let startConv = floatConversion(start)
            let endConv = floatConversion(end)
            let error = max(startConv.error, endConv.error)
            maxError = max(maxError, error)
            segments.append(
                RouteRenderSegment(
                    index: index,
                    startARWorld: start,
                    endARWorld: end,
                    midpointARWorld: midpoint,
                    directionARWorld: direction,
                    lengthMeters: length,
                    thicknessMeters: visualThicknessMeters,
                    startFloat: startConv.floats,
                    endFloat: endConv.floats,
                    floatConversionErrorMeters: error
                )
            )
        }
        return RouteRenderPlan(
            routeId: binding.routeId,
            wouldRender: true,
            pointCount: expectedPointCount,
            segmentCount: expectedSegmentCount,
            arWorldEndpoints: points,
            segments: segments,
            maxFloatConversionErrorMeters: maxError
        )
    }

    private static func hypot3(_ v: [Double]) -> Double {
        sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    }

    private static func floatConversion(_ xyz: [Double]) -> (floats: [Float], error: Double) {
        let floats = [Float(xyz[0]), Float(xyz[1]), Float(xyz[2])]
        let dx = xyz[0] - Double(floats[0])
        let dy = xyz[1] - Double(floats[1])
        let dz = xyz[2] - Double(floats[2])
        return (floats, sqrt(dx * dx + dy * dy + dz * dz))
    }
}

/// C — overlay apply result. Authoritative renderedRoute lives here, not on B.
/// Not stored in AlignmentFrameResult or WallAlignmentDebugGeometry.
struct RouteRenderState: Equatable, Sendable {
    var renderedRoute: Bool
    var visibleSegmentCount: Int
    var routeId: String?
    var renderedARWorldEndpoints: [[Double]]

    static let idle = RouteRenderState(
        renderedRoute: false,
        visibleSegmentCount: 0,
        routeId: nil,
        renderedARWorldEndpoints: []
    )

    /// Deterministic state after overlay apply of `plan`.
    /// This is production render intent, not a RealityKit scene-graph reverse read,
    /// and not AlignmentFrameResult.renderedRoute.
    static func afterApplying(_ plan: RouteRenderPlan) -> RouteRenderState {
        guard plan.wouldRender, plan.segmentCount == RouteRenderPlan.expectedSegmentCount else {
            return RouteRenderState(
                renderedRoute: false,
                visibleSegmentCount: 0,
                routeId: plan.routeId,
                renderedARWorldEndpoints: []
            )
        }
        return RouteRenderState(
            renderedRoute: true,
            visibleSegmentCount: plan.segmentCount,
            routeId: plan.routeId,
            renderedARWorldEndpoints: plan.arWorldEndpoints
        )
    }
}
