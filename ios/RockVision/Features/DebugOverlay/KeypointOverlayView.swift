import SwiftUI

enum KeypointOverlayAppearance: Equatable, Sendable {
    case debug
    case scan

    var color: Color {
        switch self {
        case .debug:
            return Color.green.opacity(0.85)
        case .scan:
            return Color(red: 215.0 / 255.0, green: 1.0, blue: 63.0 / 255.0).opacity(0.55)
        }
    }

    var pointSize: CGFloat {
        switch self {
        case .debug:
            return 4
        case .scan:
            return 2.6
        }
    }

    var maxPoints: Int {
        switch self {
        case .debug:
            return 200
        case .scan:
            return 64
        }
    }
}

enum VisualFeatureOverlay {
    static func isVisible(
        receipt: RouteApplyReceipt,
        attemptId: UUID,
        sceneActive: Bool
    ) -> Bool {
        guard sceneActive else { return false }
        return !(receipt.renderedRoute && receipt.attemptId == attemptId)
    }

    static func sampled(_ points: [CGPoint], maxCount: Int) -> [CGPoint] {
        guard maxCount > 0 else { return [] }
        guard points.count > maxCount else { return points }
        let step = max(1, points.count / maxCount)
        var sampled: [CGPoint] = []
        sampled.reserveCapacity(maxCount)
        var index = 0
        while index < points.count, sampled.count < maxCount {
            sampled.append(points[index])
            index += step
        }
        return sampled
    }
}

/// SIFT dots in camera preview space. Scan appearance uses #D7FF3F at ~55% opacity.
struct KeypointOverlayView: View {
    let points: [CGPoint]
    var appearance: KeypointOverlayAppearance = .debug
    var visible: Bool = true
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let drawn = VisualFeatureOverlay.sampled(points, maxCount: appearance.maxPoints)
        let size = appearance.pointSize
        Canvas { context, _ in
            let color = appearance.color
            for point in drawn {
                let rect = CGRect(
                    x: point.x - size / 2,
                    y: point.y - size / 2,
                    width: size,
                    height: size
                )
                context.fill(Path(ellipseIn: rect), with: .color(color))
            }
        }
        .opacity(visible ? 1 : 0)
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.45), value: visible)
        .allowsHitTesting(false)
    }
}
