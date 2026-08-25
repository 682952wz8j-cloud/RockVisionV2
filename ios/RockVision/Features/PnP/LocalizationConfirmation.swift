import Foundation

/// Named uncalibrated Gate 3E confirmation constants. Not calibration / not statistically optimized.
enum ConfirmationConfig {
    static let confirmWindow = 3
    static let adjacentRotationMaxDeg = 8.0
    static let adjacentCWallMaxMeters = 0.50
    static let adjacentRotationFlipGuardDeg = 90.0
    static let positiveDepthEpsilon = 1e-12
    static let localizationIdle = "idle"
    static let localizationConfirming = "confirming"
    static let localizationLocalized = "localized"
    static let poseName = "T_opencvCam_colmap"
}

struct AcceptedVisualCandidate: Equatable, Sendable {
    var frameID: UInt64
    var timestamp: TimeInterval?
    var rotationMatrix: [[Double]]
    var C_colmap: [Double]
    var C_wall: [Double]
    var T_opencvCam_colmap: [[Double]]
    var tvecRefined: [Double]
    var rvecRefined: [Double]
}

struct ConfirmationTick: Codable, Equatable, Sendable {
    var localizationState: String
    var windowCount: Int
    var accepted: Bool
    var resetReason: String?
    var adjacentRotationDeg: Double?
    var adjacentCWallMeters: Double?
    var confirmedT_opencvCam_colmap: [[Double]]?
    var confirmedFrameID: UInt64?
    var confirmedTimestamp: TimeInterval?
    var currentFrameID: UInt64?
    var currentTimestamp: TimeInterval?
    var confirmedEqualsLatestRefined: Bool?
    var enteredLocalized: Bool
    var lostLocalized: Bool
    var restartedFromBreakingFrame: Bool
    var windowFrameIDs: [UInt64]
    var hasT_ARWorld_Wall: Bool
    var usedARKitInConfirmation: Bool
    var usedGPSInConfirmation: Bool
    var usedPreviousPosePnPPrior: Bool
}

struct ConfirmationStats: Codable, Equatable, Sendable {
    var pnpEvaluations: Int = 0
    var qualifiedCount: Int = 0
    var unqualifiedCount: Int = 0
    var confirmationAttemptCount: Int = 0
    var localizedEntryCount: Int = 0
    var longestValidStreak: Int = 0
    var currentStreak: Int = 0
    var resetCount: Int = 0
    var resetUnqualified: Int = 0
    var resetAdjacentRotation: Int = 0
    var resetAdjacentCWall: Int = 0
    var resetPositiveDepth: Int = 0
    var resetNonFinite: Int = 0
    var resetAntiFlip: Int = 0
    var acceptedAfterFirstLocalized: Int = 0
    var localizedLossCount: Int = 0
    var firstLocalizedSequence: [UInt64]? = nil
    var confirmedAlwaysEqualsLatestRefined: Bool = true
}

struct ConfirmationRuntimeSnapshot: Equatable, Sendable {
    var localization: String = ConfirmationConfig.localizationIdle
    var window: String = "0/\(ConfirmationConfig.confirmWindow)"
    var lastReset: String = "—"
}

/// Same-queue confirmation. Consumes qualified same-frame PnP candidates only.
struct LocalizationConfirmation {
    private var window: [AcceptedVisualCandidate] = []
    private var state: String = ConfirmationConfig.localizationIdle
    private(set) var stats = ConfirmationStats()
    private var hasEverLocalized = false

    var localizationState: String { state }

    mutating func reset() {
        self = LocalizationConfirmation()
    }

    mutating func ingest(_ pnp: PnPFrameResult) -> ConfirmationTick {
        stats.pnpEvaluations += 1
        if pnp.candidateQualified {
            stats.qualifiedCount += 1
        } else {
            stats.unqualifiedCount += 1
        }
        let previousState = state
        let eligibility = Self.eligibility(pnp)
        if !eligibility.ok {
            return resetToIdle(
                reason: eligibility.reason,
                previousState: previousState,
                currentFrameID: pnp.frameID,
                currentTimestamp: pnp.timestamp
            )
        }
        stats.confirmationAttemptCount += 1
        guard let incoming = try? Self.accepted(from: pnp) else {
            return resetToIdle(
                reason: "non-finite",
                previousState: previousState,
                currentFrameID: pnp.frameID,
                currentTimestamp: pnp.timestamp
            )
        }
        guard let previous = window.last else {
            window = [incoming]
            state = ConfirmationConfig.localizationConfirming
            stats.currentStreak = 1
            stats.longestValidStreak = max(stats.longestValidStreak, 1)
            return tick(
                accepted: true,
                previousState: previousState,
                resetReason: nil,
                adjacentRotation: nil,
                adjacentCWall: nil,
                restarted: false
            )
        }
        let rotationDeg = PnPGeometry.rotationAngleDegrees(
            estimated: incoming.rotationMatrix,
            groundTruth: previous.rotationMatrix
        )
        let cWallDelta = PnPGeometry.l2(incoming.C_wall, previous.C_wall)
        if rotationDeg >= ConfirmationConfig.adjacentRotationFlipGuardDeg {
            return restart(with: incoming, reason: "anti-flip", previousState: previousState, rotationDeg: rotationDeg, cWallDelta: cWallDelta)
        }
        if rotationDeg >= ConfirmationConfig.adjacentRotationMaxDeg {
            return restart(with: incoming, reason: "adjacent rotation", previousState: previousState, rotationDeg: rotationDeg, cWallDelta: cWallDelta)
        }
        if cWallDelta >= ConfirmationConfig.adjacentCWallMaxMeters {
            return restart(with: incoming, reason: "adjacent C_wall", previousState: previousState, rotationDeg: rotationDeg, cWallDelta: cWallDelta)
        }
        window.append(incoming)
        if window.count > ConfirmationConfig.confirmWindow {
            window.removeFirst()
        }
        stats.currentStreak += 1
        stats.longestValidStreak = max(stats.longestValidStreak, stats.currentStreak)
        let entered = previousState != ConfirmationConfig.localizationLocalized
            && window.count >= ConfirmationConfig.confirmWindow
        if window.count >= ConfirmationConfig.confirmWindow {
            if entered {
                stats.localizedEntryCount += 1
                if stats.firstLocalizedSequence == nil {
                    stats.firstLocalizedSequence = window.map(\.frameID)
                }
            } else if hasEverLocalized {
                stats.acceptedAfterFirstLocalized += 1
            }
            state = ConfirmationConfig.localizationLocalized
            hasEverLocalized = true
        } else {
            state = ConfirmationConfig.localizationConfirming
        }
        return tick(
            accepted: true,
            previousState: previousState,
            resetReason: nil,
            adjacentRotation: rotationDeg,
            adjacentCWall: cWallDelta,
            restarted: false,
            enteredLocalized: entered
        )
    }

    private mutating func resetToIdle(
        reason: String,
        previousState: String,
        currentFrameID: UInt64?,
        currentTimestamp: TimeInterval?
    ) -> ConfirmationTick {
        let hadChain = !window.isEmpty || previousState != ConfirmationConfig.localizationIdle
        let lost = previousState == ConfirmationConfig.localizationLocalized
        window = []
        state = ConfirmationConfig.localizationIdle
        stats.currentStreak = 0
        if hadChain {
            stats.resetCount += 1
            tallyReset(reason)
        }
        if lost {
            stats.localizedLossCount += 1
        }
        return tick(
            accepted: false,
            previousState: previousState,
            resetReason: hadChain ? reason : nil,
            adjacentRotation: nil,
            adjacentCWall: nil,
            restarted: false,
            lostLocalized: lost,
            currentFrameID: currentFrameID,
            currentTimestamp: currentTimestamp
        )
    }

    private mutating func restart(
        with incoming: AcceptedVisualCandidate,
        reason: String,
        previousState: String,
        rotationDeg: Double,
        cWallDelta: Double
    ) -> ConfirmationTick {
        let lost = previousState == ConfirmationConfig.localizationLocalized
        stats.resetCount += 1
        tallyReset(reason)
        if lost {
            stats.localizedLossCount += 1
        }
        window = [incoming]
        state = ConfirmationConfig.localizationConfirming
        stats.currentStreak = 1
        stats.longestValidStreak = max(stats.longestValidStreak, 1)
        return tick(
            accepted: true,
            previousState: previousState,
            resetReason: reason,
            adjacentRotation: rotationDeg,
            adjacentCWall: cWallDelta,
            restarted: true,
            lostLocalized: lost
        )
    }

    private mutating func tallyReset(_ reason: String) {
        switch reason {
        case "unqualified": stats.resetUnqualified += 1
        case "adjacent rotation": stats.resetAdjacentRotation += 1
        case "adjacent C_wall": stats.resetAdjacentCWall += 1
        case "positive depth": stats.resetPositiveDepth += 1
        case "non-finite": stats.resetNonFinite += 1
        case "anti-flip": stats.resetAntiFlip += 1
        default: break
        }
    }

    private mutating func tick(
        accepted: Bool,
        previousState: String,
        resetReason: String?,
        adjacentRotation: Double?,
        adjacentCWall: Double?,
        restarted: Bool,
        enteredLocalized: Bool = false,
        lostLocalized: Bool = false,
        currentFrameID: UInt64? = nil,
        currentTimestamp: TimeInterval? = nil
    ) -> ConfirmationTick {
        let current = window.last
        let confirmed = state == ConfirmationConfig.localizationLocalized ? current : nil
        let equalsLatest: Bool?
        if let confirmed, let last = window.last {
            equalsLatest = confirmed.T_opencvCam_colmap == last.T_opencvCam_colmap
                && confirmed.frameID == last.frameID
            if equalsLatest == false {
                stats.confirmedAlwaysEqualsLatestRefined = false
            }
        } else {
            equalsLatest = nil
        }
        _ = previousState
        return ConfirmationTick(
            localizationState: state,
            windowCount: window.count,
            accepted: accepted,
            resetReason: resetReason,
            adjacentRotationDeg: adjacentRotation,
            adjacentCWallMeters: adjacentCWall,
            confirmedT_opencvCam_colmap: confirmed?.T_opencvCam_colmap,
            confirmedFrameID: confirmed?.frameID,
            confirmedTimestamp: confirmed?.timestamp,
            currentFrameID: currentFrameID ?? current?.frameID,
            currentTimestamp: currentTimestamp ?? current?.timestamp,
            confirmedEqualsLatestRefined: equalsLatest,
            enteredLocalized: enteredLocalized,
            lostLocalized: lostLocalized,
            restartedFromBreakingFrame: restarted,
            windowFrameIDs: window.map(\.frameID),
            hasT_ARWorld_Wall: false,
            usedARKitInConfirmation: false,
            usedGPSInConfirmation: false,
            usedPreviousPosePnPPrior: false
        )
    }

    private static func eligibility(_ pnp: PnPFrameResult) -> (ok: Bool, reason: String) {
        if !pnp.candidateQualified {
            return (false, "unqualified")
        }
        guard let pdr = pnp.positiveDepthRatioRefined, abs(pdr - 1.0) <= ConfirmationConfig.positiveDepthEpsilon else {
            return (false, "positive depth")
        }
        if (try? accepted(from: pnp)) == nil {
            return (false, "non-finite")
        }
        return (true, "ok")
    }

    private static func accepted(from pnp: PnPFrameResult) throws -> AcceptedVisualCandidate {
        guard let frameID = pnp.frameID,
              PnPGeometry.isFiniteMatrix(pnp.rotationMatrix, rows: 3, cols: 3),
              PnPGeometry.isFiniteVec(pnp.C_colmap, count: 3),
              PnPGeometry.isFiniteVec(pnp.C_wall, count: 3),
              PnPGeometry.isFiniteMatrix(pnp.T_opencvCam_colmap, rows: 4, cols: 4),
              PnPGeometry.isFiniteVec(pnp.tvecRefined, count: 3),
              PnPGeometry.isFiniteVec(pnp.rvecRefined, count: 3),
              let rotation = pnp.rotationMatrix,
              let cColmap = pnp.C_colmap,
              let cWall = pnp.C_wall,
              let transform = pnp.T_opencvCam_colmap,
              let tvec = pnp.tvecRefined,
              let rvec = pnp.rvecRefined
        else {
            throw ConfirmationEligibilityError.nonFinite
        }
        return AcceptedVisualCandidate(
            frameID: frameID,
            timestamp: pnp.timestamp,
            rotationMatrix: rotation,
            C_colmap: cColmap,
            C_wall: cWall,
            T_opencvCam_colmap: transform,
            tvecRefined: tvec,
            rvecRefined: rvec
        )
    }
}

private enum ConfirmationEligibilityError: Error {
    case nonFinite
}

struct ARKitCameraTransformSidecar: Codable, Equatable, Sendable {
    var sameARFrame: Bool
    var layout: String
    var columns: [[Double]]
    var frameID: UInt64?
    var timestamp: TimeInterval?
    var usedInPnP: Bool
    var usedInConfirmation: Bool
    var producesT_ARWorld_Wall: Bool

    static func capture(
        columnMajor4x4 columns: [[Double]],
        timestamp: TimeInterval? = nil
    ) -> ARKitCameraTransformSidecar {
        ARKitCameraTransformSidecar(
            sameARFrame: true,
            layout: "columnMajor4x4",
            columns: columns,
            frameID: nil,
            timestamp: timestamp,
            usedInPnP: false,
            usedInConfirmation: false,
            producesT_ARWorld_Wall: false
        )
    }

    func stamped(frameID: UInt64, timestamp: TimeInterval) -> ARKitCameraTransformSidecar {
        var next = self
        next.frameID = frameID
        next.timestamp = timestamp
        return next
    }
}

enum ConfirmationSnapshot {
    static func make(_ tick: ConfirmationTick) -> ConfirmationRuntimeSnapshot {
        ConfirmationRuntimeSnapshot(
            localization: tick.localizationState,
            window: "\(tick.windowCount)/\(ConfirmationConfig.confirmWindow)",
            lastReset: tick.resetReason ?? "—"
        )
    }
}
