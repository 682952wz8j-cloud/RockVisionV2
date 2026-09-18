import Foundation

enum ScanStageStatus: Equatable, Sendable {
    case pending
    case success
}

enum ScanHintKind: Equatable, Sendable {
    case none
    case aimAtWall
    case network
    case locationPermission
    case locationUnavailable
    case cameraPermission
    case cameraUnavailable
    case package
    case noWall
    case failed
}

enum MascotClipKind: Equatable, Sendable {
    case run
    case jump
}

enum ScanLoadingMotion {
    static let enterPosition = -0.18
    static let identifyCap = 0.36
    static let localizeCap = 0.68
    static let exitPosition = 1.20
    static let crawlSpeed = 0.055
    static let matchingSpeed = 0.10
    static let localizedSpeed = 0.14
    static let exitSpeed = 0.58
    static let accelPerSecond = 0.48
    static let jumpDuration = Double(MascotSequence.jumpFrameCount) / MascotSequence.framesPerSecond
    static let longWaitSeconds = 8.0
    static let minCrawl = 0.012
}

struct ScanLoadingFacts: Equatable, Sendable {
    var localization: String
    var lostLocalized: Bool
    var matchingStatus: String
    var cloudAssetsLoaded: Bool
    var wallId: String
    var lastError: String?
    var receipt: RouteApplyReceipt
    var sceneActive: Bool
}

struct ScanLoadingState: Equatable, Sendable {
    var attemptId: UUID
    var wallId: String
    var identify: ScanStageStatus
    var localize: ScanStageStatus
    var load: ScanStageStatus
    var hint: ScanHintKind
    /// Loading status row only. Route labels do not follow this flag.
    var hideChrome: Bool
    var mascotHidden: Bool
    var clip: MascotClipKind
    var didJump: Bool
    var jumpElapsed: Double
    var position: Double
    var speed: Double
    var hardError: Bool
    var attemptStartedAt: TimeInterval
    var handledLostPulse: Bool
    var seenLocalized: Bool
    var lastConsumedReceipt: RouteApplyReceipt

    static func fresh(attemptId: UUID, wallId: String, now: TimeInterval) -> ScanLoadingState {
        ScanLoadingState(
            attemptId: attemptId,
            wallId: wallId,
            identify: .pending,
            localize: .pending,
            load: .pending,
            hint: .none,
            hideChrome: false,
            mascotHidden: false,
            clip: .run,
            didJump: false,
            jumpElapsed: 0,
            position: ScanLoadingMotion.enterPosition,
            speed: ScanLoadingMotion.crawlSpeed,
            hardError: false,
            attemptStartedAt: now,
            handledLostPulse: false,
            seenLocalized: false,
            lastConsumedReceipt: .none
        )
    }
}

enum ScanLoadingReducer {
    static func ingest(
        _ state: inout ScanLoadingState,
        facts: ScanLoadingFacts,
        now: TimeInterval = Date().timeIntervalSince1970,
        newAttemptId: () -> UUID
    ) {
        if !facts.sceneActive {
            return
        }
        if facts.wallId != state.wallId, facts.wallId != "—", !facts.wallId.isEmpty {
            state = .fresh(attemptId: newAttemptId(), wallId: facts.wallId, now: now)
        }

        // A background/session reset can return directly to idle without a lost pulse.
        if facts.localization == "idle", !facts.lostLocalized, state.seenLocalized {
            state = .fresh(attemptId: newAttemptId(), wallId: facts.wallId, now: now)
        }
        if facts.lostLocalized, state.seenLocalized, !state.handledLostPulse {
            state = .fresh(attemptId: newAttemptId(), wallId: facts.wallId, now: now)
            state.handledLostPulse = true
        } else if !facts.lostLocalized {
            state.handledLostPulse = false
        }

        state.hardError = {
            let kind = classifiedError(facts.lastError)
            switch kind {
            case .network, .package, .noWall, .failed, .locationPermission, .locationUnavailable, .cameraPermission, .cameraUnavailable:
                return facts.localization != ConfirmationConfig.localizationLocalized
                    && !facts.receipt.renderedRoute
            case .none, .aimAtWall:
                return false
            }
        }()

        if facts.localization == ConfirmationConfig.localizationLocalized {
            state.seenLocalized = true
            state.identify = .success
            state.localize = .success
        }

        let receipt = facts.receipt
        let isCurrentAttempt = receipt.attemptId == state.attemptId
        let isNewReceipt = receipt != state.lastConsumedReceipt
        if isCurrentAttempt, isNewReceipt {
            state.lastConsumedReceipt = receipt
            if receipt.renderedRoute, !state.didJump {
                state.load = .success
                state.clip = .jump
                state.didJump = true
                state.jumpElapsed = 0
            }
        }

        if state.hardError {
            state.identify = state.identify == .success ? .success : .pending
            state.localize = state.localize == .success ? .success : .pending
            if state.load != .success {
                state.load = .pending
            }
            if !state.didJump {
                state.clip = .run
            }
        }

        state.hint = hint(state: state, facts: facts, now: now)
    }

    static func tick(_ state: inout ScanLoadingState, dt: Double, matchingActive: Bool) {
        guard !state.mascotHidden else { return }
        if state.clip == .jump {
            state.jumpElapsed += dt
            if state.jumpElapsed >= ScanLoadingMotion.jumpDuration {
                state.clip = .run
            }
        }

        let cap: Double?
        if state.load == .success, state.jumpElapsed >= ScanLoadingMotion.jumpDuration {
            cap = nil
        } else if state.load == .success {
            cap = nil
        } else if state.localize == .success {
            cap = ScanLoadingMotion.localizeCap
        } else {
            cap = ScanLoadingMotion.identifyCap
        }

        var target = ScanLoadingMotion.crawlSpeed
        if matchingActive {
            target = ScanLoadingMotion.matchingSpeed
        }
        if state.localize == .success {
            target = ScanLoadingMotion.localizedSpeed
        }
        if state.load == .success, state.jumpElapsed >= ScanLoadingMotion.jumpDuration {
            target = ScanLoadingMotion.exitSpeed
        } else if state.load == .success {
            target = ScanLoadingMotion.localizedSpeed
        }
        if state.hardError {
            target = 0
        }
        if let cap {
            let remaining = cap - state.position
            if remaining <= 0.08 {
                target = min(target, max(ScanLoadingMotion.minCrawl, remaining * 1.6))
            }
            if remaining <= 0.002 {
                target = 0
            }
        }

        let maxDelta = ScanLoadingMotion.accelPerSecond * dt
        let delta = min(max(target - state.speed, -maxDelta), maxDelta)
        state.speed += delta
        var next = state.position + state.speed * dt
        if let cap {
            next = min(next, cap)
        }
        state.position = next

        if state.load == .success, state.position >= ScanLoadingMotion.exitPosition {
            state.hideChrome = true
            state.mascotHidden = true
        }
    }

    static func classifiedError(_ raw: String?) -> ScanHintKind {
        guard let raw, !raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return .none
        }
        let text = raw.lowercased()
        if text == "unavailable" || text == "—" {
            return .none
        }
        if text.contains("location permission") { return .locationPermission }
        if text.contains("location unavailable") { return .locationUnavailable }
        if text.contains("camera permission") { return .cameraPermission }
        if text.contains("camera unavailable") { return .cameraUnavailable }
        if text.contains("no wall in gps") {
            return .noWall
        }
        if text.contains("network")
            || text.contains("nsurl")
            || text.contains("offline")
            || text.contains("timed out")
            || text.contains("timeout")
            || text.contains("-1001")
            || text.contains("-1009")
        {
            return .network
        }
        if text.contains("http")
            || text.contains("integrity")
            || text.contains("install")
            || text.contains("download")
            || text.contains("storage")
            || text.contains("加载失败")
        {
            return .package
        }
        return .failed
    }

    static func hint(state: ScanLoadingState, facts: ScanLoadingFacts, now: TimeInterval) -> ScanHintKind {
        let classified = classifiedError(facts.lastError)
        if classified != .none, state.identify != .success {
            return classified
        }
        if state.identify == .pending,
           now - state.attemptStartedAt >= ScanLoadingMotion.longWaitSeconds,
           classified == .none
        {
            return .aimAtWall
        }
        return .none
    }

    static func hintText(_ kind: ScanHintKind) -> String? {
        switch kind {
        case .none: return nil
        case .aimAtWall: return "请对准岩壁重新扫描"
        case .locationPermission: return "请在设置中允许 CragPal 使用定位"
        case .locationUnavailable: return "暂时无法获取位置，请移至开阔处重试"
        case .cameraPermission: return "请在设置中允许 CragPal 使用相机"
        case .cameraUnavailable: return "相机暂时不可用，请重试"
        case .network: return "网络异常，请稍后重试"
        case .package: return "路线包加载失败"
        case .noWall: return "附近没有可扫描的岩壁"
        case .failed: return "扫描失败"
        }
    }
}
