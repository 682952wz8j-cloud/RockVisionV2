import SwiftUI
import UIKit

struct FieldTestPanel: View {
    @ObservedObject var controller: FieldTestController
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Field Test")
                .font(.system(size: 15, weight: .semibold, design: .monospaced))
            Text(controller.storageLabel)
                .font(.system(size: 11, weight: .regular, design: .monospaced))
            Text(controller.lastSaveLabel)
                .font(.system(size: 11, weight: .regular, design: .monospaced))
            Text(controller.persistedSamplesLabel)
                .font(.system(size: 11, weight: .regular, design: .monospaced))
            Text(controller.exportLabel)
                .font(.system(size: 11, weight: .regular, design: .monospaced))
            if let error = controller.persistErrorLabel {
                Text("Persist error: \(error)")
                    .font(.system(size: 11, weight: .regular, design: .monospaced))
                    .foregroundStyle(.red)
            }
            Text(controller.instruction)
                .font(.system(size: 13, weight: .regular, design: .monospaced))
                .fixedSize(horizontal: false, vertical: true)
            Text("Progress: \(controller.progressLabel)   Time: \(controller.elapsedLabel)")
                .font(.system(size: 12, weight: .regular, design: .monospaced))
            Text("Mode: \(controller.plan.modeLabel)")
                .font(.system(size: 12, weight: .regular, design: .monospaced))

            if controller.canChangeMode {
                HStack(spacing: 8) {
                    fieldButton("Full A/B/C", emphasized: controller.plan == .full, enabled: true) {
                        controller.selectPlan(.full)
                    }
                    fieldButton("A only", emphasized: controller.plan == .single(.A), enabled: true) {
                        controller.selectPlan(.single(.A))
                    }
                }
                HStack(spacing: 8) {
                    fieldButton("B only", emphasized: controller.plan == .single(.B), enabled: true) {
                        controller.selectPlan(.single(.B))
                    }
                    fieldButton("C only", emphasized: controller.plan == .single(.C), enabled: true) {
                        controller.selectPlan(.single(.C))
                    }
                }
            }

            HStack(spacing: 8) {
                if controller.hasResumableSession {
                    fieldButton("Resume", emphasized: true, enabled: controller.canStartTest, action: controller.resume)
                    fieldButton("New Session", emphasized: false, enabled: controller.canStartTest, action: controller.startNewSession)
                } else {
                    switch controller.phase {
                    case .readyToStart(let scene), .readyToStartNext(_, let scene):
                        fieldButton("START \(scene.rawValue)", emphasized: true, enabled: controller.canStartTest, action: controller.startOfficialNext)
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
                fieldButton("Share Current Results", emphasized: true, enabled: controller.canExport, action: controller.shareCurrentResults)
                fieldButton("Copy Summary", emphasized: false, enabled: controller.canCopySummary) {
                    _ = controller.copySummary()
                    copied = true
                }
            }
            if copied {
                Text(controller.copyFeedback ?? "Summary copied")
                    .font(.system(size: 11, weight: .regular, design: .monospaced))
            }

            if let summary = controller.summary {
                let rows = summary.cells.filter { $0.status != .pending }
                if !rows.isEmpty {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 2) {
                            ForEach(rows, id: \.progressKey) { cell in
                                Text("\(cell.scene) \(cell.presetLabel) \(cell.status.rawValue) \(cell.progressLabel)")
                                    .font(.system(size: 11, weight: .regular, design: .monospaced))
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 88)
                }
            }

            Text(controller.sessionPath)
                .font(.system(size: 9, weight: .regular, design: .monospaced))
                .foregroundStyle(.white.opacity(0.7))
                .lineLimit(2)
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
    }
}

private struct FieldTestActivityView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

private extension FieldTestCellSummary {
    var progressKey: String { "\(scene)|\(presetLabel)|\(status.rawValue)|\(validCount)" }
}
