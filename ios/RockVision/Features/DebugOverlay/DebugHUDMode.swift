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

    /// DEBUG D5 evidence collection uses the Cloud discovery HUD.
    /// Release keeps the existing Gate 4B field-test surface; D5 Cloud UI
    /// is not production UI.
    static var active: DebugHUDMode {
        #if DEBUG
        .cloudD5
        #else
        .gate4b
        #endif
    }

    var showsCloudD5HUD: Bool { self == .cloudD5 }
    var showsGate4BHUD: Bool { self == .gate4b }
    var showsFullCloudDebugHUD: Bool { self == .stage3 }
}
