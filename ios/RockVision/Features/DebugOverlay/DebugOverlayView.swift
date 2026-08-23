import SwiftUI

/// Developer overlay. Localization stays idle. No matches / inliers / pose.
struct DebugOverlayView: View {
    let snapshot: ARSessionSnapshot
    let openCV: OpenCVRuntimeSnapshot
    let sift: SIFTRuntimeSnapshot
    var onSelectPreset: (SIFTProcessingPreset) -> Void = { _ in }
    var onToggleKeypoints: () -> Void = {}
    var onSelectScene: (String) -> Void = { _ in }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("RockVision V2")
                .font(.system(size: 15, weight: .semibold, design: .monospaced))
            row("Localization", snapshot.localizationState)
            row("ARKit", snapshot.trackingState)
            row("ARFrame", "\(snapshot.frameCount)")
            row("Camera", cameraResolution)
            row("OpenCV", openCV.status)
            row("SIFT", sift.status)
            row("Processing", sift.processing)
            row("Keypoints", sift.keypoints)
            row("Descriptors", sift.descriptors)
            row("Grid", sift.grid)
            row("Preprocess", ms(sift.preprocessMs))
            row("SIFT", ms(sift.siftMs))
            row("Total", ms(sift.totalMs))
            row("SIFT rate", "\(sift.rateHz) Hz  (req \(sift.requestedRateHz))")
            row("Skipped", "\(sift.skipped)")
            row("Scene", sift.scene)
            row("Dots", sift.showKeypoints ? "on" : "off")

            Text("Res")
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
            HStack(spacing: 6) {
                ForEach(SIFTProcessingPreset.allCases, id: \.rawValue) { preset in
                    debugButton(
                        title: preset.label,
                        selected: sift.presetLabel == preset.label || sift.processing == preset.displaySize
                    ) {
                        onSelectPreset(preset)
                    }
                }
            }

            Text("Scene")
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
            HStack(spacing: 6) {
                ForEach(SIFTSceneLabel.allCases, id: \.rawValue) { label in
                    debugButton(
                        title: label.buttonTitle,
                        selected: sift.scene == label.rawValue
                    ) {
                        onSelectScene(label.rawValue)
                    }
                }
            }

            debugButton(
                title: sift.showKeypoints ? "Dots: on" : "Dots: off",
                selected: sift.showKeypoints
            ) {
                onToggleKeypoints()
            }
        }
        .foregroundStyle(.white)
        .padding(10)
        .background(Color.black.opacity(0.62), in: RoundedRectangle(cornerRadius: 8))
        .padding(.top, 12)
        .padding(.leading, 12)
    }

    private var cameraResolution: String {
        if snapshot.cameraWidth == 0 || snapshot.cameraHeight == 0 {
            return "— × —"
        }
        return "\(snapshot.cameraWidth) × \(snapshot.cameraHeight)"
    }

    private func row(_ title: String, _ value: String) -> some View {
        Text("\(title): \(value)")
            .font(.system(size: 13, weight: .regular, design: .monospaced))
    }

    private func ms(_ value: String) -> String {
        value == "—" ? "—" : "\(value) ms"
    }

    private func debugButton(title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .foregroundStyle(.white)
                .padding(.horizontal, 8)
                .padding(.vertical, 8)
                .frame(minHeight: 32)
                .background(selected ? Color.white.opacity(0.38) : Color.white.opacity(0.16), in: RoundedRectangle(cornerRadius: 5))
                .overlay(
                    RoundedRectangle(cornerRadius: 5)
                        .stroke(selected ? Color.white : Color.white.opacity(0.45), lineWidth: 1)
                )
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
    }
}

private extension SIFTProcessingPreset {
    var displaySize: String {
        "\(targetWidth) × \(targetHeight)"
    }
}
