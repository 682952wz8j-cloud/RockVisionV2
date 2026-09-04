import SwiftUI
import UIKit

/// UI-only launch latch for the device Full Test. Not part of sample validity.
enum FieldTestLaunchGate {
    static func blockReason(
        storageReady: Bool,
        tracking: String,
        matchingStatus: String,
        presetLabel: String,
        processingLabel: String
    ) -> String? {
        if !storageReady {
            return "Storage 未就绪"
        }
        if matchingStatus != "active" {
            return "Matching 未就绪：\(matchingStatus)"
        }
        if !is960(presetLabel: presetLabel, processingLabel: processingLabel) {
            return "需要处理分辨率 960×720"
        }
        if tracking != "normal" {
            return "等待 ARKit tracking = normal"
        }
        return nil
    }

    static func is960(presetLabel: String, processingLabel: String) -> Bool {
        let compactPreset = presetLabel.replacingOccurrences(of: " ", with: "")
        let compactProcessing = processingLabel.replacingOccurrences(of: " ", with: "")
        return compactPreset == "960×720" || compactProcessing == "960×720"
    }
}

struct FieldTestPanel: View {
    @ObservedObject var controller: FieldTestController
    var tracking: String = "—"
    var localization: String = "idle"
    var confirmationWindow: String = "0/3"
    var alignment: String = "none"
    var wallAxes: String = "hidden"
    var wallMarkers: String = "0/4"
    var routeBinding: RuntimeRouteBinding = .unbound
    var routePlan: RouteRenderPlan = .empty
    var sift: SIFTRuntimeSnapshot = SIFTRuntimeSnapshot()
    var matching: MatchingRuntimeSnapshot = MatchingRuntimeSnapshot()
    var pnp: PnPRuntimeSnapshot = PnPRuntimeSnapshot()

    var body: some View {
        let actions = Gate4BPhysicalValidationHUD.actions(
            hasResumableSession: controller.hasResumableSession,
            phase: controller.phase,
            canExport: controller.canExport
        )
        let _ = retainedDiagnosticRows
        VStack(alignment: .leading, spacing: 3) {
            Text(Gate4BPhysicalValidationHUD.title)
                .font(.system(size: 12, weight: .semibold, design: .monospaced))

            if actions.showUnfinishedBanner {
                Text(Gate4BPhysicalValidationHUD.unfinishedMessage)
                    .font(.system(size: 11, weight: .regular, design: .monospaced))
            } else {
                if controller.phase == .complete {
                    Text("Measurement session complete")
                        .font(.system(size: 11, weight: .regular, design: .monospaced))
                }
                ForEach(visibleRows, id: \.title) { row in
                    statusRow(row.title, row.value)
                }
            }

            if let error = controller.persistErrorLabel {
                Text("Persist error: \(error)")
                    .font(.system(size: 10, weight: .regular, design: .monospaced))
                    .foregroundStyle(.red)
            }

            HStack(spacing: 6) {
                if actions.showResume {
                    fieldButton("Resume", emphasized: true, enabled: controller.canStartTest, action: controller.resume)
                }
                if actions.showNewSession {
                    fieldButton("New Session", emphasized: !actions.showResume, enabled: controller.canStartTest, action: controller.startNewSession)
                }
                if actions.showStartMeasurement {
                    fieldButton(
                        Gate4BPhysicalValidationHUD.startMeasurementTitle,
                        emphasized: true,
                        enabled: Gate4BPhysicalValidationHUD.startMeasurementEnabled(
                            canStartTest: controller.canStartTest,
                            storageReady: controller.storageReady,
                            tracking: tracking,
                            matchingStatus: matching.status,
                            presetLabel: sift.presetLabel,
                            processingLabel: sift.processing
                        ),
                        action: controller.startOfficialNext
                    )
                }
                if actions.showAbort {
                    fieldButton("Abort", emphasized: false, enabled: true, action: controller.abort)
                }
            }
            if actions.showShareResults {
                fieldButton(
                    "Share Results",
                    emphasized: controller.phase == .complete || controller.canExport,
                    enabled: controller.canExport,
                    action: controller.shareCurrentResults
                )
            }
        }
        .foregroundStyle(.white)
        .padding(8)
        .frame(maxWidth: 260, alignment: .leading)
        .background(Color.black.opacity(0.62), in: RoundedRectangle(cornerRadius: 6))
        .padding(.leading, 10)
        .padding(.bottom, 10)
        .onAppear { controller.enterFieldTest() }
        .sheet(isPresented: $controller.isSharePresented) {
            if let url = controller.shareZIPURL {
                FieldTestActivityView(url: url)
            }
        }
    }

    private var visibleRows: [Gate4BPhysicalValidationHUD.StatusRow] {
        Gate4BPhysicalValidationHUD.visibleRows(
            scene: currentSceneLabel,
            tracking: tracking,
            localization: localization,
            confirmationWindow: confirmationWindow,
            alignment: alignment,
            wallAxes: wallAxes,
            wallMarkers: wallMarkers,
            routeId: routeBinding.routeId,
            hashVerified: routeBinding.hashVerified,
            boundPointCount: routeBinding.routeARWorldPointCount,
            rendered: routePlan.wouldRender,
            visibleSegmentCount: routePlan.segmentCount,
            matching: matching,
            pnp: pnp
        )
    }

    /// Full historical Stage 3 mapping stays computed; only Unique 3D / PnP inliers / PnP are shown.
    var retainedDiagnosticRows: [Gate4BPhysicalValidationHUD.StatusRow] {
        Gate4BPhysicalValidationHUD.diagnosticRows(
            processing: "960×720",
            valid: "\(currentValidLabel) / \(FieldTestPolicy.targetValidSamples)",
            matching: matching,
            sift: sift,
            pnp: pnp
        )
    }

    private var currentSceneLabel: String {
        switch controller.phase {
        case .readyToStart(let scene), .waitingTracking(let scene, _), .sampling(let scene, _), .readyToStartNext(_, let scene):
            return scene.rawValue
        case .complete:
            return "done"
        case .idle:
            return "—"
        }
    }

    private var currentValidLabel: String {
        let parts = controller.progressLabel.split(separator: "/")
        return parts.first.map(String.init) ?? "—"
    }

    private func statusRow(_ title: String, _ value: String) -> some View {
        Text("\(title): \(value)")
            .font(.system(size: 11, weight: .regular, design: .monospaced))
    }

    private func fieldButton(_ title: String, emphasized: Bool, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .foregroundStyle(.white)
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .frame(minHeight: 28)
                .background(emphasized ? Color.white.opacity(0.36) : Color.white.opacity(0.16), in: RoundedRectangle(cornerRadius: 5))
                .overlay(RoundedRectangle(cornerRadius: 5).stroke(Color.white.opacity(0.7), lineWidth: 1))
                .contentShape(Rectangle())
                .opacity(enabled ? 1 : 0.4)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .accessibilityLabel(title)
    }
}

private struct FieldTestActivityView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
