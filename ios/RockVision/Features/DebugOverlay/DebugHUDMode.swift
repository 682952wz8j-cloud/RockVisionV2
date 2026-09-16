import Foundation

/// Which DEBUG/field-test HUD owns the screen.
///
/// Active test phase owns the debug HUD. Show only controls, progress,
/// and PASS/FAIL evidence for the current Gate/Phase. Do not mix
/// historical diagnostic surfaces into every field test.
enum DebugHUDMode: String, Equatable, Sendable {
    case cloudD5
    case gate4b
    case stage3
    case stage5

    /// DEBUG Production Field Engineering Mode owns the HUD.
    /// Release uses the product scan surface; engineering controls are DEBUG-only.
    static var active: DebugHUDMode {
        #if DEBUG
        .stage5
        #else
        .stage5
        #endif
    }

    var showsCloudD5HUD: Bool { self == .cloudD5 }
    var showsGate4BHUD: Bool { self == .gate4b }
    var showsFullCloudDebugHUD: Bool { self == .stage3 }
    var showsStage5HUD: Bool { self == .stage5 }
}
