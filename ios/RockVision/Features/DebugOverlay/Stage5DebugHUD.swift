import SwiftUI

/// Stage 5 DEBUG field HUD copy only. Does not own overlay or localization math.
enum Stage5DebugHUDModel {
    static let successLabel = "定位成功"
    static let failureLabel = "定位失败"

    static func localizationLine(state: String) -> String {
        state == ConfirmationConfig.localizationLocalized ? successLabel : failureLabel
    }

    static func pnpLine(inliers: String, reproj: String) -> String {
        "PnP \(inliers) | \(medianToken(reproj)) px"
    }

    static func lines(localization: String, pnp: PnPRuntimeSnapshot) -> [String] {
        [
            localizationLine(state: localization),
            pnpLine(inliers: pnp.inliers, reproj: pnp.reproj)
        ]
    }

    private static func medianToken(_ reproj: String) -> String {
        if reproj.hasSuffix(" px") {
            return String(reproj.dropLast(3))
        }
        return reproj
    }
}

/// DEBUG Stage 5 screenshot HUD: localization + live PnP only.
struct Stage5DebugHUD: View {
    var localization: String
    var pnp: PnPRuntimeSnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(Stage5DebugHUDModel.lines(localization: localization, pnp: pnp), id: \.self) { line in
                Text(line)
                    .font(.system(size: 14, weight: .semibold, design: .monospaced))
            }
        }
        .foregroundStyle(.white)
        .padding(8)
        .background(Color.black.opacity(0.62), in: RoundedRectangle(cornerRadius: 6))
        .padding(.leading, 10)
        .padding(.bottom, 10)
    }
}
