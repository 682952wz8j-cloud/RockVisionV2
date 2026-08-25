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
    var sift: SIFTRuntimeSnapshot = SIFTRuntimeSnapshot()
    var matching: MatchingRuntimeSnapshot = MatchingRuntimeSnapshot()
    var pnp: PnPRuntimeSnapshot = PnPRuntimeSnapshot()
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Field Test")
                .font(.system(size: 15, weight: .semibold, design: .monospaced))
            statusRow("Scene", currentSceneLabel)
            statusRow("Processing", "960×720")
            statusRow("Valid", "\(currentValidLabel) / \(FieldTestPolicy.targetValidSamples)")
            statusRow("Tracking", tracking)
            statusRow("Matching", matching.status)
            statusRow("Query kp", matching.queryKeypoints)
            statusRow("Accepted", matching.acceptedAfterRatio)
            statusRow("Unique 3D", matching.acceptedUniquePoint3D)
            statusRow("SIFT", ms(sift.siftMs))
            statusRow("Match", ms(matching.matchingMs))
            statusRow("Stage3", ms(matching.stage3Ms))
            statusRow("PnP", pnp.status)
            statusRow("PnP in", pnp.inputCorr)
            statusRow("RANSAC inliers", pnp.inliers)
            statusRow("Inlier ratio", pnp.inlierRatio)
            statusRow("Reproj", pnp.reproj)
            statusRow("C_wall", pnp.cWall)
            statusRow("obs-depth sanity", pnp.obsDepth)
            statusRow("Localization", localization)
            statusRow("Confirm window", confirmationWindow)
            statusRow("T_ARWorld_Wall", alignment)
            statusRow("Wall axes", wallAxes)

            Text(controller.instruction)
                .font(.system(size: 13, weight: .regular, design: .monospaced))
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 10) {
                sceneChip("A")
                sceneChip("B")
                sceneChip("C")
            }

            if let error = controller.persistErrorLabel {
                Text("Persist error: \(error)")
                    .font(.system(size: 11, weight: .regular, design: .monospaced))
                    .foregroundStyle(.red)
            }
            if let gate = launchBlockReason, showsLaunchButton {
                Text(gate)
                    .font(.system(size: 12, weight: .regular, design: .monospaced))
                    .foregroundStyle(.yellow)
            }

            if controller.phase == .complete {
                Text("Test Complete")
                    .font(.system(size: 15, weight: .semibold, design: .monospaced))
            }

            HStack(spacing: 8) {
                if controller.hasResumableSession {
                    fieldButton("Resume", emphasized: true, enabled: controller.canStartTest, action: controller.resume)
                    fieldButton("New Session", emphasized: false, enabled: controller.canStartTest, action: controller.startNewSession)
                } else {
                    switch controller.phase {
                    case .readyToStart(let scene):
                        fieldButton("Start \(scene.rawValue)", emphasized: true, enabled: canPressLaunch, action: controller.startOfficialNext)
                    case .readyToStartNext(_, let scene):
                        fieldButton("Continue \(scene.rawValue)", emphasized: true, enabled: canPressLaunch, action: controller.startOfficialNext)
                    case .complete:
                        fieldButton("New Session", emphasized: false, enabled: controller.canStartTest, action: controller.startNewSession)
                    case .idle:
                        fieldButton("New Session", emphasized: true, enabled: controller.canStartTest, action: controller.startNewSession)
                    default:
                        fieldButton("Abort", emphasized: false, enabled: true, action: controller.abort)
                    }
                }
            }

            HStack(spacing: 8) {
                fieldButton(
                    "Share Current Results",
                    emphasized: controller.phase == .complete || controller.canExport,
                    enabled: controller.canExport,
                    action: controller.shareCurrentResults
                )
                fieldButton("Copy Summary", emphasized: false, enabled: controller.canCopySummary) {
                    _ = controller.copySummary()
                    copied = true
                }
            }
            if copied {
                Text(controller.copyFeedback ?? "Summary copied")
                    .font(.system(size: 11, weight: .regular, design: .monospaced))
            }
        }
        .foregroundStyle(.white)
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.black.opacity(0.72), in: RoundedRectangle(cornerRadius: 8))
        .padding(.horizontal, 12)
        .padding(.bottom, 12)
        .onAppear { controller.enterFieldTest() }
        .sheet(isPresented: $controller.isSharePresented) {
            if let url = controller.shareZIPURL {
                FieldTestActivityView(url: url)
            }
        }
    }

    private var launchBlockReason: String? {
        FieldTestLaunchGate.blockReason(
            storageReady: controller.storageReady,
            tracking: tracking,
            matchingStatus: matching.status,
            presetLabel: sift.presetLabel,
            processingLabel: sift.processing
        )
    }

    private var showsLaunchButton: Bool {
        switch controller.phase {
        case .readyToStart, .readyToStartNext:
            return !controller.hasResumableSession
        default:
            return false
        }
    }

    private var canPressLaunch: Bool {
        controller.canStartTest && launchBlockReason == nil
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

    private func sceneChip(_ scene: String) -> some View {
        let status = controller.summary?.cells.first {
            $0.scene == scene && $0.presetLabel == SIFTProcessingPreset.low.label
        }?.status ?? .pending
        let label: String
        switch status {
        case .complete: label = "complete"
        case .incomplete: label = "incomplete"
        case .running: label = "running"
        case .notRequested: label = "—"
        case .pending: label = "pending"
        }
        return Text("\(scene) \(label)")
            .font(.system(size: 12, weight: .semibold, design: .monospaced))
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(Color.white.opacity(0.16), in: RoundedRectangle(cornerRadius: 5))
    }

    private func statusRow(_ title: String, _ value: String) -> some View {
        Text("\(title): \(value)")
            .font(.system(size: 13, weight: .regular, design: .monospaced))
    }

    private func ms(_ value: String) -> String {
        value == "—" ? "—" : "\(value) ms"
    }

    private func fieldButton(_ title: String, emphasized: Bool, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 13, weight: .semibold, design: .monospaced))
                .foregroundStyle(.white)
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .frame(minHeight: 36)
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
