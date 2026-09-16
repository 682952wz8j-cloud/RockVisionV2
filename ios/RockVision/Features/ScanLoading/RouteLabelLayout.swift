import CoreGraphics
import Foundation

struct ProjectedRouteSample: Equatable, Sendable {
    var routeId: String
    var anchor: CGPoint?
    var polyline: [CGPoint]
}

struct RouteProjectionSnapshot: Equatable, Sendable {
    var attemptId: UUID
    var wallId: String
    var renderedRoute: Bool
    var samples: [ProjectedRouteSample]

    static let empty = RouteProjectionSnapshot(
        attemptId: RouteApplyReceipt.none.attemptId,
        wallId: "",
        renderedRoute: false,
        samples: []
    )

    func isLive(attemptId: UUID, wallId: String) -> Bool {
        renderedRoute
            && self.attemptId == attemptId
            && self.wallId == wallId
            && !wallId.isEmpty
            && wallId != "—"
    }
}

enum RouteLabelSlot: Equatable, Sendable {
    case right
    case left
    case above
}

struct RouteLabelPlacement: Equatable, Sendable {
    var routeId: String
    var frame: CGRect
    var leaderStart: CGPoint
    var leaderEnd: CGPoint
    var expanded: Bool
    var compactText: String
    var slot: RouteLabelSlot
}

struct RouteLabelLayoutMemory: Equatable, Sendable {
    var visibleIds: [String]
    var slots: [String: RouteLabelSlot]

    static let empty = RouteLabelLayoutMemory(visibleIds: [], slots: [:])
}

enum RouteLabelLayout {
    static let maxLabels = 3
    static let gap: CGFloat = 8
    static let hitSlop: CGFloat = 22
    static let maxLeader: CGFloat = 72
    static let lineHeight: CGFloat = 20
    static let horizontalPadding: CGFloat = 8
    static let verticalPadding: CGFloat = 6
    static let hysteresis: CGFloat = 40

    struct Context {
        var canvas: CGSize
        var safeInsets: CGRect
        var obstacles: [CGRect]
        var selectedId: String?
    }

    static func compactText(name: String, grade: String?) -> String {
        if name.isEmpty {
            return grade ?? ""
        }
        if let grade, !grade.isEmpty {
            return "\(name) · \(grade)"
        }
        return name
    }

    static func measure(text: String, expanded: Bool, canvasWidth: CGFloat) -> CGSize {
        let maxWidth = canvasWidth * (expanded ? 0.46 : 0.38) - horizontalPadding * 2
        let font = AppPixelFont.uiFont
        let bounds = (text as NSString).boundingRect(
            with: CGSize(width: max(48, maxWidth), height: lineHeight * (expanded ? 4 : 2)),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: [.font: font],
            context: nil
        )
        let extra = expanded ? lineHeight : 0
        return CGSize(
            width: ceil(min(max(bounds.width, 24) + horizontalPadding * 2, canvasWidth * 0.5)),
            height: ceil(max(lineHeight, bounds.height) + extra + verticalPadding * 2)
        )
    }

    static func pickVisible(
        samples: [ProjectedRouteSample],
        selected: String?,
        canvas: CGSize,
        previous: [String]
    ) -> [String] {
        let ranked = samples
            .filter { sample in
                if let anchor = sample.anchor, canvas.contains(anchor) {
                    return true
                }
                return sample.polyline.contains { canvas.contains($0) }
            }
            .sorted { lhs, rhs in
                score(lhs, canvas: canvas) > score(rhs, canvas: canvas)
            }
        let rankedIds = ranked.map(\.routeId)
        var picked: [String] = []
        if let selected, rankedIds.contains(selected) {
            picked.append(selected)
        }
        for id in previous where picked.count < maxLabels && rankedIds.contains(id) {
            if !picked.contains(id) {
                picked.append(id)
            }
        }
        for id in rankedIds where picked.count < maxLabels {
            if !picked.contains(id) {
                picked.append(id)
            }
        }
        return Array(picked.prefix(maxLabels))
    }

    static func layout(
        samples: [ProjectedRouteSample],
        texts: [String: (compact: String, expanded: Bool)],
        context: Context,
        memory: RouteLabelLayoutMemory
    ) -> (placements: [RouteLabelPlacement], memory: RouteLabelLayoutMemory) {
        let ids = pickVisible(
            samples: samples,
            selected: context.selectedId,
            canvas: context.canvas,
            previous: memory.visibleIds
        )
        var placements: [RouteLabelPlacement] = []
        var slots = memory.slots
        var occupied = context.obstacles
        for id in ids {
            guard let sample = samples.first(where: { $0.routeId == id }),
                  let anchor = sample.anchor,
                  context.canvas.contains(anchor)
            else { continue }
            let copy = texts[id]
            let expanded = copy?.expanded ?? false
            let text = copy?.compact ?? ""
            guard !text.isEmpty else { continue }
            let size = measure(text: expanded ? text : text, expanded: expanded, canvasWidth: context.canvas.width)
            let preferred = slots[id]
            let order: [RouteLabelSlot] = {
                switch preferred {
                case .some(.left): return [.left, .right, .above]
                case .some(.above): return [.above, .right, .left]
                default: return [.right, .left, .above]
                }
            }()
            var placed: RouteLabelPlacement?
            for slot in order {
                if let candidate = placement(
                    sample: sample,
                    size: size,
                    slot: slot,
                    expanded: expanded,
                    text: text,
                    canvas: context.canvas,
                    safe: context.safeInsets,
                    obstacles: occupied,
                    polylines: samples.filter { $0.routeId != id }.map(\.polyline)
                ) {
                    placed = candidate
                    break
                }
            }
            if let placed {
                placements.append(placed)
                occupied.append(placed.frame.insetBy(dx: -4, dy: -4))
                slots[id] = placed.slot
            } else {
                slots[id] = nil
            }
        }
        let visible = placements.map(\.routeId)
        slots = slots.filter { visible.contains($0.key) }
        return (placements, RouteLabelLayoutMemory(visibleIds: visible, slots: slots))
    }

    static func nearestRoute(samples: [ProjectedRouteSample], point: CGPoint, slop: CGFloat = hitSlop) -> String? {
        var best: (String, CGFloat)?
        for sample in samples {
            let distance = minDistance(point, polyline: sample.polyline)
            if distance <= slop, best == nil || distance < best!.1 {
                best = (sample.routeId, distance)
            }
        }
        return best?.0
    }

    static func minDistance(_ point: CGPoint, polyline: [CGPoint]) -> CGFloat {
        guard polyline.count >= 2 else {
            return polyline.first.map { hypot($0.x - point.x, $0.y - point.y) } ?? .greatestFiniteMagnitude
        }
        var best = CGFloat.greatestFiniteMagnitude
        for index in 0..<(polyline.count - 1) {
            best = min(best, distance(point, polyline[index], polyline[index + 1]))
        }
        return best
    }

    private static func score(_ sample: ProjectedRouteSample, canvas: CGSize) -> CGFloat {
        let center = CGPoint(x: canvas.width * 0.5, y: canvas.height * 0.5)
        let point = sample.anchor ?? sample.polyline.first ?? center
        let dist = hypot(point.x - center.x, point.y - center.y)
        let visible = sample.polyline.filter { canvas.contains($0) }.count
        return CGFloat(visible) * 80 - dist
    }

    private static func placement(
        sample: ProjectedRouteSample,
        size: CGSize,
        slot: RouteLabelSlot,
        expanded: Bool,
        text: String,
        canvas: CGSize,
        safe: CGRect,
        obstacles: [CGRect],
        polylines: [[CGPoint]]
    ) -> RouteLabelPlacement? {
        guard let anchor = sample.anchor else { return nil }
        let origin: CGPoint
        switch slot {
        case .right:
            origin = CGPoint(x: anchor.x + gap, y: anchor.y - size.height * 0.65)
        case .left:
            origin = CGPoint(x: anchor.x - gap - size.width, y: anchor.y - size.height * 0.65)
        case .above:
            origin = CGPoint(x: anchor.x - size.width * 0.3, y: anchor.y - gap - size.height)
        }
        var frame = CGRect(origin: origin, size: size)
        let minX = max(safe.minX, 8)
        let maxX = min(safe.maxX, canvas.width - 8)
        let minY = max(safe.minY, 36)
        let maxY = min(safe.maxY, canvas.height - 36)
        frame.origin.x = min(max(frame.origin.x, minX), maxX - size.width)
        frame.origin.y = min(max(frame.origin.y, minY), maxY - size.height)
        if frame.width < 8 || frame.height < 8 { return nil }
        if hypot(frame.origin.x - origin.x, frame.origin.y - origin.y) > 48 { return nil }
        if frame.contains(anchor) { return nil }
        let leaderStart = leaderAttach(frame: frame, slot: slot, anchor: anchor)
        if hypot(leaderStart.x - anchor.x, leaderStart.y - anchor.y) > maxLeader { return nil }
        for obstacle in obstacles where obstacle.intersects(frame.insetBy(dx: -2, dy: -2)) {
            return nil
        }
        let grown = frame.insetBy(dx: -3, dy: -3)
        for polyline in polylines where lineHits(polyline, rect: grown) {
            return nil
        }
        return RouteLabelPlacement(
            routeId: sample.routeId,
            frame: frame,
            leaderStart: leaderStart,
            leaderEnd: anchor,
            expanded: expanded,
            compactText: text,
            slot: slot
        )
    }

    private static func leaderAttach(frame: CGRect, slot: RouteLabelSlot, anchor: CGPoint) -> CGPoint {
        switch slot {
        case .right:
            return CGPoint(x: frame.minX, y: min(max(anchor.y, frame.minY + 6), frame.maxY - 6))
        case .left:
            return CGPoint(x: frame.maxX, y: min(max(anchor.y, frame.minY + 6), frame.maxY - 6))
        case .above:
            return CGPoint(x: min(max(anchor.x, frame.minX + 6), frame.maxX - 6), y: frame.maxY)
        }
    }

    private static func lineHits(_ polyline: [CGPoint], rect: CGRect) -> Bool {
        if polyline.contains(where: { rect.contains($0) }) {
            return true
        }
        guard polyline.count >= 2 else { return false }
        let edges = [
            (CGPoint(x: rect.minX, y: rect.minY), CGPoint(x: rect.maxX, y: rect.minY)),
            (CGPoint(x: rect.maxX, y: rect.minY), CGPoint(x: rect.maxX, y: rect.maxY)),
            (CGPoint(x: rect.maxX, y: rect.maxY), CGPoint(x: rect.minX, y: rect.maxY)),
            (CGPoint(x: rect.minX, y: rect.maxY), CGPoint(x: rect.minX, y: rect.minY)),
        ]
        for index in 0..<(polyline.count - 1) {
            for edge in edges where segmentsIntersect(polyline[index], polyline[index + 1], edge.0, edge.1) {
                return true
            }
        }
        return false
    }

    private static func segmentsIntersect(_ p1: CGPoint, _ p2: CGPoint, _ p3: CGPoint, _ p4: CGPoint) -> Bool {
        func orient(_ a: CGPoint, _ b: CGPoint, _ c: CGPoint) -> CGFloat {
            (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
        }
        let o1 = orient(p1, p2, p3)
        let o2 = orient(p1, p2, p4)
        let o3 = orient(p3, p4, p1)
        let o4 = orient(p3, p4, p2)
        return o1 * o2 < 0 && o3 * o4 < 0
    }

    private static func distance(_ point: CGPoint, _ a: CGPoint, _ b: CGPoint) -> CGFloat {
        let dx = b.x - a.x
        let dy = b.y - a.y
        let length = max(dx * dx + dy * dy, 1e-6)
        let t = min(max(((point.x - a.x) * dx + (point.y - a.y) * dy) / length, 0), 1)
        let x = a.x + dx * t
        let y = a.y + dy * t
        return hypot(point.x - x, point.y - y)
    }
}

private extension CGSize {
    func contains(_ point: CGPoint) -> Bool {
        point.x >= 0 && point.y >= 0 && point.x <= width && point.y <= height
    }
}
