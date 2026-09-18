import CoreLocation
import Foundation

enum WallLocationError: LocalizedError {
    case permissionDenied
    case unavailable

    var errorDescription: String? {
        switch self {
        case .permissionDenied: return "location permission denied"
        case .unavailable: return "location unavailable"
        }
    }
}

/// App-layer GPS reader for WallCandidateSelector. Not a localizer.
@MainActor
final class WallLocationProvider: NSObject, @MainActor CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var continuation: CheckedContinuation<CLLocationCoordinate2D, Error>?
    private var timeout: Task<Void, Never>?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    func requestCoordinate() async throws -> CLLocationCoordinate2D {
        // Never replace a pending continuation. ProductionRuntime also serializes attempts.
        guard continuation == nil else { throw WallLocationError.unavailable }
        return try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            resolveAuthorization()
        }
    }

    private func resolveAuthorization() {
        guard continuation != nil else { return }
        switch manager.authorizationStatus {
        case .authorizedWhenInUse, .authorizedAlways:
            if let current = manager.location,
               current.horizontalAccuracy >= 0,
               abs(current.timestamp.timeIntervalSinceNow) < 60 {
                finish(.success(current.coordinate))
                return
            }
            // A location fix can fail silently indoors; always offer a retry after 20 seconds.
            if timeout == nil {
                timeout = Task { [weak self] in
                    do { try await Task.sleep(nanoseconds: 20_000_000_000) }
                    catch { return }
                    self?.finish(.failure(WallLocationError.unavailable))
                }
            }
            manager.requestLocation()
        case .denied, .restricted:
            finish(.failure(WallLocationError.permissionDenied))
        case .notDetermined:
            manager.requestWhenInUseAuthorization()
        @unknown default:
            finish(.failure(WallLocationError.unavailable))
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        resolveAuthorization()
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last, location.horizontalAccuracy >= 0 else {
            finish(.failure(WallLocationError.unavailable))
            return
        }
        finish(.success(location.coordinate))
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        finish(.failure((error as? CLError)?.code == .denied
            ? WallLocationError.permissionDenied : WallLocationError.unavailable))
    }

    private func finish(_ result: Result<CLLocationCoordinate2D, Error>) {
        let pending = continuation
        continuation = nil
        timeout?.cancel()
        timeout = nil
        pending?.resume(with: result)
    }
}
