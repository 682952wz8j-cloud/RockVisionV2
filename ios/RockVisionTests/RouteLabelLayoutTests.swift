import UIKit
import XCTest
@testable import RockVision

final class RouteLabelLayoutTests: XCTestCase {
    func testColumnCopyPutsSuccessOnSecondLine() {
        XCTAssertEqual(ScanLoadingCopy.identifyPending, "识别岩壁…")
        XCTAssertEqual(ScanLoadingCopy.localizePending, "定位攀爬路线…")
        XCTAssertEqual(ScanLoadingCopy.loadPending, "加载攀爬路线…")
        XCTAssertEqual(
            ScanLoadingCopy.columnText(pending: ScanLoadingCopy.identifyPending, title: ScanLoadingCopy.identifyTitle, done: true),
            "识别岩壁\n成功！"
        )
        XCTAssertEqual(
            ScanLoadingCopy.columnText(pending: ScanLoadingCopy.localizePending, title: ScanLoadingCopy.localizeTitle, done: true),
            "定位攀爬路线\n成功！"
        )
        XCTAssertEqual(
            ScanLoadingCopy.columnText(pending: ScanLoadingCopy.loadPending, title: ScanLoadingCopy.loadTitle, done: true),
            "加载攀爬路线\n成功！"
        )
        XCTAssertEqual(
            ScanLoadingCopy.columnText(pending: ScanLoadingCopy.identifyPending, title: ScanLoadingCopy.identifyTitle, done: false),
            "识别岩壁…"
        )
    }

    func testCompactAndQuickdrawKeepHangerMeaning() {
        let route = sampleRoute(name: "爬爬爬", grade: "5.9", draws: "3+2")
        XCTAssertEqual(ProductionRouteFieldCopy.compactLine(route), "爬爬爬 · 5.9")
        XCTAssertEqual(ProductionRouteFieldCopy.quickdrawCaption(route), "快挂 3+2")
        XCTAssertEqual(ProductionRouteFieldCopy.quickdrawLine("3+2"), "🔗 3+2")
        XCTAssertFalse(ProductionRouteFieldCopy.quickdrawCaption(route)!.contains("5"))
        XCTAssertNil(ProductionRouteFieldCopy.quickdrawCaption(sampleRoute(name: "A", grade: "5.9", draws: nil)))
        XCTAssertEqual(ProductionRouteFieldCopy.compactLine(sampleRoute(name: "A", grade: nil, draws: nil)), "A")
    }

    func testStaleOrUnprojectedSnapshotsAreNotLive() {
        let attempt = UUID()
        let live = RouteProjectionSnapshot(
            attemptId: attempt,
            wallId: "wall_a",
            renderedRoute: true,
            samples: [ProjectedRouteSample(routeId: "r1", anchor: CGPoint(x: 40, y: 80), polyline: [CGPoint(x: 40, y: 80)])]
        )
        XCTAssertTrue(live.isLive(attemptId: attempt, wallId: "wall_a"))
        XCTAssertFalse(live.isLive(attemptId: UUID(), wallId: "wall_a"))
        XCTAssertFalse(live.isLive(attemptId: attempt, wallId: "wall_b"))
        XCTAssertFalse(live.isLive(attemptId: attempt, wallId: "—"))
        var dead = live
        dead.renderedRoute = false
        XCTAssertFalse(dead.isLive(attemptId: attempt, wallId: "wall_a"))
        XCTAssertFalse(RouteProjectionSnapshot.empty.isLive(attemptId: attempt, wallId: "wall_a"))
    }

    func testSingleRouteKeepsSelectedAndPlacesNearStart() throws {
        let sample = ProjectedRouteSample(
            routeId: "r1",
            anchor: CGPoint(x: 180, y: 500),
            polyline: [CGPoint(x: 180, y: 500), CGPoint(x: 190, y: 420)]
        )
        let result = RouteLabelLayout.layout(
            samples: [sample],
            texts: ["r1": ("爬爬爬 · 5.9", true)],
            context: context(selected: "r1"),
            memory: .empty
        )
        XCTAssertEqual(result.placements.count, 1)
        let placed = try XCTUnwrap(result.placements.first)
        XCTAssertEqual(placed.routeId, "r1")
        XCTAssertLessThan(abs(placed.leaderEnd.x - 180), 1)
        XCTAssertLessThan(hypot(placed.frame.minX - 180, placed.frame.midY - 500), 90)
    }

    func testThreeAndTenRoutesCapAtThreeAndKeepSelection() {
        let samples = makeSamples(count: 10)
        var texts: [String: (compact: String, expanded: Bool)] = [:]
        for sample in samples {
            texts[sample.routeId] = ("R \(sample.routeId)", sample.routeId == "r9")
        }
        let three = Array(samples.prefix(3))
        let threeResult = RouteLabelLayout.layout(
            samples: three,
            texts: texts,
            context: context(selected: "r1"),
            memory: .empty
        )
        XCTAssertLessThanOrEqual(threeResult.placements.count, 3)
        XCTAssertTrue(threeResult.placements.contains { $0.routeId == "r1" })

        let picked = RouteLabelLayout.pickVisible(
            samples: samples,
            selected: "r9",
            canvas: CGSize(width: 390, height: 844),
            previous: []
        )
        XCTAssertTrue(picked.contains("r9"))
        XCTAssertLessThanOrEqual(picked.count, 3)
        let crowded = RouteLabelLayout.layout(
            samples: samples,
            texts: texts,
            context: context(selected: "r9"),
            memory: .empty
        )
        XCTAssertLessThanOrEqual(crowded.placements.count, 3)
    }

    func testLayoutKeepsPreviousIdsWhenStillValid() {
        let samples = makeSamples(count: 8)
        var texts: [String: (compact: String, expanded: Bool)] = [:]
        for sample in samples {
            texts[sample.routeId] = ("路线\(sample.routeId)", false)
        }
        let first = RouteLabelLayout.layout(
            samples: samples,
            texts: texts,
            context: context(selected: nil),
            memory: .empty
        )
        XCTAssertFalse(first.memory.visibleIds.isEmpty)
        let shifted = samples.map { sample in
            var copy = sample
            copy.anchor?.x += 2
            copy.polyline = copy.polyline.map { CGPoint(x: $0.x + 2, y: $0.y) }
            return copy
        }
        let second = RouteLabelLayout.layout(
            samples: shifted,
            texts: texts,
            context: context(selected: nil),
            memory: first.memory
        )
        XCTAssertEqual(second.memory.visibleIds, first.memory.visibleIds)
    }

    func testNearestProjectedSegmentWins() {
        let samples = [
            ProjectedRouteSample(routeId: "left", anchor: CGPoint(x: 40, y: 200), polyline: [CGPoint(x: 40, y: 200), CGPoint(x: 40, y: 80)]),
            ProjectedRouteSample(routeId: "right", anchor: CGPoint(x: 220, y: 200), polyline: [CGPoint(x: 220, y: 200), CGPoint(x: 220, y: 80)]),
        ]
        XCTAssertEqual(RouteLabelLayout.nearestRoute(samples: samples, point: CGPoint(x: 44, y: 140)), "left")
        XCTAssertEqual(RouteLabelLayout.nearestRoute(samples: samples, point: CGPoint(x: 218, y: 140)), "right")
        XCTAssertNil(RouteLabelLayout.nearestRoute(samples: samples, point: CGPoint(x: 120, y: 20), slop: 10))
    }

    func testDirectoryShowsJinshidongAndComingSoonAndHidesInternalWalls() {
        let groups = CragDirectoryBuilder.groups(counts: [JinshidongCatalogLocation.wallId: 4])
        XCTAssertEqual(groups.map(\.title), ["已上线：", "coming soon："])
        XCTAssertEqual(groups[0].rows.map(\.name), ["安徽｜宣城｜泾县金狮洞"])
        XCTAssertEqual(
            CragDirectoryBuilder.line(name: groups[0].rows[0].name, count: groups[0].rows[0].routeCount),
            "安徽｜宣城｜泾县金狮洞（4条路线）"
        )
        XCTAssertEqual(
            groups[1].rows.map(\.name),
            ["浙江｜杭州｜临安狮头山", "安徽｜芜湖｜繁昌戴店"]
        )
        let names = groups.flatMap(\.rows).map(\.name).joined(separator: "\n")
        XCTAssertFalse(names.contains("九龙峰"))
        XCTAssertFalse(names.contains("其他"))
        XCTAssertFalse(names.contains("example wall"))
        XCTAssertFalse(names.contains("cragpal publisher e2e test wall"))
        XCTAssertEqual(CragDirectoryBuilder.line(name: CragDirectoryCopy.wuhuDaidian, count: 0), CragDirectoryCopy.wuhuDaidian)
        let fitted = CragDirectoryMetrics.panelWidth(groups: groups, screenWidth: 390)
        let longest = CragDirectoryMetrics.displayedLines(in: groups).map { line in
            (line as NSString).size(withAttributes: [.font: AppPixelFont.uiFont]).width
        }.max() ?? 0
        XCTAssertEqual(fitted, min(ceil(longest) + 20, 390))
        XCTAssertTrue(CragDirectoryMetrics.displayedLines(in: groups).contains(CragDirectoryCopy.version))
        XCTAssertTrue(CragDirectoryMetrics.displayedLines(in: groups).contains("www.cragpal.com"))
        XCTAssertTrue(CragDirectoryMetrics.displayedLines(in: groups).contains("隐私政策与支持"))
        let source = try? String(
            contentsOf: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/ScanLoading/CragDirectory.swift")
        )
        XCTAssertTrue(source?.contains("coming soon：") == true)
        XCTAssertTrue(source?.contains("临安狮头山") == true)
        XCTAssertTrue(source?.contains("繁昌戴店") == true)
        XCTAssertTrue(source?.contains("泾县金狮洞") == true)
        XCTAssertFalse(source?.contains("泾县狮子山") == true)
        XCTAssertFalse(source?.contains("Coming soon") == true)
        XCTAssertFalse(source?.contains("Button(\"关闭\")") == true)
        XCTAssertFalse(source?.contains("其他：") == true)
        XCTAssertFalse(source?.contains("geo.size.width / 3") == true)
        XCTAssertFalse(source?.contains("screenWidth * 2 / 3") == true)
        XCTAssertFalse(source?.contains("productionFieldRoutes") == true)
        XCTAssertTrue(source?.contains("fromWallRoutes") == true)
        XCTAssertTrue(source?.contains("group.title == CragDirectoryCopy.liveTitle") == true)
        XCTAssertTrue(source?.contains("CFBundleShortVersionString") == true)
        XCTAssertTrue(source?.contains("www.cragpal.com") == true)
        XCTAssertTrue(source?.contains("https://www.cragpal.com") == true)
        XCTAssertTrue(source?.contains("Link(destination: CragDirectoryCopy.siteURL)") == true)
        XCTAssertTrue(source?.contains("隐私政策与支持") == true)
        XCTAssertTrue(source?.contains("frame(maxWidth: .infinity, alignment: .center)") == true)
        if let source {
            let siteRange = source.range(of: "Link(destination: CragDirectoryCopy.siteURL)")
            let infoRange = source.range(of: "Button(CragDirectoryCopy.information)")
            XCTAssertNotNil(siteRange)
            XCTAssertNotNil(infoRange)
            if let siteRange, let infoRange {
                XCTAssertLessThan(siteRange.lowerBound, infoRange.lowerBound)
            }
        }
        XCTAssertTrue(source?.contains("Color.black.opacity(0.14)") == true)
        XCTAssertFalse(source?.contains("Color.black.opacity(0.03)") == true)
        XCTAssertTrue(source?.contains("geo.size.height - bottomClearance") == true)
        XCTAssertEqual(CragDirectoryMetrics.bottomHUDClearance(safeBottom: 34), 154)
    }

    func testDirectoryCountIsProductionWallRoutesLength() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("offline/packages/wall_jinshidong_01/r000001/assets/wall-routes")
        guard FileManager.default.isReadableFile(atPath: url.path) else {
            throw XCTSkip("production jinshidong wall-routes missing")
        }
        let data = try Data(contentsOf: url)
        XCTAssertEqual(
            CragDirectoryBuilder.count(
                fromWallRoutes: data,
                wallId: JinshidongCatalogLocation.wallId,
                releaseId: JinshidongCatalogLocation.releaseId
            ),
            4
        )
        XCTAssertNil(
            CragDirectoryBuilder.count(
                fromWallRoutes: data,
                wallId: JiulongfengCatalogLocation.wallId,
                releaseId: "r000001"
            )
        )
        let jiulongfeng = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("offline/packages/wall_jiulongfeng_01/r000001/assets/wall-routes")
        if FileManager.default.isReadableFile(atPath: jiulongfeng.path) {
            let other = try Data(contentsOf: jiulongfeng)
            XCTAssertNil(
                CragDirectoryBuilder.count(
                    fromWallRoutes: other,
                    wallId: JiulongfengCatalogLocation.wallId,
                    releaseId: JiulongfengCatalogLocation.releaseId
                )
            )
        }
        XCTAssertEqual(
            CragDirectoryBuilder.line(name: CragDirectoryCopy.jinshidongLine, count: 4),
            "安徽｜宣城｜泾县金狮洞（4条路线）"
        )
    }

    func testPixelFontFallbackForMissingHui() throws {
        XCTAssertEqual(AppPixelFont.pointSize, 12)
        XCTAssertEqual(AppPixelFont.postScriptName, "Ark-Pixel-12px-Mono-zh_cn-Regular")
        if AppPixelFont.pixelFaceAvailable {
            XCTAssertTrue(AppPixelFont.glyphExists("岩".unicodeScalars.first!))
            XCTAssertFalse(AppPixelFont.glyphExists("徽".unicodeScalars.first!))
        }
        let cascade = AppPixelFont.uiFont.fontDescriptor.object(forKey: .cascadeList) as? [UIFontDescriptor]
        XCTAssertNotNil(cascade)
        XCTAssertTrue(cascade?.contains { $0.postscriptName.contains("PingFang") || $0.postscriptName.contains("PingFangSC") } == true
            || AppPixelFont.uiFont.fontName.contains("PingFang")
            || !(cascade ?? []).isEmpty)
    }

    func testHudKeepsLabelsAfterChromeHideAndDoesNotUseLoadSuccess() throws {
        let hud = try String(
            contentsOf: URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("RockVision/Features/ScanLoading/ScanLoadingHUD.swift")
        )
        XCTAssertTrue(hud.contains("if !state.hideChrome"))
        XCTAssertTrue(hud.contains("if !state.mascotHidden"))
        XCTAssertTrue(hud.contains("liveSamples"))
        XCTAssertFalse(hud.contains("state.load == .success ?"))
    }

    private func makeSamples(count: Int) -> [ProjectedRouteSample] {
        var samples: [ProjectedRouteSample] = []
        samples.reserveCapacity(count)
        for index in 0..<count {
            let x = CGFloat(40 + index * 28)
            let y = CGFloat(180 + index * 36)
            samples.append(
                ProjectedRouteSample(
                    routeId: "r\(index)",
                    anchor: CGPoint(x: x, y: y),
                    polyline: [CGPoint(x: x, y: y), CGPoint(x: x + 8, y: y - 60)]
                )
            )
        }
        return samples
    }

    private func context(selected: String?) -> RouteLabelLayout.Context {
        RouteLabelLayout.Context(
            canvas: CGSize(width: 390, height: 844),
            safeInsets: CGRect(x: 0, y: 48, width: 390, height: 760),
            obstacles: [CGRect(x: 0, y: 724, width: 390, height: 120)],
            selectedId: selected
        )
    }

    private func sampleRoute(name: String?, grade: String?, draws: String?) -> VerifiedFrozenRoute {
        VerifiedFrozenRoute(
            routeId: "route_1",
            wallId: "wall_a",
            coordinateFrame: "WallMetricMeters",
            provenance: "IDENTITY_SUPPORTED",
            dummyOriginExcluded: true,
            polylineSha256: String(repeating: "a", count: 64),
            wallMetricMeters: [[0, 0, 0], [1, 0, 0]],
            hashVerified: true,
            developmentValidationOnly: false,
            sourceArtifact: "x",
            routeName: name,
            grade: grade,
            displayDraws: draws
        )
    }
}
