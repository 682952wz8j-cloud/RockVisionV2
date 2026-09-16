import SwiftUI

enum EngineeringDiagnostics {
    static var isEnabled: Bool {
        #if DEBUG
        true
        #else
        false
        #endif
    }
}

struct EngineeringDiagnosticsPanel: View {
    var localization: String
    var window: String
    var pnp: PnPRuntimeSnapshot
    var wallId: String
    var cloudAssetsLoaded: Bool
    var renderedRoute: Bool
    var matchingStatus: String
    var lastError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(lines, id: \.self) { line in
                Text(line)
                    .font(AppPixelFont.font)
                    .foregroundStyle(.white.opacity(0.62))
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(Color.black.opacity(0.35), in: RoundedRectangle(cornerRadius: 7, style: .continuous))
        .allowsHitTesting(false)
    }

    var lines: [String] {
        EngineeringDiagnosticsModel.lines(
            localization: localization,
            window: window,
            pnp: pnp,
            wallId: wallId,
            cloudAssetsLoaded: cloudAssetsLoaded,
            renderedRoute: renderedRoute,
            matchingStatus: matchingStatus,
            lastError: lastError
        )
    }
}

enum EngineeringDiagnosticsModel {
    static func lines(
        localization: String,
        window: String,
        pnp: PnPRuntimeSnapshot,
        wallId: String,
        cloudAssetsLoaded: Bool,
        renderedRoute: Bool,
        matchingStatus: String,
        lastError: String?
    ) -> [String] {
        let liveWall = wallId.isEmpty ? "—" : wallId
        let cloud = cloudAssetsLoaded ? Stage5DebugHUDModel.cloudLoadedLabel : Stage5DebugHUDModel.cloudFailedLabel
        let reproj = pnp.reproj.hasSuffix(" px") ? String(pnp.reproj.dropLast(3)) : pnp.reproj
        var rows = [
            "\(Stage5DebugHUDModel.localizationToken(state: localization)) \(window)",
            "PnP \(pnp.inliers) | \(reproj) px",
            liveWall,
            cloud,
            renderedRoute ? "route applied" : "route idle",
        ]
        if let lastError, !lastError.isEmpty {
            rows.append(String(lastError.prefix(48)))
        } else {
            rows.append("match \(matchingStatus)")
        }
        return Array(rows.prefix(6))
    }
}
