import RealityKit
import XCTest
@testable import RockVision

final class Gate5DARendererCorrectnessTests: XCTestCase {
    private let tol = 1e-12
    private let floatBound = RouteRenderPlan.floatErrorBoundMeters

    func testEmptyBindingYieldsNonRenderablePlanAndIdleApplyState() {
        let plan = RouteRenderPlan.evaluate(from: .unbound)
        XCTAssertFalse(plan.wouldRender)
        XCTAssertEqual(plan.segmentCount, 0)
        XCTAssertTrue(plan.segments.isEmpty)
        XCTAssertFalse(RuntimeRouteBinding.unbound.hasBoundRoute)
        XCTAssertEqual(RuntimeRouteBinding.unbound.routeARWorldPointCount, 0)
        let beforeApply = RouteRenderState.idle
        XCTAssertFalse(beforeApply.renderedRoute)
        let applied = RouteOverlay.apply(plan: plan, root: AnchorEntity(world: .zero))
        XCTAssertFalse(applied.renderedRoute)
        XCTAssertEqual(applied.visibleSegmentCount, 0)
    }

    func testValidBindingPlansTenOrderedSegments() {
        let binding = bound(points: polylineA())
        let plan = RouteRenderPlan.evaluate(from: binding)
        XCTAssertTrue(plan.wouldRender)
        XCTAssertEqual(plan.pointCount, 11)
        XCTAssertEqual(plan.segmentCount, 10)
        XCTAssertEqual(plan.segments.count, 10)
        XCTAssertEqual(plan.arWorldEndpoints, polylineA())
        for i in 0..<10 {
            XCTAssertEqual(plan.segments[i].index, i)
            assertAlmostEqual(plan.segments[i].startARWorld, polylineA()[i])
            assertAlmostEqual(plan.segments[i].endARWorld, polylineA()[i + 1])
        }
    }

    func testMidpointAndDirectionMatchCurrentBinding() {
        let points = polylineA()
        let plan = RouteRenderPlan.evaluate(from: bound(points: points))
        for i in 0..<10 {
            let start = points[i]
            let end = points[i + 1]
            let expectedMid = [
                (start[0] + end[0]) / 2,
                (start[1] + end[1]) / 2,
                (start[2] + end[2]) / 2
            ]
            let expectedDir = [end[0] - start[0], end[1] - start[1], end[2] - start[2]]
            assertAlmostEqual(plan.segments[i].midpointARWorld, expectedMid)
            assertAlmostEqual(plan.segments[i].directionARWorld, expectedDir)
        }
    }

    func testThicknessDoesNotShiftLongitudinalEndpoints() {
        let points = polylineA()
        let plan = RouteRenderPlan.evaluate(from: bound(points: points))
        XCTAssertEqual(plan.segments.first?.thicknessMeters, RouteRenderPlan.visualThicknessMeters)
        for i in 0..<10 {
            let segment = plan.segments[i]
            assertAlmostEqual(segment.reconstructedStart, points[i])
            assertAlmostEqual(segment.reconstructedEnd, points[i + 1])
            XCTAssertEqual(segment.thicknessMeters, RouteRenderPlan.visualThicknessMeters)
        }
    }

    func testFloatConversionErrorMeetsBound() {
        let plan = RouteRenderPlan.evaluate(from: bound(points: polylineA()))
        XCTAssertLessThanOrEqual(plan.maxFloatConversionErrorMeters, floatBound)
        for segment in plan.segments {
            XCTAssertLessThanOrEqual(segment.floatConversionErrorMeters, floatBound)
            XCTAssertEqual(segment.startFloat.count, 3)
            XCTAssertEqual(segment.endFloat.count, 3)
        }
    }

    func testNoNormalizationRecenteringScaleFlipOrOffset() throws {
        let points = polylineA()
        let plan = RouteRenderPlan.evaluate(from: bound(points: points))
        XCTAssertEqual(plan.arWorldEndpoints, points)
        let centroid = [
            points.map { $0[0] }.reduce(0, +) / 11,
            points.map { $0[1] }.reduce(0, +) / 11,
            points.map { $0[2] }.reduce(0, +) / 11
        ]
        XCTAssertNotEqual(plan.arWorldEndpoints[0], [0, 0, 0])
        XCTAssertNotEqual(plan.arWorldEndpoints[0], centroid)
        for i in 0..<11 {
            XCTAssertEqual(plan.arWorldEndpoints[i][0], points[i][0])
            XCTAssertEqual(plan.arWorldEndpoints[i][1], points[i][1])
            XCTAssertEqual(plan.arWorldEndpoints[i][2], points[i][2])
        }
        let source = try readHostSource("RockVision/Features/PnP/RouteRenderPlan.swift")
        XCTAssertFalse(source.contains("3.19764417024824"))
        XCTAssertFalse(source.contains("routeOffset"))
        XCTAssertFalse(source.contains("routeScale"))
        XCTAssertFalse(source.contains("axisFlip"))
        XCTAssertFalse(source.contains("correctionMatrix"))
        XCTAssertFalse(source.contains("normalize("))
        let overlay = try readHostSource("RockVision/Features/RouteOverlay/RouteOverlay.swift")
        XCTAssertFalse(overlay.contains("3.19764417024824"))
        XCTAssertFalse(overlay.contains("routeOffset"))
        XCTAssertFalse(overlay.contains("applyFrozenWallRoutePointToARWorld"))
        XCTAssertFalse(overlay.contains("productionAlignment"))
    }

    func testBoundBeforeApplyIsNotYetRendered() {
        let plan = RouteRenderPlan.evaluate(from: bound(points: polylineA()))
        XCTAssertTrue(plan.wouldRender)
        XCTAssertFalse(RouteRenderState.idle.renderedRoute)
        XCTAssertEqual(bound(points: polylineA()).renderedRoute, false)
    }

    func testApplyValidPlanSetsAuthoritativeRenderedState() {
        let binding = bound(points: polylineA())
        let plan = RouteRenderPlan.evaluate(from: binding)
        let root = AnchorEntity(world: .zero)
        let state = RouteOverlay.apply(plan: plan, root: root)
        XCTAssertTrue(state.renderedRoute)
        XCTAssertEqual(state.visibleSegmentCount, 10)
        XCTAssertEqual(state.renderedARWorldEndpoints, polylineA())
        XCTAssertEqual(root.children.count, 10)
        XCTAssertEqual(binding.renderedRoute, false)
        XCTAssertEqual(binding.hasBoundRoute, true)
    }

    func testRollingUpdateReplacesPreviousGeometry() {
        let plan1 = RouteRenderPlan.evaluate(from: bound(points: polylineA()))
        let plan2 = RouteRenderPlan.evaluate(from: bound(points: polylineB()))
        let root = AnchorEntity(world: .zero)
        let c1 = RouteOverlay.apply(plan: plan1, root: root)
        XCTAssertEqual(c1.renderedARWorldEndpoints, polylineA())
        let c2 = RouteOverlay.apply(plan: plan2, root: root)
        XCTAssertEqual(c2.renderedARWorldEndpoints, polylineB())
        XCTAssertNotEqual(c2.renderedARWorldEndpoints, polylineA())
        XCTAssertEqual(root.children.count, 10)
        for i in 0..<11 {
            XCTAssertNotEqual(polylineA()[i], polylineB()[i])
        }
    }

    func testAlignmentLossClearsRoute() {
        let root = AnchorEntity(world: .zero)
        _ = RouteOverlay.apply(plan: RouteRenderPlan.evaluate(from: bound(points: polylineA())), root: root)
        XCTAssertEqual(root.children.count, 10)
        let empty = RouteOverlay.apply(plan: RouteRenderPlan.evaluate(from: .unbound), root: root)
        XCTAssertFalse(empty.renderedRoute)
        XCTAssertEqual(empty.visibleSegmentCount, 0)
        XCTAssertEqual(root.children.count, 0)
    }

    func testRelocalizationUsesOnlyNewBinding() {
        let root = AnchorEntity(world: .zero)
        let c1 = RouteOverlay.apply(plan: RouteRenderPlan.evaluate(from: bound(points: polylineA())), root: root)
        XCTAssertEqual(c1.renderedARWorldEndpoints, polylineA())
        _ = RouteOverlay.apply(plan: RouteRenderPlan.evaluate(from: .unbound), root: root)
        let c2 = RouteOverlay.apply(plan: RouteRenderPlan.evaluate(from: bound(points: polylineB())), root: root)
        XCTAssertEqual(c2.renderedARWorldEndpoints, polylineB())
        XCTAssertNotEqual(c2.renderedARWorldEndpoints, polylineA())
        XCTAssertTrue(c2.renderedRoute)
        XCTAssertEqual(c2.visibleSegmentCount, 10)
    }

    func testBindingRenderedRouteRemainsNonAuthoritative() {
        var binding = bound(points: polylineA())
        let original = binding
        let plan = RouteRenderPlan.evaluate(from: binding)
        _ = RouteOverlay.apply(plan: plan, root: AnchorEntity(world: .zero))
        XCTAssertEqual(binding, original)
        XCTAssertEqual(binding.renderedRoute, false)
        XCTAssertTrue(plan.wouldRender)
        let applied = RouteRenderState.afterApplying(plan)
        XCTAssertTrue(applied.renderedRoute)
        XCTAssertNotEqual(binding.renderedRoute, applied.renderedRoute)
    }

    func testAlignmentFrameResultDoesNotOwnRouteRenderState() throws {
        let source = try readHostSource("RockVision/Features/PnP/ProductionAlignment.swift")
        XCTAssertTrue(source.contains("struct AlignmentFrameResult"))
        XCTAssertFalse(source.contains("var routeARWorldPoints"))
        XCTAssertFalse(source.contains("var hasBoundRoute"))
        XCTAssertFalse(source.contains("RouteRenderPlan"))
        XCTAssertFalse(source.contains("RouteRenderState"))
        XCTAssertFalse(source.contains("visibleSegmentCount"))
        let aligned = AlignmentFrameResult.aligned(
            transform: identitySE3(),
            provenance: AlignmentProvenance(
                confirmedFrameID: 1,
                confirmedTimestamp: 1,
                T_opencvCam_colmap: identitySE3(),
                arFrameID: 1,
                arFrameTimestamp: 1,
                T_ARWorld_arkitCam: identitySE3()
            ),
            confirmedEqualsLatestRefined: true
        )
        XCTAssertEqual(aligned.renderedRoute, false)
    }

    func testSourceOwnershipIsolation() throws {
        let overlay = try readHostSource("RockVision/Features/RouteOverlay/RouteOverlay.swift")
        XCTAssertFalse(overlay.contains("WallMetricMeters"))
        XCTAssertFalse(overlay.contains("Gate5CRouteFixture"))
        XCTAssertFalse(overlay.contains("gate5a_ingested"))
        XCTAssertFalse(overlay.contains(".dxf"))
        XCTAssertFalse(overlay.contains("applyFrozenWallRoutePointToARWorld"))
        XCTAssertFalse(overlay.contains("productionAlignment"))
        XCTAssertFalse(overlay.contains("S_wall_colmap"))
        XCTAssertFalse(overlay.contains("CLLocation"))
        XCTAssertFalse(overlay.contains("CLHeading"))

        let plan = try readHostSource("RockVision/Features/PnP/RouteRenderPlan.swift")
        XCTAssertFalse(plan.contains("import RealityKit"))
        XCTAssertFalse(plan.contains("AnchorEntity"))
        XCTAssertFalse(plan.contains("ModelEntity"))
        XCTAssertFalse(plan.contains("applyFrozenWallRoutePointToARWorld"))
        XCTAssertFalse(plan.contains("productionAlignment"))

        let binding = try readHostSource("RockVision/Features/PnP/RuntimeRouteBinding.swift")
        XCTAssertFalse(binding.contains("import RealityKit"))
        XCTAssertFalse(binding.contains("renderedRoute = true"))
        XCTAssertFalse(binding.contains("RouteOverlay"))
        XCTAssertFalse(binding.contains("ModelEntity"))

        let gate4b = try readHostSource("RockVision/Features/DebugOverlay/WallAlignmentDebugOverlay.swift")
        XCTAssertFalse(gate4b.contains("RuntimeRouteBinding"))
        XCTAssertFalse(gate4b.contains("RouteRenderPlan"))
        XCTAssertFalse(gate4b.contains("RouteOverlay"))
        XCTAssertFalse(gate4b.contains("route_test_01"))

        let processor = try readHostSource("RockVision/Features/OpenCV/OpenCVFrameProcessor.swift")
        XCTAssertFalse(processor.contains("import RealityKit"))
        XCTAssertFalse(processor.contains("RouteOverlay"))
        XCTAssertFalse(processor.contains("AnchorEntity"))
        XCTAssertFalse(processor.contains("ModelEntity"))
        XCTAssertTrue(processor.contains("RouteRenderPlan.evaluate"))
        XCTAssertTrue(processor.contains("fieldSink?.ingest"))

        let preview = try readHostSource("RockVision/Features/ARSessionHost/ARCameraPreview.swift")
        XCTAssertTrue(preview.contains("let routeRoot = AnchorEntity(world: .zero)"))
        XCTAssertTrue(preview.contains("RouteOverlay.apply(plan: plan, root: routeRoot)"))
        XCTAssertTrue(preview.contains("WallAlignmentDebugOverlay.apply"))
        XCTAssertNotEqual(
            preview.range(of: "let root = AnchorEntity(world: .zero)"),
            preview.range(of: "let routeRoot = AnchorEntity(world: .zero)")
        )
    }

    func testFieldTestExportUsesPlanNotAlignmentRenderedRoute() throws {
        let binding = bound(points: polylineA())
        let plan = RouteRenderPlan.evaluate(from: binding)
        XCTAssertTrue(plan.wouldRender)
        let snapshot = FieldTestRouteRenderingSnapshot(
            renderedRoute: plan.wouldRender,
            visibleSegmentCount: plan.segmentCount
        )
        XCTAssertTrue(snapshot.renderedRoute)
        XCTAssertEqual(snapshot.visibleSegmentCount, 10)
        XCTAssertNotEqual(snapshot.renderedRoute, binding.renderedRoute)
        XCTAssertEqual(AlignmentFrameResult.none.renderedRoute, false)
        XCTAssertNotEqual(snapshot.renderedRoute, AlignmentFrameResult.none.renderedRoute)

        let export = try readHostSource("RockVision/Features/FieldTest/FieldTestExport.swift")
        XCTAssertTrue(export.contains("routeRendering.renderedRoute"))
        XCTAssertTrue(export.contains("routeBinding.hasBoundRoute"))
        XCTAssertTrue(export.contains("frozenRouteHashVerified"))
        XCTAssertEqual(FieldTestExportSchema.version, "gate5da.runtime.1")

        let sample = FieldTestSample(
            recordedAt: Date(),
            frameID: 1,
            timestamp: 1,
            scene: "A",
            processingWidth: 960,
            processingHeight: 720,
            presetLabel: "960×720",
            keypointCount: 1,
            occupiedCells: 1,
            occupancyRatio: 1,
            preprocessLatencyMs: 0,
            siftLatencyMs: 0,
            totalLatencyMs: 0,
            tracking: "normal",
            valid: true,
            invalidReason: nil,
            descriptorRows: 1,
            descriptorDimension: 128,
            descriptorsFinite: true,
            rowsMatchKeypoints: true,
            skippedFrames: 0,
            achievedRateHz: 2,
            routeBinding: FieldTestRouteBindingSnapshot(
                routeId: "route_test_01",
                frozenRouteHashVerified: true,
                routeARWorldPointCount: 11,
                hasBoundRoute: true
            ),
            routeRendering: snapshot
        )
        XCTAssertEqual(sample.routeBinding?.routeId, "route_test_01")
        XCTAssertEqual(sample.routeBinding?.routeARWorldPointCount, 11)
        XCTAssertEqual(sample.routeRendering?.renderedRoute, true)
        XCTAssertNil(sample.alignmentStats)
    }

    func testHUDExposesRouteHashBoundRendered() {
        let rows = Gate4BPhysicalValidationHUD.visibleRows(
            scene: "A",
            tracking: "normal",
            localization: "localized",
            confirmationWindow: "3/3",
            alignment: "yes 1",
            wallAxes: "visible",
            wallMarkers: "4/4",
            routeId: "route_test_01",
            hashVerified: true,
            boundPointCount: 11,
            rendered: true,
            visibleSegmentCount: 10
        )
        XCTAssertTrue(rows.contains { $0.title == "Route" && $0.value == "route_test_01" })
        XCTAssertTrue(rows.contains { $0.title == "Hash" && $0.value == "OK" })
        XCTAssertTrue(rows.contains { $0.title == "Bound" && $0.value == "11" })
        XCTAssertTrue(rows.contains { $0.title == "Rendered" && $0.value == "YES" })
        XCTAssertFalse(Gate4BPhysicalValidationHUD.visibleTitles.contains("Offset"))
        XCTAssertFalse(Gate4BPhysicalValidationHUD.visibleTitles.contains("Scale"))
    }

    func testEvaluateDoesNotMutateBinding() {
        let original = bound(points: polylineA())
        var binding = original
        _ = RouteRenderPlan.evaluate(from: binding)
        XCTAssertEqual(binding, original)
        XCTAssertEqual(binding.routeARWorldPoints, polylineA())
        XCTAssertEqual(binding.renderedRoute, false)
    }

    // MARK: - Helpers

    private func bound(points: [[Double]]) -> RuntimeRouteBinding {
        RuntimeRouteBinding(
            routeId: "route_test_01",
            hashVerified: true,
            hasBoundRoute: true,
            routeARWorldPointCount: points.count,
            routeARWorldPoints: points,
            renderedRoute: false,
            reason: nil
        )
    }

    private func polylineA() -> [[Double]] {
        (0..<11).map { i in [Double(i), Double(i) * 0.1, 2.5] }
    }

    private func polylineB() -> [[Double]] {
        (0..<11).map { i in [Double(i) + 10, 4.0, Double(i) * -0.2] }
    }

    private func identitySE3() -> [[Double]] {
        [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ]
    }

    private func assertAlmostEqual(_ a: [Double], _ b: [Double], file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(a.count, b.count, file: file, line: line)
        for i in 0..<a.count {
            XCTAssertEqual(a[i], b[i], accuracy: tol, file: file, line: line)
        }
    }

    private func readHostSource(_ relative: String) throws -> String {
        let path = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(relative)
            .path
        guard FileManager.default.isReadableFile(atPath: path) else {
            throw XCTSkip("host source tree not readable")
        }
        return try String(contentsOfFile: path, encoding: .utf8)
    }
}
