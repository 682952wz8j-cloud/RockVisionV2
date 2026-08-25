import Foundation

/// Field Test session-boundary bookkeeping. Does not change confirmation rules or thresholds.
///
/// Reset and the next field sample must be ordered on the existing OpenCV serial queue:
/// in-flight process blocks drain, then reset runs, then sampling may record.
/// Until a sample is actually recorded, a leftover ingest is discarded so the first
/// session sample cannot inherit a pre-reset window, streak, or counter.
struct FieldConfirmationSessionBarrier {
    private(set) var needsFreshEngine = false

    mutating func noteResetCompletedOnProcessingQueue() {
        needsFreshEngine = true
    }

    mutating func prepareCandidateIngest(_ engine: inout LocalizationConfirmation) {
        guard needsFreshEngine else { return }
        engine.reset()
    }

    mutating func noteFieldDecision(recorded: Bool, engine: inout LocalizationConfirmation) {
        if recorded {
            needsFreshEngine = false
            return
        }
        guard needsFreshEngine else { return }
        engine.reset()
    }
}
