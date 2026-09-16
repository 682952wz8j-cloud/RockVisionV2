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

    struct ScreenCard: Equatable, Sendable {
        var name: String
        var grade: String?
        var secondary: [String]
    }

    /// Screen-space card after apply. `displayDraws` stays `x+2` (hangers + anchors), never bolt counts.
    static func screenCard(_ route: VerifiedFrozenRoute) -> ScreenCard {
        var secondary: [String] = []
        if let length = officialLength(route.lengthMeters) {
            secondary.append(length)
        }
        if let draws = quickdrawLine(route.displayDraws) {
            secondary.append(draws)
        }
        return ScreenCard(
            name: officialText(route.routeName) ?? "",
            grade: officialText(route.grade),
            secondary: secondary
        )
    }

    static func compactLine(_ route: VerifiedFrozenRoute) -> String {
        RouteLabelLayout.compactText(
            name: officialText(route.routeName) ?? "",
            grade: officialText(route.grade)
        )
    }

    /// Selected-card caption. Keeps hanger+2 meaning; does not use emoji.
    static func quickdrawCaption(_ route: VerifiedFrozenRoute) -> String? {
        guard let text = officialText(route.displayDraws), let count = hangerCount(from: text) else {
            return nil
        }
        return "快挂 \(count)+2"
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

/// Diagnostic copy helpers. Product Field Engineering HUD lives in ScanLoadingHUD.
struct Stage5DebugHUD: View {
    var localization: String
    var pnp: PnPRuntimeSnapshot
    var wallId: String
    var cloudAssetsLoaded: Bool

    var body: some View {
        EmptyView()
    }
}
