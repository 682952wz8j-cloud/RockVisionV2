import ARKit
import Combine
import Foundation
import os

protocol ARFrameConsumer: AnyObject {
    func consumeARFrame(_ frame: ARFrame)
}

/// Isolated ARKit session owner for Gate 0.
///
/// May create, run, pause, and publish frame / tracking facts.
/// Must not localize a wall, read GPS, align coordinates, or render routes.
final class ARSessionHost: NSObject, ObservableObject, ARSessionDelegate {
    let session = ARSession()

    @Published private(set) var snapshot = ARSessionSnapshot()

    /// Optional OpenCV (or later) consumer. Host does not import OpenCV.
    weak var frameConsumer: ARFrameConsumer?

    private var isRunning = false
    private let lock = NSLock()
    private let log = Logger(subsystem: "com.rockvision.v2", category: "ARSessionHost")
    private var lastLoggedFrameCount = 0

    override init() {
        super.init()
        session.delegate = self
        session.delegateQueue = DispatchQueue(label: "com.rockvision.v2.arsession", qos: .userInteractive)
    }

    func start() {
        lock.lock()
        defer { lock.unlock() }
        guard !isRunning else { return }
        guard ARWorldTrackingConfiguration.isSupported else {
            publish { snapshot in
                snapshot.trackingState = "notAvailable (world tracking unsupported)"
            }
            return
        }
        let configuration = ARWorldTrackingConfiguration()
        configuration.worldAlignment = .gravity
        configuration.planeDetection = []
        session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
        isRunning = true
        log.info("ARSession started with ARWorldTrackingConfiguration")
        print("ARSessionHost: ARSession started with ARWorldTrackingConfiguration")
    }

    func pause() {
        lock.lock()
        defer { lock.unlock() }
        guard isRunning else { return }
        session.pause()
        isRunning = false
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        let width = CVPixelBufferGetWidth(frame.capturedImage)
        let height = CVPixelBufferGetHeight(frame.capturedImage)
        let tracking = Self.describe(frame.camera.trackingState)
        publish { snapshot in
            snapshot.frameCount += 1
            snapshot.cameraWidth = width
            snapshot.cameraHeight = height
            snapshot.trackingState = tracking
            let count = snapshot.frameCount
            if count == 1 || count - self.lastLoggedFrameCount >= 30 {
                self.lastLoggedFrameCount = count
                self.log.info("ARFrame \(count) camera=\(width)x\(height) tracking=\(tracking, privacy: .public)")
                print("ARSessionHost: ARFrame \(count) camera=\(width)x\(height) tracking=\(tracking)")
            }
        }
        frameConsumer?.consumeARFrame(frame)
    }

    func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        let tracking = Self.describe(camera.trackingState)
        publish { snapshot in
            snapshot.trackingState = tracking
        }
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        publish { snapshot in
            snapshot.trackingState = "failed: \(error.localizedDescription)"
        }
    }

    private func publish(_ mutate: @escaping (inout ARSessionSnapshot) -> Void) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            var next = self.snapshot
            mutate(&next)
            self.snapshot = next
        }
    }

    private static func describe(_ state: ARCamera.TrackingState) -> String {
        switch state {
        case .notAvailable:
            return "notAvailable"
        case .normal:
            return "normal"
        case .limited(let reason):
            switch reason {
            case .initializing:
                return "limited(initializing)"
            case .excessiveMotion:
                return "limited(excessiveMotion)"
            case .insufficientFeatures:
                return "limited(insufficientFeatures)"
            case .relocalizing:
                return "limited(relocalizing)"
            @unknown default:
                return "limited(unknown)"
            }
        }
    }
}

/// Facts the UI may observe. Localization stays `idle` until later gates.
struct ARSessionSnapshot: Equatable, Sendable {
    var localizationState: String = "idle"
    var trackingState: String = "—"
    var frameCount: Int = 0
    var cameraWidth: Int = 0
    var cameraHeight: Int = 0
}
