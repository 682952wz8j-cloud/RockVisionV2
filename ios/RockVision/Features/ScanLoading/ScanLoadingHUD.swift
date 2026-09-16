import Combine
import QuartzCore
import SwiftUI
import UIKit

@MainActor
final class ScanLoadingPlayback: ObservableObject {
    @Published private(set) var state: ScanLoadingState
    private var displayLink: CADisplayLink?
    private let linkTarget = DisplayLinkTarget()
    private var lastTimestamp: CFTimeInterval = 0
    private var runClock: TimeInterval = 0
    private let bridge: ScanSessionBridge
    private var lastFacts: ScanLoadingFacts?

    init(bridge: ScanSessionBridge, now: TimeInterval = Date().timeIntervalSince1970) {
        self.bridge = bridge
        self.state = .fresh(attemptId: bridge.attemptId, wallId: "—", now: now)
        linkTarget.onTick = { [weak self] link in
            self?.step(link)
        }
    }

    var runFrameIndex: Int {
        let frame = Int(runClock * MascotSequence.framesPerSecond)
        return ((frame % MascotSequence.runFrameCount) + MascotSequence.runFrameCount) % MascotSequence.runFrameCount
    }

    var jumpFrameIndex: Int {
        min(Int(state.jumpElapsed * MascotSequence.framesPerSecond), MascotSequence.jumpFrameCount - 1)
    }

    func ingest(_ facts: ScanLoadingFacts) {
        lastFacts = facts
        if !facts.sceneActive {
            stopLink()
            return
        }
        var next = state
        ScanLoadingReducer.ingest(&next, facts: facts) { [weak self] in
            self?.bridge.beginAttempt() ?? UUID()
        }
        if next.attemptId != state.attemptId {
            runClock = 0
        }
        state = next
        startLink()
    }

    func stop() {
        stopLink()
    }

    private func startLink() {
        guard displayLink == nil else { return }
        let link = CADisplayLink(target: linkTarget, selector: #selector(DisplayLinkTarget.tick(_:)))
        link.add(to: .main, forMode: .common)
        displayLink = link
        lastTimestamp = 0
    }

    private func stopLink() {
        displayLink?.invalidate()
        displayLink = nil
        lastTimestamp = 0
    }

    private func step(_ link: CADisplayLink) {
        if lastTimestamp == 0 {
            lastTimestamp = link.timestamp
            return
        }
        let dt = min(link.timestamp - lastTimestamp, 1.0 / 20.0)
        lastTimestamp = link.timestamp
        var next = state
        let matchingActive = lastFacts?.matchingStatus == "active"
        ScanLoadingReducer.tick(&next, dt: dt, matchingActive: matchingActive)
        if next.clip == .run {
            runClock += dt
        }
        state = next
        if next.mascotHidden {
            stopLink()
        }
    }
}

struct ScanLoadingHUD: View {
    var facts: ScanLoadingFacts
    var routes: [VerifiedFrozenRoute]
    var sidebarOpen: Bool = false
    @ObservedObject var bridge: ScanSessionBridge
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var playback: ScanLoadingPlayback
    @State private var labelMemory = RouteLabelLayoutMemory.empty
    @State private var placements: [RouteLabelPlacement] = []

    init(
        facts: ScanLoadingFacts,
        routes: [VerifiedFrozenRoute],
        bridge: ScanSessionBridge,
        sidebarOpen: Bool = false
    ) {
        self.facts = facts
        self.routes = routes
        self.bridge = bridge
        self.sidebarOpen = sidebarOpen
        _playback = StateObject(wrappedValue: ScanLoadingPlayback(bridge: bridge))
    }

    var body: some View {
        GeometryReader { geo in
            let state = playback.state
            ZStack(alignment: .topLeading) {
                RouteInteractionCanvas(
                    samples: liveSamples,
                    selectedId: bridge.selectedRouteId,
                    size: geo.size
                )
                RouteScreenLabelOverlay(
                    routes: routes,
                    placements: placements
                )
                .frame(width: geo.size.width, height: geo.size.height)
                .allowsHitTesting(false)
                VStack {
                    Spacer()
                    if !state.mascotHidden {
                        mascot(in: geo.size)
                            .frame(width: geo.size.width, height: 92, alignment: .leading)
                    }
                    if !state.hideChrome {
                        statusRow
                            .padding(.horizontal, 12)
                        if let hint = ScanLoadingReducer.hintText(state.hint) {
                            Text(hint)
                                .font(AppPixelFont.font)
                                .foregroundStyle(.white.opacity(0.72))
                                .frame(maxWidth: .infinity, alignment: .center)
                                .padding(.horizontal, 12)
                                .padding(.top, 6)
                        }
                    }
                }
                .allowsHitTesting(false)
                .padding(.bottom, max(geo.safeAreaInsets.bottom, 10))
            }
            .onAppear { relayout(size: geo.size, safe: geo.safeAreaInsets) }
            .onChange(of: layoutToken) { _, _ in
                relayout(size: geo.size, safe: geo.safeAreaInsets)
            }
            .contentShape(Rectangle())
            .onTapGesture(count: 1, coordinateSpace: .local) { location in
                handleTap(location)
            }
        }
        .allowsHitTesting(!sidebarOpen)
        .onAppear { playback.ingest(facts) }
        .onChange(of: facts) { _, next in
            playback.ingest(next)
        }
        .onChange(of: scenePhase) { _, phase in
            var next = facts
            next.sceneActive = phase == .active
            playback.ingest(next)
        }
        .onDisappear {
            playback.stop()
        }
    }

    private var liveSamples: [ProjectedRouteSample] {
        let snapshot = bridge.projection
        guard snapshot.isLive(attemptId: bridge.attemptId, wallId: facts.wallId) else {
            return []
        }
        return snapshot.samples
    }

    private var layoutToken: String {
        let ids = liveSamples.map(\.routeId).joined(separator: ",")
        let anchors = liveSamples.map { sample in
            guard let point = sample.anchor else { return "-" }
            return "\(Int(point.x / 4)):\(Int(point.y / 4))"
        }.joined(separator: ",")
        return "\(ids)|\(anchors)|\(bridge.selectedRouteId ?? "")|\(playback.state.hideChrome)|\(sidebarOpen)"
    }

    private var statusRow: some View {
        let state = playback.state
        return HStack(alignment: .top, spacing: 6) {
            statusColumn(
                pending: ScanLoadingCopy.identifyPending,
                title: ScanLoadingCopy.identifyTitle,
                done: state.identify == .success
            )
            statusColumn(
                pending: ScanLoadingCopy.localizePending,
                title: ScanLoadingCopy.localizeTitle,
                done: state.localize == .success
            )
            statusColumn(
                pending: ScanLoadingCopy.loadPending,
                title: ScanLoadingCopy.loadTitle,
                done: state.load == .success
            )
        }
        .frame(height: 40)
    }

    private func statusColumn(pending: String, title: String, done: Bool) -> some View {
        Text(ScanLoadingCopy.columnText(pending: pending, title: title, done: done))
            .font(AppPixelFont.font)
            .foregroundStyle(done ? ScanLoadingStyle.success : ScanLoadingStyle.pending)
            .multilineTextAlignment(.center)
            .lineLimit(2)
            .lineSpacing(0)
            .frame(maxWidth: .infinity, minHeight: 40, maxHeight: 40, alignment: .center)
    }

    private func mascot(in size: CGSize) -> some View {
        let state = playback.state
        let index = state.clip == .jump ? playback.jumpFrameIndex : playback.runFrameIndex
        let image = MascotSequence.image(clip: state.clip, index: index)
        let x = state.position * size.width
        return Group {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
                    .frame(width: 88, height: 88)
                    .offset(x: x - 44, y: 0)
            }
        }
    }

    private func handleTap(_ point: CGPoint) {
        if let hit = placements.first(where: { $0.frame.insetBy(dx: -6, dy: -6).contains(point) }) {
            bridge.selectRoute(hit.routeId)
            return
        }
        if let routeId = RouteLabelLayout.nearestRoute(samples: liveSamples, point: point) {
            bridge.selectRoute(routeId)
        }
    }

    private func relayout(size: CGSize, safe: EdgeInsets) {
        let samples = liveSamples
        guard !samples.isEmpty else {
            placements = []
            labelMemory = .empty
            return
        }
        var obstacles: [CGRect] = []
        if sidebarOpen {
            obstacles.append(CGRect(x: 0, y: 0, width: size.width / 3, height: size.height))
        }
        if !playback.state.hideChrome {
            let bottom = 120 + safe.bottom
            obstacles.append(CGRect(x: 0, y: size.height - bottom, width: size.width, height: bottom))
        }
        if EngineeringDiagnostics.isEnabled {
            obstacles.append(CGRect(x: size.width - 176, y: safe.top + 8, width: 168, height: 118))
        }
        let usable = CGRect(
            x: safe.leading,
            y: safe.top,
            width: size.width - safe.leading - safe.trailing,
            height: size.height - safe.top - safe.bottom
        )
        var texts: [String: (compact: String, expanded: Bool)] = [:]
        let selected = bridge.selectedRouteId
        let expandAll = samples.count == 1
        for sample in samples {
            guard let route = routes.first(where: { $0.routeId == sample.routeId }) else { continue }
            let compact = ProductionRouteFieldCopy.compactLine(route)
            let expanded = expandAll || sample.routeId == selected
            var display = compact
            if expanded, let caption = ProductionRouteFieldCopy.quickdrawCaption(route) {
                display += "\n\(caption)"
            }
            texts[sample.routeId] = (display, expanded)
        }
        let result = RouteLabelLayout.layout(
            samples: samples,
            texts: texts,
            context: RouteLabelLayout.Context(
                canvas: size,
                safeInsets: usable,
                obstacles: obstacles,
                selectedId: selected
            ),
            memory: labelMemory
        )
        placements = result.placements
        labelMemory = result.memory
    }
}

enum ScanLoadingStyle {
    static let success = Color(red: 215.0 / 255.0, green: 1.0, blue: 63.0 / 255.0)
    static let pending = Color.white.opacity(0.46)
}

private final class DisplayLinkTarget: NSObject {
    var onTick: ((CADisplayLink) -> Void)?

    @objc func tick(_ link: CADisplayLink) {
        onTick?(link)
    }
}

private struct RouteInteractionCanvas: View {
    var samples: [ProjectedRouteSample]
    var selectedId: String?
    var size: CGSize

    var body: some View {
        Canvas { context, _ in
            if let selectedId, let sample = samples.first(where: { $0.routeId == selectedId }), sample.polyline.count >= 2 {
                var path = Path()
                path.move(to: sample.polyline[0])
                for point in sample.polyline.dropFirst() {
                    path.addLine(to: point)
                }
                context.stroke(path, with: .color(.white.opacity(0.28)), lineWidth: 6)
            }
        }
        .frame(width: size.width, height: size.height)
        .allowsHitTesting(false)
    }
}

struct RouteScreenLabelOverlay: View {
    var routes: [VerifiedFrozenRoute]
    var placements: [RouteLabelPlacement]

    var body: some View {
        ZStack {
            ForEach(placements, id: \.routeId) { placement in
                Path { path in
                    path.move(to: placement.leaderEnd)
                    path.addLine(to: placement.leaderStart)
                }
                .stroke(Color.white.opacity(0.8), lineWidth: 1)
                .allowsHitTesting(false)
                RouteLabelCard(
                    route: routes.first(where: { $0.routeId == placement.routeId }),
                    placement: placement
                )
                .position(x: placement.frame.midX, y: placement.frame.midY)
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel(placement.compactText)
            }
        }
        .allowsHitTesting(true)
    }
}

private struct RouteLabelCard: View {
    var route: VerifiedFrozenRoute?
    var placement: RouteLabelPlacement

    var body: some View {
        let compact = placement.compactText
        VStack(alignment: .leading, spacing: 0) {
            if placement.expanded, let route {
                let name = ProductionRouteFieldCopy.officialText(route.routeName) ?? compact
                Text(name)
                    .font(AppPixelFont.font)
                    .foregroundStyle(.white)
                    .fixedSize(horizontal: false, vertical: true)
                if let grade = ProductionRouteFieldCopy.officialText(route.grade) {
                    Text(grade)
                        .font(AppPixelFont.font)
                        .foregroundStyle(.white)
                }
                if let caption = ProductionRouteFieldCopy.quickdrawCaption(route) {
                    HStack(spacing: 4) {
                        Image(systemName: "lock")
                            .font(.system(size: 11, weight: .regular))
                            .foregroundStyle(.white)
                            .accessibilityHidden(true)
                        Text(caption)
                            .font(AppPixelFont.font)
                            .foregroundStyle(.white)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel(caption)
                }
            } else {
                Text(compact)
                    .font(AppPixelFont.font)
                    .foregroundStyle(.white)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .frame(width: placement.frame.width, height: placement.frame.height, alignment: .topLeading)
        .background(Color.black.opacity(0.7), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}
