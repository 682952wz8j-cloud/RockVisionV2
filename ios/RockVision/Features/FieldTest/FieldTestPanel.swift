import SwiftUI

struct FieldTestPanel: View {
    @ObservedObject var controller: FieldTestController

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Field Test")
                .font(.system(size: 15, weight: .semibold, design: .monospaced))
            Text(controller.instruction)
                .font(.system(size: 13, weight: .regular, design: .monospaced))
                .fixedSize(horizontal: false, vertical: true)
            Text("Progress: \(controller.progressLabel)   Time: \(controller.elapsedLabel)")
                .font(.system(size: 12, weight: .regular, design: .monospaced))
            if let summary = controller.summary {
                ForEach(summary.cells.filter { $0.status != .pending }, id: \.progressKey) { cell in
                    Text("\(cell.scene) \(cell.presetLabel) \(cell.status.rawValue) \(cell.progressLabel)")
                        .font(.system(size: 11, weight: .regular, design: .monospaced))
                }
            }

            HStack(spacing: 8) {
                if controller.hasResumableSession {
                    fieldButton("Resume", emphasized: true, action: controller.resume)
                    fieldButton("New Session", emphasized: false, action: controller.startNewSession)
                } else {
                    switch controller.phase {
                    case .readyToStart(let scene), .readyToStartNext(_, let scene):
                        fieldButton("START \(scene.rawValue)", emphasized: true, action: controller.startOfficialNext)
                    case .complete:
                        EmptyView()
                    case .idle:
                        fieldButton("New Session", emphasized: true, action: controller.startNewSession)
                    default:
                        fieldButton("Abort", emphasized: false, action: controller.abort)
                    }
                }
            }

            if controller.canShare, let url = controller.shareURL {
                ShareLink(item: url) {
                    Text("Share results")
                        .font(.system(size: 13, weight: .semibold, design: .monospaced))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 8)
                        .background(Color.white.opacity(0.28), in: RoundedRectangle(cornerRadius: 5))
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
    }

    private func fieldButton(_ title: String, emphasized: Bool, action: @escaping () -> Void) -> some View {
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
        }
        .buttonStyle(.plain)
    }
}

private extension FieldTestCellSummary {
    var progressKey: String { "\(scene)|\(presetLabel)|\(status.rawValue)|\(validCount)" }
}
