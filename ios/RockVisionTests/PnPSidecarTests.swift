import XCTest
@testable import RockVision

final class PnPSidecarTests: XCTestCase {
    func testSidecarKeepsFullUniqueCorrespondencesAndCountsMissingXYZ() {
        let unique = [
            MatchRecord(queryIndex: 0, reason: .acceptedAfterRatio, point3DID: 10, distance: 0.2, secondDistance: 0.4, ratio: 0.5, referenceRow: 0),
            MatchRecord(queryIndex: 1, reason: .acceptedAfterRatio, point3DID: 11, distance: 0.3, secondDistance: 0.5, ratio: 0.6, referenceRow: 1),
            MatchRecord(queryIndex: 2, reason: .acceptedAfterRatio, point3DID: 12, distance: 0.25, secondDistance: 0.45, ratio: 0.55, referenceRow: 2),
            MatchRecord(queryIndex: 3, reason: .acceptedAfterRatio, point3DID: 10, distance: 0.1, secondDistance: 0.2, ratio: 0.4, referenceRow: 0)
        ]
        let database = ReferenceDatabase(
            descriptors: Data(count: 16),
            descriptorCount: 3,
            point3dIds: [10, 11, 12],
            rows: [
                LandmarkRow(index: 0, referenceImageID: 1, referenceImageName: "a.jpg", referenceKeypointX: 1, referenceKeypointY: 2, point3DID: 10, colmapXYZ: [1, 2, 3], wallLocalXYZ: [9, 9, 9]),
                LandmarkRow(index: 1, referenceImageID: 1, referenceImageName: "a.jpg", referenceKeypointX: 3, referenceKeypointY: 4, point3DID: 11, colmapXYZ: nil, wallLocalXYZ: [8, 8, 8]),
                LandmarkRow(index: 2, referenceImageID: 1, referenceImageName: "a.jpg", referenceKeypointX: 5, referenceKeypointY: 6, point3DID: 12, colmapXYZ: [Double.nan, 0, 0], wallLocalXYZ: [7, 7, 7])
            ],
            wallId: "wall_jiulongfeng_01",
            matcherHotPath: ["descriptor", "point3DID"],
            developmentFixtureOnly: true,
            notAWallPackage: true
        )
        let built = PnPSidecarBuilder.make(
            unique: unique,
            nativeX: [100, 200, 300, 400],
            nativeY: [110, 210, 310, 410],
            database: database
        )
        XCTAssertEqual(MatchingConfig.diagnosticMatchCap, 20)
        XCTAssertEqual(built.correspondences.count, 3)
        XCTAssertEqual(built.inputCorrespondenceCount, 1)
        XCTAssertEqual(built.xyzMissingRejected, 2)
        XCTAssertEqual(built.duplicatePoint3DRejected, 1)
        XCTAssertEqual(built.correspondences[0].queryXYNative, [100, 110])
        XCTAssertEqual(built.correspondences[0].colmapXYZ, [1, 2, 3])
        XCTAssertEqual(built.correspondences[0].queryCoordinateSpace, "nativeCapturedImage")
        XCTAssertNil(built.correspondences[1].colmapXYZ)
        XCTAssertNil(built.correspondences[2].colmapXYZ)
        XCTAssertFalse(built.correspondences.contains { $0.colmapXYZ == [9, 9, 9] })
        let ids = built.correspondences.map(\.point3DID)
        XCTAssertEqual(ids.count, Set(ids).count)
    }

    func testDiagnosticCapStaysTwentyWhileSidecarIsFull() {
        XCTAssertEqual(MatchingConfig.diagnosticMatchCap, 20)
        let unique = (0..<25).map { i in
            MatchRecord(
                queryIndex: i,
                reason: .acceptedAfterRatio,
                point3DID: Int64(i + 1),
                distance: 0.2,
                secondDistance: 0.5,
                ratio: 0.4,
                referenceRow: i
            )
        }
        let rows = (0..<25).map { i in
            LandmarkRow(
                index: i,
                referenceImageID: 1,
                referenceImageName: "a.jpg",
                referenceKeypointX: Double(i),
                referenceKeypointY: Double(i),
                point3DID: Int64(i + 1),
                colmapXYZ: [Double(i), 0, 1],
                wallLocalXYZ: nil
            )
        }
        let database = ReferenceDatabase(
            descriptors: Data(),
            descriptorCount: 25,
            point3dIds: rows.map(\.point3DID),
            rows: rows,
            wallId: "wall_jiulongfeng_01",
            matcherHotPath: ["descriptor", "point3DID"],
            developmentFixtureOnly: true,
            notAWallPackage: true
        )
        let sidecar = PnPSidecarBuilder.make(
            unique: unique,
            nativeX: (0..<25).map(Double.init),
            nativeY: (0..<25).map(Double.init),
            database: database
        )
        XCTAssertEqual(sidecar.correspondences.count, 25)
        XCTAssertEqual(sidecar.inputCorrespondenceCount, 25)
        XCTAssertEqual(sidecar.xyzMissingRejected, 0)
        XCTAssertEqual(min(unique.count, MatchingConfig.diagnosticMatchCap), 20)
    }
}
