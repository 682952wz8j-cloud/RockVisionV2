import SwiftUI

/// Debug-only SIFT dots. Positions must already be in the camera preview's view space.
struct KeypointOverlayView: View {
    let points: [CGPoint]

    var body: some View {
        Canvas { context, _ in
            let color = Color.green.opacity(0.85)
            for point in points {
                let rect = CGRect(x: point.x - 2, y: point.y - 2, width: 4, height: 4)
                context.fill(Path(ellipseIn: rect), with: .color(color))
            }
        }
        .allowsHitTesting(false)
    }
}
