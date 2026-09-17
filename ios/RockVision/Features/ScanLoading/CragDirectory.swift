import SwiftUI

struct CragDirectoryRow: Equatable, Identifiable, Sendable {
    var wallId: String
    var name: String
    var routeCount: Int?

    var id: String { wallId }
}

struct CragDirectoryGroup: Equatable, Sendable {
    var title: String
    var rows: [CragDirectoryRow]
}

enum CragDirectoryLoadState: Equatable, Sendable {
    case loading
    case failed
    case ready
}

enum CragDirectoryCopy {
    static let liveTitle = "已上线："
    static let comingSoonTitle = "coming soon："
    static let jinshidongLine = "安徽｜宣城｜泾县金狮洞"
    static let linanShitoushan = "浙江｜杭州｜临安狮头山"
    static let wuhuDaidian = "安徽｜芜湖｜繁昌戴店"
    static var version: String { "version \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—")" }
    static let site = "www.cragpal.com"
    static let siteURL = URL(string: "https://www.cragpal.com")!
    static let information = "隐私政策与支持"
}

enum CragDirectoryMetrics {
    static let horizontalPadding: CGFloat = 10
    static let topInset: CGFloat = 54

    static func displayedLines(in groups: [CragDirectoryGroup]) -> [String] {
        var lines = [CragDirectoryCopy.version, CragDirectoryCopy.site, CragDirectoryCopy.information]
        for group in groups {
            lines.append(group.title)
            lines.append(contentsOf: group.rows.map {
                CragDirectoryBuilder.line(name: $0.name, count: $0.routeCount)
            })
        }
        return lines
    }

    static func panelWidth(groups: [CragDirectoryGroup], screenWidth: CGFloat) -> CGFloat {
        let font = AppPixelFont.uiFont
        let longest = displayedLines(in: groups).map { line in
            (line as NSString).size(withAttributes: [.font: font]).width
        }.max() ?? 0
        let fitted = ceil(longest) + horizontalPadding * 2
        return min(max(fitted, 80), max(screenWidth, 80))
    }

    static func bottomHUDClearance(safeBottom: CGFloat) -> CGFloat {
        120 + max(safeBottom, 10)
    }
}

enum CragDirectoryBuilder {
    static func groups(counts: [String: Int] = [:]) -> [CragDirectoryGroup] {
        [
            CragDirectoryGroup(
                title: CragDirectoryCopy.liveTitle,
                rows: [
                    CragDirectoryRow(
                        wallId: JinshidongCatalogLocation.wallId,
                        name: CragDirectoryCopy.jinshidongLine,
                        routeCount: counts[JinshidongCatalogLocation.wallId]
                    ),
                ]
            ),
            CragDirectoryGroup(
                title: CragDirectoryCopy.comingSoonTitle,
                rows: [
                    CragDirectoryRow(
                        wallId: "coming-soon-linan-shitoushan",
                        name: CragDirectoryCopy.linanShitoushan,
                        routeCount: nil
                    ),
                    CragDirectoryRow(
                        wallId: "coming-soon-wuhu-daidian",
                        name: CragDirectoryCopy.wuhuDaidian,
                        routeCount: nil
                    ),
                ]
            ),
        ]
    }

    /// Package `wall-routes` length for a production release. Not on-screen / field-visible routes.
    static func count(fromWallRoutes data: Data, wallId: String, releaseId: String) -> Int? {
        guard wallId == JinshidongCatalogLocation.wallId else { return nil }
        guard let routes = VerifiedFrozenRoute.loadProductionAsset(
            from: data,
            expectedWallId: wallId,
            expectedReleaseId: releaseId
        ) else {
            return nil
        }
        return routes.count
    }

    static func count(from release: LocalValidatedRelease) -> Int? {
        guard release.wallId == JinshidongCatalogLocation.wallId else { return nil }
        guard let asset = try? CloudStage3AssetSemantics.productionRoutesAsset(in: release.manifest) else {
            return nil
        }
        let url = release.fileURL(forAssetId: asset.assetId)
        guard let data = try? Data(contentsOf: url) else { return nil }
        return count(fromWallRoutes: data, wallId: release.wallId, releaseId: release.releaseId)
    }

    static func productionRouteCount(wallId: String, service: CloudAssetService) async -> Int? {
        guard wallId == JinshidongCatalogLocation.wallId else { return nil }
        let catalog = try? await service.fetchCatalog()
        let latestId = catalog?.walls.first(where: {
            $0.wallId == wallId && $0.environment == .production
        })?.latestReleaseId

        if let latestId,
           let local = service.localValidatedReleaseIfPresent(wallId: wallId),
           local.releaseId == latestId,
           let count = count(from: local)
        {
            return count
        }

        do {
            let manifest: WallManifest
            if let latestId {
                manifest = try await service.client.fetchManifest(wallId: wallId, releaseId: latestId)
            } else {
                manifest = try await service.client.fetchManifest(wallId: wallId)
            }
            guard manifest.wallId == wallId else { return nil }
            guard let asset = try CloudStage3AssetSemantics.productionRoutesAsset(in: manifest) else {
                return nil
            }
            let data = try await service.client.downloadAsset(
                wallId: wallId,
                releaseId: manifest.releaseId,
                assetId: asset.assetId
            )
            return count(fromWallRoutes: data, wallId: wallId, releaseId: manifest.releaseId)
        } catch {
            if let local = service.localValidatedReleaseIfPresent(wallId: wallId) {
                return count(from: local)
            }
            return nil
        }
    }

    static func line(name: String, count: Int?) -> String {
        if let count, count > 0 {
            return "\(name)（\(count)条路线）"
        }
        return name
    }
}

@MainActor
final class CragDirectoryModel: ObservableObject {
    @Published var isOpen = false
    @Published var loadState: CragDirectoryLoadState = .ready
    @Published var groups: [CragDirectoryGroup] = CragDirectoryBuilder.groups()

    var serviceOverride: CloudAssetService?

    func toggle() {
        isOpen.toggle()
        if isOpen {
            Task { await refresh() }
        }
    }

    func closeFromOutside() {
        isOpen = false
    }

    func refresh() async {
        var counts: [String: Int] = [:]
        do {
            let service = try serviceOverride ?? CloudAssetService.default()
            if let count = await CragDirectoryBuilder.productionRouteCount(
                wallId: JinshidongCatalogLocation.wallId,
                service: service
            ) {
                counts[JinshidongCatalogLocation.wallId] = count
            }
            loadState = .ready
        } catch {
            loadState = .ready
        }
        groups = CragDirectoryBuilder.groups(counts: counts)
    }
}

struct CragDirectoryOverlay: View {
    @State private var showsInformation = false
    @ObservedObject var model: CragDirectoryModel
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { geo in
            let width = CragDirectoryMetrics.panelWidth(groups: model.groups, screenWidth: geo.size.width)
            let bottomClearance = CragDirectoryMetrics.bottomHUDClearance(safeBottom: geo.safeAreaInsets.bottom)
            ZStack(alignment: .leading) {
                if model.isOpen {
                    Color.clear
                        .ignoresSafeArea()
                        .contentShape(Rectangle())
                        .onTapGesture {
                            model.closeFromOutside()
                        }
                        .accessibilityLabel("收起岩场列表")
                    panel(width: width, height: max(geo.size.height - bottomClearance, 200))
                        .offset(x: 0)
                }
            }
            .animation(reduceMotion ? nil : .easeOut(duration: 0.28), value: model.isOpen)
        }
        .allowsHitTesting(model.isOpen)
        .overlay(alignment: .leading) {
            if !model.isOpen {
                edgeOpenControl
            }
        }
        .onAppear {
            Task { await model.refresh() }
        }
        .onChange(of: model.isOpen) { _, open in
            if open {
                Task { await model.refresh() }
            }
        }
    }

    private var edgeOpenControl: some View {
        Color.clear
            .frame(width: 28)
            .frame(maxHeight: .infinity)
            .contentShape(Rectangle())
            .overlay(alignment: .center) {
                edgeHandle
            }
            .gesture(
                DragGesture(minimumDistance: 16)
                    .onEnded { value in
                        if abs(value.translation.width) > abs(value.translation.height),
                           value.translation.width > 40
                        {
                            model.isOpen = true
                        }
                    }
            )
    }

    private var edgeHandle: some View {
        Button {
            model.toggle()
        } label: {
            Text("›")
                .font(AppPixelFont.font)
                .foregroundStyle(ScanLoadingStyle.success)
                .frame(width: 22, height: 44)
                .background(Color.black.opacity(0.3), in: UnevenRoundedRectangle(
                    topLeadingRadius: 0,
                    bottomLeadingRadius: 0,
                    bottomTrailingRadius: 10,
                    topTrailingRadius: 10,
                    style: .continuous
                ))
        }
        .accessibilityLabel("打开岩场列表")
    }

    private func panel(width: CGFloat, height: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(CragDirectoryCopy.version)
                .font(AppPixelFont.font)
                .foregroundStyle(ScanLoadingStyle.success)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.bottom, 8)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 20) {
                    ForEach(Array(model.groups.enumerated()), id: \.offset) { _, group in
                        if group.title == CragDirectoryCopy.liveTitle
                            || group.title == CragDirectoryCopy.comingSoonTitle
                        {
                            Text(" ")
                                .font(AppPixelFont.font)
                                .foregroundStyle(.clear)
                                .accessibilityHidden(true)
                        }
                        Text(group.title)
                            .font(AppPixelFont.font)
                            .foregroundStyle(ScanLoadingStyle.success)
                            .padding(.bottom, 4)
                        ForEach(group.rows) { row in
                            Text(CragDirectoryBuilder.line(name: row.name, count: row.routeCount))
                                .font(AppPixelFont.font)
                                .foregroundStyle(ScanLoadingStyle.success)
                                .fixedSize(horizontal: false, vertical: true)
                                .padding(.bottom, 6)
                        }
                    }
                }
            }
            Link(destination: CragDirectoryCopy.siteURL) {
                Text(CragDirectoryCopy.site)
                    .font(AppPixelFont.font)
                    .foregroundStyle(ScanLoadingStyle.success)
                    .frame(maxWidth: .infinity, alignment: .center)
            }
            .buttonStyle(.plain)
            .padding(.top, 12)
            Button(CragDirectoryCopy.information) { showsInformation = true }
                .font(AppPixelFont.font)
                .foregroundStyle(ScanLoadingStyle.success)
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(.top, 8)
                .sheet(isPresented: $showsInformation) { AppInformationView() }
        }
        .padding(.top, CragDirectoryMetrics.topInset)
        .padding(.horizontal, CragDirectoryMetrics.horizontalPadding)
        .padding(.bottom, 16)
        .frame(width: width, height: height, alignment: .topLeading)
        .background { panelBackground }
        .clipShape(UnevenRoundedRectangle(
            topLeadingRadius: 0,
            bottomLeadingRadius: 0,
            bottomTrailingRadius: 22,
            topTrailingRadius: 22,
            style: .continuous
        ))
        .overlay(alignment: .trailing) {
            Rectangle()
                .fill(Color.white.opacity(0.14))
                .frame(width: 1)
        }
        .simultaneousGesture(panelCloseDrag())
        .accessibilityElement(children: .contain)
        .accessibilityLabel("支持的岩场列表")
    }

    @ViewBuilder
    private var panelBackground: some View {
        if reduceTransparency {
            Color.black.opacity(0.32)
        } else {
            ZStack {
                Rectangle().fill(.ultraThinMaterial).opacity(0.22)
                Color.black.opacity(0.14)
            }
        }
    }

    private func panelCloseDrag() -> some Gesture {
        DragGesture(minimumDistance: 24)
            .onEnded { value in
                if abs(value.translation.width) > abs(value.translation.height), value.translation.width < -48 {
                    model.closeFromOutside()
                }
            }
    }
}
