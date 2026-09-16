import Foundation
import SwiftUI

/// Display-layer apply receipt. `renderedRoute` means RouteOverlay attached
/// segment entities this pass — not a GPU first-frame proof.
struct RouteApplyReceipt: Equatable, Sendable {
    var attemptId: UUID
    var wallId: String
    var renderedRoute: Bool
    var routeId: String?
    var visibleSegmentCount: Int

    static let none = RouteApplyReceipt(
        attemptId: UUID(uuidString: "00000000-0000-0000-0000-000000000000")!,
        wallId: "",
        renderedRoute: false,
        routeId: nil,
        visibleSegmentCount: 0
    )
}

struct RouteScreenLabel: Equatable, Sendable {
    var routeId: String
    var point: CGPoint
}

/// Shared by ARCameraPreview and the loading HUD. Attempt id changes are rare;
/// mascot motion must not publish through this object.
@MainActor
final class ScanSessionBridge: ObservableObject {
    @Published private(set) var attemptId = UUID()
    @Published private(set) var receipt = RouteApplyReceipt.none
    @Published private(set) var screenLabels: [RouteScreenLabel] = []
    @Published private(set) var projection = RouteProjectionSnapshot.empty
    @Published private(set) var selectedRouteId: String?

    private var lastReceipt = RouteApplyReceipt.none
    private var lastProjection = RouteProjectionSnapshot.empty

    func beginAttempt() -> UUID {
        let next = UUID()
        attemptId = next
        lastReceipt = .none
        lastProjection = .empty
        receipt = .none
        screenLabels = []
        projection = .empty
        selectedRouteId = nil
        return next
    }

    func selectRoute(_ routeId: String?) {
        if selectedRouteId != routeId {
            selectedRouteId = routeId
        }
    }

    /// Called from ARCameraPreview. Never publishes synchronously during
    /// `updateUIView`; identical receipts are ignored.
    nonisolated func noteCoordinatorApply(receipt: RouteApplyReceipt, snapshot: RouteProjectionSnapshot) {
        Task { @MainActor [receipt, snapshot] in
            let receiptChanged = receipt != lastReceipt
            let projectionChanged = !Self.projectionEquivalent(lastProjection, snapshot)
            guard receiptChanged || projectionChanged else { return }
            lastReceipt = receipt
            lastProjection = snapshot
            if receiptChanged {
                self.receipt = receipt
            }
            if projectionChanged {
                self.projection = snapshot
                self.screenLabels = snapshot.samples.compactMap { sample in
                    guard let point = sample.anchor else { return nil }
                    return RouteScreenLabel(routeId: sample.routeId, point: point)
                }
                if let selected = self.selectedRouteId,
                   !snapshot.samples.contains(where: { $0.routeId == selected })
                {
                    self.selectedRouteId = snapshot.samples.count == 1 ? snapshot.samples[0].routeId : nil
                } else if self.selectedRouteId == nil, snapshot.samples.count == 1 {
                    self.selectedRouteId = snapshot.samples[0].routeId
                }
            }
        }
    }

    private static func projectionEquivalent(_ a: RouteProjectionSnapshot, _ b: RouteProjectionSnapshot) -> Bool {
        guard a.attemptId == b.attemptId,
              a.wallId == b.wallId,
              a.renderedRoute == b.renderedRoute,
              a.samples.count == b.samples.count
        else { return false }
        for (lhs, rhs) in zip(a.samples, b.samples) {
            if lhs.routeId != rhs.routeId { return false }
            if !pointsClose(lhs.anchor, rhs.anchor) { return false }
            if lhs.polyline.count != rhs.polyline.count { return false }
            for (p, q) in zip(lhs.polyline, rhs.polyline) {
                if abs(p.x - q.x) > 1.5 || abs(p.y - q.y) > 1.5 { return false }
            }
        }
        return true
    }

    private static func pointsClose(_ a: CGPoint?, _ b: CGPoint?) -> Bool {
        switch (a, b) {
        case (nil, nil):
            return true
        case let (l?, r?):
            return abs(l.x - r.x) <= 1.5 && abs(l.y - r.y) <= 1.5
        default:
            return false
        }
    }
}
