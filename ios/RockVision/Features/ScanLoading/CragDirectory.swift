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

enum CragDirectoryBuilder {
    static func groups(catalog: WallCatalog, counts: [String: Int]) -> [CragDirectoryGroup] {
        let live = catalog.walls.filter { $0.environment == .production }
        let test = catalog.walls.filter { $0.environment == .developmentTest }
        let other = catalog.walls.filter { $0.environment == .unspecified }
        var groups: [CragDirectoryGroup] = []
        if !live.isEmpty {
            groups.append(CragDirectoryGroup(title: "已上线：", rows: live.map { row($0, counts: counts) }))
        }
        if !test.isEmpty {
            groups.append(CragDirectoryGroup(title: "测试：", rows: test.map { row($0, counts: counts) }))
        }
        if !other.isEmpty {
            groups.append(CragDirectoryGroup(title: "其他：", rows: other.map { row($0, counts: counts) }))
        }
        return groups
    }

    static func count(from release: LocalValidatedRelease) -> Int? {
        guard let asset = try? CloudStage3AssetSemantics.productionRoutesAsset(in: release.manifest) else {
            return nil
        }
        let url = release.fileURL(forAssetId: asset.assetId)
        guard let routes = VerifiedFrozenRoute.loadProductionAsset(
            from: url,
            expectedWallId: release.wallId,
            expectedReleaseId: release.releaseId
        ) else {
            return nil
        }
        return routes.count
    }

    static func line(name: String, count: Int?) -> String {
        if let count, count > 0 {
            return "\(name)（\(count)条线路）"
        }
        return name
    }

    private static func row(_ entry: WallCatalogEntry, counts: [String: Int]) -> CragDirectoryRow {
        CragDirectoryRow(wallId: entry.wallId, name: entry.name, routeCount: counts[entry.wallId])
    }
}

@MainActor
final class CragDirectoryModel: ObservableObject {
    @Published var isOpen = false
    @Published var loadState: CragDirectoryLoadState = .loading
    @Published var groups: [CragDirectoryGroup] = []

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
        if groups.isEmpty {
            loadState = .loading
        }
        do {
            let service = try serviceOverride ?? CloudAssetService.default()
            let catalog = try await service.fetchCatalog()
            var counts: [String: Int] = [:]
            for release in service.localCurrentReleases() {
                if let count = CragDirectoryBuilder.count(from: release) {
                    counts[release.wallId] = count
                }
            }
            groups = CragDirectoryBuilder.groups(catalog: catalog, counts: counts)
            loadState = .ready
        } catch {
            if groups.isEmpty {
                loadState = .failed
            }
        }
    }
}

struct CragDirectoryOverlay: View {
    @ObservedObject var model: CragDirectoryModel
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { geo in
            let width = geo.size.width / 3
            ZStack(alignment: .leading) {
                if model.isOpen {
                    Color.black.opacity(0.08)
                        .ignoresSafeArea()
                        .onTapGesture {
                            model.closeFromOutside()
                        }
                        .accessibilityLabel("关闭岩场列表")
                    panel(width: width, height: geo.size.height)
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
            HStack {
                Button("关闭") {
                    model.closeFromOutside()
                }
                .font(AppPixelFont.font)
                .foregroundStyle(ScanLoadingStyle.success)
                .accessibilityLabel("关闭岩场列表")
                Spacer()
            }
            .padding(.bottom, 16)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 20) {
                    switch model.loadState {
                    case .loading:
                        Text("加载中…")
                            .font(AppPixelFont.font)
                            .foregroundStyle(ScanLoadingStyle.success.opacity(0.7))
                    case .failed:
                        Text("目录加载失败")
                            .font(AppPixelFont.font)
                            .foregroundStyle(ScanLoadingStyle.success.opacity(0.7))
                    case .ready:
                        if model.groups.isEmpty {
                            Text("暂无可用岩场")
                                .font(AppPixelFont.font)
                                .foregroundStyle(ScanLoadingStyle.success.opacity(0.7))
                        } else {
                            ForEach(Array(model.groups.enumerated()), id: \.offset) { _, group in
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
                }
            }
        }
        .padding(.top, 54)
        .padding(.horizontal, 10)
        .padding(.bottom, 24)
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
                .fill(Color.white.opacity(0.22))
                .frame(width: 1)
        }
        .simultaneousGesture(panelCloseDrag())
        .accessibilityElement(children: .contain)
        .accessibilityLabel("支持的岩场列表")
    }

    @ViewBuilder
    private var panelBackground: some View {
        if reduceTransparency {
            Color(red: 0.08, green: 0.10, blue: 0.07).opacity(0.94)
        } else {
            ZStack {
                Rectangle().fill(.ultraThinMaterial)
                LinearGradient(
                    colors: [
                        Color(red: 0.18, green: 0.20, blue: 0.15).opacity(0.60),
                        Color(red: 0.06, green: 0.09, blue: 0.06).opacity(0.48),
                    ],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
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
