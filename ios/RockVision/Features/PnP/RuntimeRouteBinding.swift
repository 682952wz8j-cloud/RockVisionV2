import CryptoKit
import Foundation

/// Shared Gate 5A / 5C frozen-polyline hash. Runtime and XCTest must use this.
enum FrozenRoutePolylineHash {
    static let expectedRouteTest01 = "ff6ff3ee58303634d369b919284ee8c827a80eb57a9403004614cda6194d2f99"
    static let expectedByteCount = 264
    static let expectedPointCount = 11

    static func canonicalBytes(_ points: [[Double]]) -> Data? {
        guard points.count == expectedPointCount,
              points.allSatisfy({ $0.count == 3 && $0.allSatisfy(\.isFinite) })
        else { return nil }
        var data = Data()
        data.reserveCapacity(expectedByteCount)
        for point in points {
            for coord in point {
                var bits = coord.bitPattern.littleEndian
                withUnsafeBytes(of: &bits) { data.append(contentsOf: $0) }
            }
        }
        guard data.count == expectedByteCount else { return nil }
        return data
    }

    static func sha256Hex(_ points: [[Double]]) -> String? {
        guard let bytes = canonicalBytes(points) else { return nil }
        return SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
    }

    static func verify(_ points: [[Double]], expectedHex: String) -> Bool {
        sha256Hex(points) == expectedHex
    }
}

/// A — verified frozen WallMetricMeters geometry. Persists independently of alignment.
struct VerifiedFrozenRoute: Equatable, Sendable {
    static let resourceName = "Gate5CRouteFixture"
    static let expectedRouteId = "route_test_01"
    static let expectedWallId = "wall_jiulongfeng_01"
    static let expectedCoordinateFrame = "WallMetricMeters"
    static let expectedProvenance = "IDENTITY_PROVEN"

    var routeId: String
    var wallId: String
    var coordinateFrame: String
    var provenance: String
    var dummyOriginExcluded: Bool
    var polylineSha256: String
    var wallMetricMeters: [[Double]]
    var hashVerified: Bool
    var developmentValidationOnly: Bool
    var sourceArtifact: String

    static func load(from url: URL) -> VerifiedFrozenRoute? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return load(from: data)
    }

    static func load(from data: Data) -> VerifiedFrozenRoute? {
        guard let payload = try? JSONDecoder().decode(FixtureFile.self, from: data) else {
            return nil
        }
        return verify(payload)
    }

    static func loadFromBundle(_ bundle: Bundle) -> VerifiedFrozenRoute? {
        guard let url = bundle.url(forResource: resourceName, withExtension: "json") else {
            return nil
        }
        return load(from: url)
    }

    static func loadCanonicalIngested(from url: URL) -> VerifiedFrozenRoute? {
        guard let data = try? Data(contentsOf: url),
              let payload = try? JSONDecoder().decode(CanonicalIngestedFile.self, from: data)
        else { return nil }
        guard payload.schemaVersion == "gate5a.ingested.route.1",
              payload.kind == "canonical_ingested_route",
              payload.routeId == expectedRouteId,
              payload.wallId == expectedWallId,
              payload.coordinateFrame == expectedCoordinateFrame,
              payload.provenance == expectedProvenance,
              payload.dummyOriginExcluded,
              payload.pointCount == FrozenRoutePolylineHash.expectedPointCount,
              payload.polyline.count == FrozenRoutePolylineHash.expectedPointCount,
              payload.polylineSha256 == FrozenRoutePolylineHash.expectedRouteTest01,
              !payload.polyline.contains(where: { $0 == [0.0, 0.0, 0.0] }),
              FrozenRoutePolylineHash.verify(payload.polyline, expectedHex: payload.polylineSha256)
        else { return nil }
        return VerifiedFrozenRoute(
            routeId: payload.routeId,
            wallId: payload.wallId,
            coordinateFrame: payload.coordinateFrame,
            provenance: payload.provenance,
            dummyOriginExcluded: payload.dummyOriginExcluded,
            polylineSha256: payload.polylineSha256,
            wallMetricMeters: payload.polyline,
            hashVerified: true,
            developmentValidationOnly: false,
            sourceArtifact: "validation/gate5a/gate5a_ingested_route_test_01.json"
        )
    }

    static func verify(_ payload: FixtureFile) -> VerifiedFrozenRoute? {
        guard payload.developmentValidationOnly,
              payload.notAProductionRoutePackage,
              payload.routeId == expectedRouteId,
              payload.wallId == expectedWallId,
              payload.coordinateFrame == expectedCoordinateFrame,
              payload.provenance == expectedProvenance,
              payload.dummyOriginExcluded,
              payload.pointCount == FrozenRoutePolylineHash.expectedPointCount,
              payload.polyline.count == FrozenRoutePolylineHash.expectedPointCount,
              payload.polylineSha256 == FrozenRoutePolylineHash.expectedRouteTest01,
              !payload.polyline.contains(where: { $0 == [0.0, 0.0, 0.0] })
        else { return nil }
        guard FrozenRoutePolylineHash.verify(payload.polyline, expectedHex: payload.polylineSha256)
        else { return nil }
        return VerifiedFrozenRoute(
            routeId: payload.routeId,
            wallId: payload.wallId,
            coordinateFrame: payload.coordinateFrame,
            provenance: payload.provenance,
            dummyOriginExcluded: payload.dummyOriginExcluded,
            polylineSha256: payload.polylineSha256,
            wallMetricMeters: payload.polyline,
            hashVerified: true,
            developmentValidationOnly: payload.developmentValidationOnly,
            sourceArtifact: payload.sourceArtifact
        )
    }

    struct CanonicalIngestedFile: Codable, Equatable, Sendable {
        var schemaVersion: String
        var kind: String
        var routeId: String
        var wallId: String
        var coordinateFrame: String
        var provenance: String
        var dummyOriginExcluded: Bool
        var pointCount: Int
        var polyline: [[Double]]
        var polylineSha256: String
    }

    struct FixtureFile: Codable, Equatable, Sendable {
        var schemaVersion: String
        var kind: String
        var developmentValidationOnly: Bool
        var notAProductionRoutePackage: Bool
        var sourceArtifact: String
        var routeId: String
        var wallId: String
        var coordinateFrame: String
        var provenance: String
        var dummyOriginExcluded: Bool
        var pointCount: Int
        var polyline: [[Double]]
        var polylineSha256: String
    }
}

/// B — disposable current ARWorld geometry. Function of A and CURRENT production T.
struct RuntimeRouteBinding: Equatable, Sendable {
    var routeId: String?
    var hashVerified: Bool
    var hasBoundRoute: Bool
    var routeARWorldPointCount: Int
    var routeARWorldPoints: [[Double]]
    var renderedRoute: Bool
    var reason: String?

    static let unbound = RuntimeRouteBinding(
        routeId: nil,
        hashVerified: false,
        hasBoundRoute: false,
        routeARWorldPointCount: 0,
        routeARWorldPoints: [],
        renderedRoute: false,
        reason: "unbound"
    )

    /// Binding predicate: frozenRouteHashVerified && currentAlignment.hasT_ARWorld_Wall.
    /// Does not construct T. Does not take Sim(3). Does not inspect localizationState.
    static func evaluate(
        verifiedRoute: VerifiedFrozenRoute?,
        alignment: AlignmentFrameResult
    ) -> RuntimeRouteBinding {
        guard let route = verifiedRoute, route.hashVerified else {
            return RuntimeRouteBinding(
                routeId: verifiedRoute?.routeId,
                hashVerified: false,
                hasBoundRoute: false,
                routeARWorldPointCount: 0,
                routeARWorldPoints: [],
                renderedRoute: false,
                reason: "hashUnverified"
            )
        }
        guard alignment.hasT_ARWorld_Wall, let transform = alignment.T_ARWorld_Wall else {
            return RuntimeRouteBinding(
                routeId: route.routeId,
                hashVerified: true,
                hasBoundRoute: false,
                routeARWorldPointCount: 0,
                routeARWorldPoints: [],
                renderedRoute: false,
                reason: "noCurrentT_ARWorld_Wall"
            )
        }
        do {
            var points: [[Double]] = []
            points.reserveCapacity(route.wallMetricMeters.count)
            for wallPoint in route.wallMetricMeters {
                let arWorld = try CoordinateTransforms.applyFrozenWallRoutePointToARWorld(
                    wallPointMeters: wallPoint,
                    T_ARWorld_Wall: transform
                )
                guard arWorld.count == 3, arWorld.allSatisfy(\.isFinite) else {
                    return failClosed(routeId: route.routeId, reason: "nonFinite")
                }
                points.append(arWorld)
            }
            guard points.count == FrozenRoutePolylineHash.expectedPointCount else {
                return failClosed(routeId: route.routeId, reason: "pointCount")
            }
            return RuntimeRouteBinding(
                routeId: route.routeId,
                hashVerified: true,
                hasBoundRoute: true,
                routeARWorldPointCount: points.count,
                routeARWorldPoints: points,
                renderedRoute: false,
                reason: nil
            )
        } catch {
            return failClosed(routeId: route.routeId, reason: "applyFailed")
        }
    }

    private static func failClosed(routeId: String?, reason: String) -> RuntimeRouteBinding {
        RuntimeRouteBinding(
            routeId: routeId,
            hashVerified: true,
            hasBoundRoute: false,
            routeARWorldPointCount: 0,
            routeARWorldPoints: [],
            renderedRoute: false,
            reason: reason
        )
    }
}
