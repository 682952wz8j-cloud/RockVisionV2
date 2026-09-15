import SwiftUI

/// Official production-route copy for Field Engineering Mode.
/// Missing length / grade / quickdraw metadata is omitted, never synthesized.
enum ProductionRouteFieldCopy {
    static let copyColor = Color.white

    static func officialText(_ raw: String?) -> String? {
        guard let raw else { return nil }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if absentTokens.contains(trimmed.lowercased()) {
            return nil
        }
        return trimmed
    }

    static func officialLength(_ meters: Double?) -> String? {
        guard let meters, meters.isFinite, meters > 0 else { return nil }
        if meters == meters.rounded(.towardZero) {
            return "\(Int(meters)) m"
        }
        return String(format: "%.1f m", meters)
    }

    /// `🔗 x+2` only when official hanger count exists. Never invents `x`.
    static func quickdrawLine(_ raw: String?) -> String? {
        guard let text = officialText(raw), let count = hangerCount(from: text) else {
            return nil
        }
        return "🔗 \(count)+2"
    }

    static func hangerCount(from raw: String) -> Int? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        let parts = trimmed.split(separator: "+", omittingEmptySubsequences: false)
        if parts.count == 1, let count = Int(parts[0]), count >= 0 {
            return count
        }
        if parts.count == 2, parts[1] == "2", let count = Int(parts[0]), count >= 0 {
            return count
        }
        return nil
    }

    static func displayLines(_ route: VerifiedFrozenRoute) -> [String] {
        var lines: [String] = []
        if let name = officialText(route.routeName) {
            lines.append(name)
        }
        if let grade = officialText(route.grade) {
            lines.append(grade)
        }
        if let length = officialLength(route.lengthMeters) {
            lines.append(length)
        }
        if let draws = quickdrawLine(route.displayDraws) {
            lines.append(draws)
        }
        return lines
    }

    static func overlayTitle(_ route: VerifiedFrozenRoute) -> String {
        displayLines(route)
            .filter { !$0.hasPrefix("🔗") }
            .joined(separator: "\n")
    }

    private static let absentTokens: Set<String> = [
        "unspecified", "n/a", "na", "none", "unknown", "tbd", "—", "-",
    ]
}

/// Production Field Engineering Mode copy. Driven by live runtime, not a named wall.
enum Stage5DebugHUDModel {
    static let successLabel = "定位成功"
    static let failureLabel = "定位失败"
    static let cloudLoadedLabel = "云端已加载"
    static let cloudFailedLabel = "加载失败"

    static func localizationToken(state: String) -> String {
        state == ConfirmationConfig.localizationLocalized ? successLabel : failureLabel
    }

    static func diagnosticLine(
        localization: String,
        pnp: PnPRuntimeSnapshot,
        wallId: String,
        cloudAssetsLoaded: Bool
    ) -> String {
        let liveWallId = wallId.isEmpty ? "—" : wallId
        let cloud = cloudAssetsLoaded ? cloudLoadedLabel : cloudFailedLabel
        return [
            localizationToken(state: localization),
            "PnP \(pnp.inliers)",
            "\(medianToken(pnp.reproj)) px",
            liveWallId,
            cloud,
        ].joined(separator: " | ")
    }

    static func localizationLine(state: String) -> String {
        localizationToken(state: state)
    }

    static func pnpLine(inliers: String, reproj: String) -> String {
        "PnP \(inliers) | \(medianToken(reproj)) px"
    }

    static func wallIdLine(_ wallId: String) -> String {
        wallId
    }

    static func cloudLine(loaded: Bool) -> String {
        loaded ? cloudLoadedLabel : cloudFailedLabel
    }

    static func lines(
        localization: String,
        pnp: PnPRuntimeSnapshot,
        wallId: String,
        cloudAssetsLoaded: Bool
    ) -> [String] {
        [diagnosticLine(localization: localization, pnp: pnp, wallId: wallId, cloudAssetsLoaded: cloudAssetsLoaded)]
    }

    private static func medianToken(_ reproj: String) -> String {
        if reproj.hasSuffix(" px") {
            return String(reproj.dropLast(3))
        }
        return reproj
    }
}

/// Field Engineering Mode: package route copy + one weak live diagnostic line.
struct Stage5DebugHUD: View {
    var localization: String
    var pnp: PnPRuntimeSnapshot
    var wallId: String
    var cloudAssetsLoaded: Bool
    var routes: [VerifiedFrozenRoute] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()
            VStack(alignment: .leading, spacing: 14) {
                ForEach(routes, id: \.routeId) { route in
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(
                            Array(ProductionRouteFieldCopy.displayLines(route).enumerated()),
                            id: \.offset
                        ) { _, line in
                            Text(line)
                                .font(.system(size: 20, weight: .semibold))
                                .foregroundStyle(ProductionRouteFieldCopy.copyColor)
                        }
                    }
                }
            }
            .padding(.leading, 16)
            .padding(.bottom, 16)
            Text(
                Stage5DebugHUDModel.diagnosticLine(
                    localization: localization,
                    pnp: pnp,
                    wallId: wallId,
                    cloudAssetsLoaded: cloudAssetsLoaded
                )
            )
            .font(.system(size: 11, weight: .regular, design: .monospaced))
            .foregroundStyle(.white.opacity(0.38))
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 12)
            .padding(.bottom, 8)
        }
        .allowsHitTesting(false)
    }
}
