import Foundation

struct AlignmentProvenance: Codable, Equatable, Sendable {
    var confirmedFrameID: UInt64
    var confirmedTimestamp: TimeInterval
    var T_opencvCam_colmap: [[Double]]
    var arFrameID: UInt64
    var arFrameTimestamp: TimeInterval
    var T_ARWorld_arkitCam: [[Double]]
}

struct AlignmentFrameResult: Codable, Equatable, Sendable {
    var status: String
    var reason: String?
    var hasT_ARWorld_Wall: Bool
    var T_ARWorld_Wall: [[Double]]?
    var productionAlignmentCalled: Bool
    var provenance: AlignmentProvenance?
    var cleared: Bool
    var renderedRoute: Bool
    var confirmedEqualsLatestRefined: Bool?

    static let none = AlignmentFrameResult(
        status: "none",
        reason: nil,
        hasT_ARWorld_Wall: false,
        T_ARWorld_Wall: nil,
        productionAlignmentCalled: false,
        provenance: nil,
        cleared: false,
        renderedRoute: false,
        confirmedEqualsLatestRefined: nil
    )

    static func aligned(
        transform: [[Double]],
        provenance: AlignmentProvenance,
        confirmedEqualsLatestRefined: Bool
    ) -> AlignmentFrameResult {
        AlignmentFrameResult(
            status: "aligned",
            reason: nil,
            hasT_ARWorld_Wall: true,
            T_ARWorld_Wall: transform,
            productionAlignmentCalled: true,
            provenance: provenance,
            cleared: false,
            renderedRoute: false,
            confirmedEqualsLatestRefined: confirmedEqualsLatestRefined
        )
    }
}

struct AlignmentStats: Codable, Equatable, Sendable {
    var generatedCount: Int = 0
    var firstGeneratedFrameID: UInt64?
    var clearedCount: Int = 0
    var lastClearReason: String?
    var renderedRoute: Bool = false
}

struct AlignmentRuntimeSnapshot: Equatable, Sendable {
    var status: String = "none"
    var frame: String = "—"
}

enum AlignmentSnapshot {
    static func make(_ result: AlignmentFrameResult) -> AlignmentRuntimeSnapshot {
        if result.hasT_ARWorld_Wall, let id = result.provenance?.confirmedFrameID {
            return AlignmentRuntimeSnapshot(status: "yes", frame: "\(id)")
        }
        return AlignmentRuntimeSnapshot(status: "none", frame: "—")
    }
}

/// Same-queue alignment after confirmation. No second timer / queue / backlog.
/// `T_ARWorld_Wall` is produced only by `CoordinateTransforms.productionAlignment`.
struct ProductionAlignmentRuntime {
    private(set) var current = AlignmentFrameResult.none
    private(set) var stats = AlignmentStats()

    mutating func reset() {
        if current.hasT_ARWorld_Wall {
            stats.clearedCount += 1
            stats.lastClearReason = "sessionReset"
        }
        current = .none
        stats = AlignmentStats()
    }

    mutating func update(
        confirmation: ConfirmationTick,
        pnp: PnPFrameResult,
        arkit: ARKitCameraTransformSidecar?,
        sim3: ValidatedSim3?
    ) -> AlignmentFrameResult {
        if confirmation.localizationState != ConfirmationConfig.localizationLocalized {
            return clear(reason: confirmation.resetReason ?? "notLocalized")
        }
        guard let confirmedT = confirmation.confirmedT_opencvCam_colmap,
              let confirmedID = confirmation.confirmedFrameID,
              let confirmedTS = confirmation.confirmedTimestamp,
              let pnpT = pnp.T_opencvCam_colmap,
              let pnpID = pnp.frameID,
              let pnpTS = pnp.timestamp
        else {
            return clear(reason: "missingConfirmedPose")
        }
        guard confirmation.confirmedEqualsLatestRefined == true,
              confirmedT == pnpT,
              confirmedID == pnpID,
              confirmedTS == pnpTS
        else {
            return clear(reason: "confirmedNotLastFrame")
        }
        guard let arkit, arkit.sameARFrame, arkit.layout == "columnMajor4x4",
              let arID = arkit.frameID,
              let arTS = arkit.timestamp
        else {
            return clear(reason: "missingARKitIdentity")
        }
        guard confirmedID == arID, arID == pnpID, arTS == pnpTS, arTS == confirmedTS else {
            return clear(reason: "provenanceMismatch")
        }
        guard let sim3 else {
            return clear(reason: "sim3Unavailable")
        }
        do {
            let T_ARWorld_arkitCam = try CoordinateTransforms.rowMajor(fromColumnMajor: arkit.columns)
            let transform = try CoordinateTransforms.productionAlignment(
                T_opencvCam_colmap: confirmedT,
                S_wall_colmap: sim3,
                T_ARWorld_arkitCam: T_ARWorld_arkitCam
            )
            let provenance = AlignmentProvenance(
                confirmedFrameID: confirmedID,
                confirmedTimestamp: confirmedTS,
                T_opencvCam_colmap: confirmedT,
                arFrameID: arID,
                arFrameTimestamp: arTS,
                T_ARWorld_arkitCam: T_ARWorld_arkitCam
            )
            let next = AlignmentFrameResult.aligned(
                transform: transform,
                provenance: provenance,
                confirmedEqualsLatestRefined: true
            )
            stats.generatedCount += 1
            if stats.firstGeneratedFrameID == nil {
                stats.firstGeneratedFrameID = confirmedID
            }
            current = next
            return next
        } catch CoordinateTransformError.sim3Unavailable {
            return clear(reason: "sim3Unavailable")
        } catch {
            return clear(reason: "productionAlignmentRefused")
        }
    }

    mutating func noteNoCandidate() -> AlignmentFrameResult {
        clear(reason: "noCandidate")
    }

    private mutating func clear(reason: String) -> AlignmentFrameResult {
        let had = current.hasT_ARWorld_Wall
        if had {
            stats.clearedCount += 1
            stats.lastClearReason = reason
        }
        current = AlignmentFrameResult(
            status: "none",
            reason: reason,
            hasT_ARWorld_Wall: false,
            T_ARWorld_Wall: nil,
            productionAlignmentCalled: false,
            provenance: nil,
            cleared: had,
            renderedRoute: false,
            confirmedEqualsLatestRefined: nil
        )
        return current
    }
}
