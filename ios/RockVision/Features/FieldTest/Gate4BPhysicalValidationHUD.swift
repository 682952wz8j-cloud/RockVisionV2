import Foundation

/// Gate 4B on-device measurement HUD presentation only.
/// Does not own localization, alignment, session, or export state.
enum Gate4BPhysicalValidationHUD {
    static let title = "Gate 4B — Physical Validation"
    static let unfinishedMessage = "Unfinished session detected"

    struct StatusRow: Equatable {
        var title: String
        var value: String
    }

    struct Actions: Equatable {
        var showUnfinishedBanner: Bool
        var showResume: Bool
        var showNewSession: Bool
        var showStartMeasurement: Bool
        var showAbort: Bool
        var showShareResults: Bool
        var showCopySummary: Bool
        var showSceneChips: Bool
    }

    static let startMeasurementTitle = "Start Measurement"
    static let startMeasurementControllerMethod = "startOfficialNext"

    static let visibleTitles = [
        "Scene",
        "Tracking",
        "Localization",
        "Confirm",
        "Unique 3D",
        "PnP inliers",
        "PnP",
        "T_ARWorld_Wall",
        "Wall axes",
        "Markers",
        "Route",
        "Hash",
        "Bound",
        "Rendered",
        "Segments"
    ]

    static let mappedDiagnosticTitles = [
        "Processing",
        "Valid",
        "Matching",
        "Query kp",
        "Accepted",
        "Unique 3D",
        "SIFT",
        "Match",
        "Stage3",
        "PnP",
        "PnP in",
        "RANSAC inliers",
        "Inlier ratio",
        "Reproj",
        "C_wall",
        "obs-depth sanity"
    ]

    /// Historical Stage 3 rows that stay mapped but are not shown, except Unique 3D / PnP
    /// which are also promoted into the live evidence HUD.
    static let hiddenDiagnosticTitles = mappedDiagnosticTitles.filter {
        $0 != "Unique 3D" && $0 != "PnP"
    }

    static func visibleRows(
        scene: String,
        tracking: String,
        localization: String,
        confirmationWindow: String,
        alignment: String,
        wallAxes: String,
        wallMarkers: String,
        routeId: String? = nil,
        hashVerified: Bool = false,
        boundPointCount: Int = 0,
        rendered: Bool = false,
        visibleSegmentCount: Int = 0,
        matching: MatchingRuntimeSnapshot = MatchingRuntimeSnapshot(),
        pnp: PnPRuntimeSnapshot = PnPRuntimeSnapshot()
    ) -> [StatusRow] {
        let evidence = stage3EvidenceRows(matching: matching, pnp: pnp)
        return [
            StatusRow(title: "Scene", value: scene),
            StatusRow(title: "Tracking", value: tracking),
            StatusRow(title: "Localization", value: localization),
            StatusRow(title: "Confirm", value: confirmationWindow)
        ] + evidence + [
            StatusRow(title: "T_ARWorld_Wall", value: wallTransformLabel(alignment)),
            StatusRow(title: "Wall axes", value: axesLabel(wallAxes)),
            StatusRow(title: "Markers", value: wallMarkers),
            StatusRow(title: "Route", value: routeId ?? "—"),
            StatusRow(title: "Hash", value: hashVerified ? "OK" : "FAIL"),
            StatusRow(title: "Bound", value: "\(boundPointCount)"),
            StatusRow(title: "Rendered", value: rendered ? "YES" : "NO"),
            StatusRow(title: "Segments", value: "\(visibleSegmentCount)")
        ]
    }

    /// Minimum Stage 3 evidence rows. Source-agnostic; uses published snapshots only.
    static func stage3EvidenceRows(
        matching: MatchingRuntimeSnapshot,
        pnp: PnPRuntimeSnapshot
    ) -> [StatusRow] {
        [
            StatusRow(title: "Unique 3D", value: matching.acceptedUniquePoint3D),
            StatusRow(title: "PnP inliers", value: pnp.inliers),
            StatusRow(title: "PnP", value: pnp.status)
        ]
    }

    /// Full historical Stage 3 mapping. Unique 3D and PnP are also shown live; the rest stay hidden.
    static func diagnosticRows(
        processing: String,
        valid: String,
        matching: MatchingRuntimeSnapshot,
        sift: SIFTRuntimeSnapshot,
        pnp: PnPRuntimeSnapshot
    ) -> [StatusRow] {
        [
            StatusRow(title: "Processing", value: processing),
            StatusRow(title: "Valid", value: valid),
            StatusRow(title: "Matching", value: matching.status),
            StatusRow(title: "Query kp", value: matching.queryKeypoints),
            StatusRow(title: "Accepted", value: matching.acceptedAfterRatio),
            StatusRow(title: "Unique 3D", value: matching.acceptedUniquePoint3D),
            StatusRow(title: "SIFT", value: latency(sift.siftMs)),
            StatusRow(title: "Match", value: latency(matching.matchingMs)),
            StatusRow(title: "Stage3", value: latency(matching.stage3Ms)),
            StatusRow(title: "PnP", value: pnp.status),
            StatusRow(title: "PnP in", value: pnp.inputCorr),
            StatusRow(title: "RANSAC inliers", value: pnp.inliers),
            StatusRow(title: "Inlier ratio", value: pnp.inlierRatio),
            StatusRow(title: "Reproj", value: pnp.reproj),
            StatusRow(title: "C_wall", value: pnp.cWall),
            StatusRow(title: "obs-depth sanity", value: pnp.obsDepth)
        ]
    }

    static func actions(
        hasResumableSession: Bool,
        phase: FieldTestPhase = .readyToStart(.A),
        canExport: Bool = false
    ) -> Actions {
        if hasResumableSession {
            return Actions(
                showUnfinishedBanner: true,
                showResume: true,
                showNewSession: true,
                showStartMeasurement: false,
                showAbort: false,
                showShareResults: false,
                showCopySummary: false,
                showSceneChips: false
            )
        }
        switch phase {
        case .readyToStart, .readyToStartNext:
            return Actions(
                showUnfinishedBanner: false,
                showResume: false,
                showNewSession: false,
                showStartMeasurement: true,
                showAbort: false,
                showShareResults: canExport,
                showCopySummary: false,
                showSceneChips: false
            )
        case .waitingTracking, .sampling:
            return Actions(
                showUnfinishedBanner: false,
                showResume: false,
                showNewSession: false,
                showStartMeasurement: false,
                showAbort: true,
                showShareResults: false,
                showCopySummary: false,
                showSceneChips: false
            )
        case .complete:
            return Actions(
                showUnfinishedBanner: false,
                showResume: false,
                showNewSession: true,
                showStartMeasurement: false,
                showAbort: false,
                showShareResults: true,
                showCopySummary: false,
                showSceneChips: false
            )
        case .idle:
            return Actions(
                showUnfinishedBanner: false,
                showResume: false,
                showNewSession: true,
                showStartMeasurement: false,
                showAbort: false,
                showShareResults: canExport,
                showCopySummary: false,
                showSceneChips: false
            )
        }
    }

    static func startMeasurementEnabled(
        canStartTest: Bool,
        storageReady: Bool,
        tracking: String,
        matchingStatus: String,
        presetLabel: String,
        processingLabel: String
    ) -> Bool {
        guard canStartTest else { return false }
        return FieldTestLaunchGate.blockReason(
            storageReady: storageReady,
            tracking: tracking,
            matchingStatus: matchingStatus,
            presetLabel: presetLabel,
            processingLabel: processingLabel
        ) == nil
    }

    static func wallTransformLabel(_ alignment: String) -> String {
        alignment.hasPrefix("yes") ? "valid" : "none"
    }

    static func axesLabel(_ wallAxes: String) -> String {
        wallAxes == "hidden" ? "hidden" : "visible"
    }

    private static func latency(_ value: String) -> String {
        value == "—" ? "—" : "\(value) ms"
    }
}
