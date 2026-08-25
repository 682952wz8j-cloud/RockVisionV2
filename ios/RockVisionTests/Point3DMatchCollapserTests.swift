import CryptoKit
import XCTest
@testable import RockVision

final class Point3DMatchCollapserTests: XCTestCase {
    func testNamedConstants() {
        XCTAssertEqual(MatchingConfig.candidateK, 16)
        XCTAssertEqual(MatchingConfig.candidateKName, "candidateK")
        XCTAssertEqual(MatchingConfig.minDistinctPoint3DForRatio, 2)
        XCTAssertEqual(MatchingConfig.ratioThreshold, 0.8, accuracy: 1e-12)
        XCTAssertEqual(MatchingConfig.descriptorDim, 128)
        XCTAssertEqual(MatchingConfig.diagnosticMatchCap, 20)
    }

    func testDuplicateDescriptorsSamePoint3DRatioUsesDistinctIds() throws {
        let k = MatchingConfig.candidateK
        let indices = [padKNN([0, 1, 2], k: k)]
        let distances = [padDist([0.40, 0.41, 0.60], k: k)]
        let result = try Point3DMatcher.match(
            queryCount: 1,
            knnIndices: indices,
            knnDistances: distances,
            point3dIds: [100, 100, 200]
        )
        XCTAssertEqual(result.acceptedAfterRatio.count, 1)
        XCTAssertEqual(result.acceptedAfterRatio[0].point3DID, 100)
        XCTAssertEqual(result.acceptedAfterRatio[0].ratio ?? -1, 0.40 / 0.60, accuracy: 1e-9)
        XCTAssertLessThan(result.acceptedAfterRatio[0].ratio ?? 1, MatchingConfig.ratioThreshold)
        XCTAssertGreaterThan(0.40 / 0.41, MatchingConfig.ratioThreshold)
    }

    func testOnlyOneDistinctPoint3DIsInsufficient() throws {
        let k = MatchingConfig.candidateK
        let result = try Point3DMatcher.match(
            queryCount: 1,
            knnIndices: [padKNN([0, 1], k: k)],
            knnDistances: [padDist([0.1, 0.2], k: k)],
            point3dIds: [100, 100]
        )
        XCTAssertEqual(result.insufficientDistinctPoint3D, 1)
        XCTAssertEqual(result.acceptedAfterRatio.count, 0)
        XCTAssertEqual(result.records[0].reason, .insufficientDistinctPoint3D)
        XCTAssertEqual(MatchingConfig.minDistinctPoint3DForRatio, 2)
    }

    func testRatioThresholdIsStrictLessThan0_8() throws {
        let k = MatchingConfig.candidateK
        let result = try Point3DMatcher.match(
            queryCount: 1,
            knnIndices: [padKNN([0, 1], k: k)],
            knnDistances: [padDist([0.8, 1.0], k: k)],
            point3dIds: [1, 2]
        )
        XCTAssertEqual(result.records[0].reason, .ratioRejected)
        XCTAssertEqual(result.acceptedAfterRatio.count, 0)
        XCTAssertEqual(result.records[0].ratio ?? -1, 0.8, accuracy: 1e-12)
    }

    func testRatioJustBelow0_8IsAccepted() throws {
        let k = MatchingConfig.candidateK
        let result = try Point3DMatcher.match(
            queryCount: 1,
            knnIndices: [padKNN([0, 1], k: k)],
            knnDistances: [padDist([0.79, 1.0], k: k)],
            point3dIds: [1, 2]
        )
        XCTAssertEqual(result.records[0].reason, .acceptedAfterRatio)
        XCTAssertEqual(result.acceptedAfterRatio.count, 1)
    }

    func testDuplicateQuerySamePoint3DKeepsOne() throws {
        let k = MatchingConfig.candidateK
        let result = try Point3DMatcher.match(
            queryCount: 2,
            knnIndices: [padKNN([0, 1], k: k), padKNN([0, 1], k: k)],
            knnDistances: [padDist([0.10, 0.50], k: k), padDist([0.20, 0.50], k: k)],
            point3dIds: [9, 8]
        )
        XCTAssertEqual(result.acceptedAfterRatio.count, 2)
        XCTAssertEqual(result.acceptedUniquePoint3D.count, 1)
        XCTAssertEqual(result.acceptedUniquePoint3D[0].queryIndex, 0)
        XCTAssertEqual(result.duplicatePoint3DRejected, 1)
    }

    func testTieBreakUsesSmallerQueryIndex() {
        let a = MatchRecord(queryIndex: 5, reason: .acceptedAfterRatio, point3DID: 7, distance: 0.2, ratio: 0.4)
        let b = MatchRecord(queryIndex: 1, reason: .acceptedAfterRatio, point3DID: 7, distance: 0.2, ratio: 0.4)
        let (kept, rejected) = Point3DMatchCollapser.uniquePoint3DDedup([a, b])
        XCTAssertEqual(rejected, 1)
        XCTAssertEqual(kept[0].queryIndex, 1)
    }

    func testEmptyQueryAndReferenceDoNotCrash() throws {
        let emptyQuery = try Point3DMatcher.match(
            queryCount: 0,
            knnIndices: [],
            knnDistances: [],
            point3dIds: [1]
        )
        XCTAssertTrue(emptyQuery.emptyQuery)
        XCTAssertEqual(emptyQuery.records.count, 0)

        let emptyRef = try Point3DMatcher.match(
            queryCount: 1,
            knnIndices: [Array(repeating: -1, count: MatchingConfig.candidateK)],
            knnDistances: [Array(repeating: Double.infinity, count: MatchingConfig.candidateK)],
            point3dIds: [],
            emptyReference: true
        )
        XCTAssertTrue(emptyRef.emptyReference)
        XCTAssertEqual(emptyRef.records[0].reason, .insufficientDistinctPoint3D)
    }

    func testNonFiniteQueryRejected() throws {
        let k = MatchingConfig.candidateK
        let result = try Point3DMatcher.match(
            queryCount: 1,
            queryFinite: [false],
            knnIndices: [padKNN([0], k: k)],
            knnDistances: [padDist([0.1], k: k)],
            point3dIds: [1]
        )
        XCTAssertEqual(result.records[0].reason, .nonFiniteDescriptor)
        XCTAssertEqual(result.acceptedAfterRatio.count, 0)
    }

    func testCandidateKIs16() throws {
        XCTAssertEqual(MatchingConfig.candidateK, 16)
        var indices = Array(0..<16)
        var distances = (0..<16).map { Double($0) * 0.01 + 0.05 }
        let result = try Point3DMatcher.match(
            queryCount: 1,
            knnIndices: [indices],
            knnDistances: [distances],
            point3dIds: Array(1...20).map(Int64.init)
        )
        XCTAssertEqual(result.records[0].rawDescriptorCandidates, 16)
        XCTAssertEqual(indices.count, 16)
    }

    func testCandidateKTruncatedWhenDistinctBelowMin() throws {
        let indices = Array(repeating: 0, count: 16)
        let distances = (0..<16).map { 0.1 + Double($0) * 0.01 }
        let result = try Point3DMatcher.match(
            queryCount: 1,
            knnIndices: [indices],
            knnDistances: [distances],
            point3dIds: [42, 42]
        )
        XCTAssertTrue(result.records[0].candidateKTruncatedDistinct)
        XCTAssertEqual(result.candidateKTruncatedQueries, 1)
        XCTAssertEqual(result.records[0].reason, .insufficientDistinctPoint3D)
    }

    func testBadDescriptorDimensionThrows() {
        XCTAssertThrowsError(
            try Point3DMatcher.match(
                queryCount: 1,
                descriptorDim: 64,
                knnIndices: [[0]],
                knnDistances: [[0.1]],
                point3dIds: [1]
            )
        ) { error in
            XCTAssertEqual(error as? MatchingError, .badDescriptorDimension(64))
        }
    }

    func testRVS1RoundtripFloat32Dim128() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("rvs1-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let matrix = packDescriptors([desc(1, 2), desc(3, 4)])
        let url = dir.appendingPathComponent("descriptors.bin")
        try RVS1Artifact.write(descriptors: matrix, to: url)
        let back = try RVS1Artifact.read(from: url)
        XCTAssertEqual(back.count, 2)
        XCTAssertEqual(back.dim, 128)
        XCTAssertEqual(back.data, matrix)
        let header = try Data(contentsOf: url).prefix(20)
        XCTAssertEqual(header.prefix(4), MatchingConfig.rvs1Magic)
        XCTAssertEqual(readU32(header, 4), 1)
        XCTAssertEqual(readU32(header, 8), 1)
        XCTAssertEqual(readU32(header, 12), 128)
        XCTAssertEqual(readU32(header, 16), 2)
    }

    func testMalformedMagicAndDim() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("rvs1-bad-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        var bad = Data("XXXX".utf8)
        bad.append(contentsOf: [1, 0, 0, 0, 1, 0, 0, 0, 128, 0, 0, 0, 0, 0, 0, 0])
        XCTAssertThrowsError(try RVS1Artifact.read(data: bad)) { error in
            XCTAssertEqual(error as? MatchingError, .badMagic)
        }
        XCTAssertThrowsError(try RVS1Artifact.write(descriptors: Data(count: 64 * 4), dim: 64, to: dir.appendingPathComponent("d.bin"))) { error in
            XCTAssertEqual(error as? MatchingError, .badDescriptorDimension(64))
        }
        var wrongDim = Data("RVS1".utf8)
        func append(_ value: UInt32) {
            var le = value.littleEndian
            Swift.withUnsafeBytes(of: &le) { wrongDim.append(contentsOf: $0) }
        }
        append(1); append(1); append(64); append(0)
        XCTAssertThrowsError(try RVS1Artifact.read(data: wrongDim)) { error in
            XCTAssertEqual(error as? MatchingError, .badDescriptorDimension(64))
        }
    }

    func testNonFiniteDescriptorsRefused() {
        var row = [Float](repeating: 0, count: 128)
        row[3] = .infinity
        let data = row.withUnsafeBufferPointer { Data(buffer: $0) }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("inf-\(UUID().uuidString).bin")
        XCTAssertThrowsError(try RVS1Artifact.write(descriptors: data, to: url)) { error in
            XCTAssertEqual(error as? MatchingError, .nonFiniteDescriptors)
        }
    }

    func testFreezeAndProvenanceLookup() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("baseline-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let descriptors = packDescriptors([desc(1)])
        try RVS1Artifact.write(descriptors: descriptors, to: dir.appendingPathComponent("descriptors.bin"))
        let landmarks: [String: Any] = [
            "schema": 1,
            "schemaId": "reference_matching.baseline_2px.1",
            "wallId": "wall_fixture",
            "developmentFixtureOnly": true,
            "notAWallPackage": true,
            "matcherHotPath": ["descriptor", "point3DID"],
            "landmarks": [[
                "index": 0,
                "referenceImageID": 4,
                "referenceImageName": "DJI_TEST.JPG",
                "referenceKeypointX": 12.0,
                "referenceKeypointY": 34.0,
                "point3DID": 99,
                "colmapXYZ": [1.0, 2.0, 3.0],
                "wallLocalXYZ": [4.0, 5.0, 6.0],
            ]],
        ]
        let json = try JSONSerialization.data(withJSONObject: landmarks)
        try json.write(to: dir.appendingPathComponent("landmarks.json"))
        let db = try ReferenceDatabase.load(
            descriptorsURL: dir.appendingPathComponent("descriptors.bin"),
            landmarksURL: dir.appendingPathComponent("landmarks.json")
        )
        XCTAssertEqual(db.descriptorCount, 1)
        XCTAssertEqual(db.point3dIds[0], 99)
        XCTAssertEqual(db.matcherHotPath, ["descriptor", "point3DID"])
        XCTAssertTrue(db.developmentFixtureOnly)
        XCTAssertTrue(db.notAWallPackage)
        let record = MatchRecord(
            queryIndex: 0,
            reason: .acceptedAfterRatio,
            point3DID: 99,
            distance: 0.1,
            ratio: 0.2,
            referenceRow: 0
        )
        let prov = try XCTUnwrap(db.provenance(for: record))
        XCTAssertEqual(prov.referenceImageName, "DJI_TEST.JPG")
        XCTAssertEqual(prov.referenceImageID, 4)
        XCTAssertEqual(prov.referenceXY, [12.0, 34.0])
        XCTAssertEqual(SHA256.hash(data: descriptors).description.count > 0, true)
    }

    func testOpenCVBFMatcherKEquals16AndGroupingStillInSwift() throws {
        var referenceRows: [Data] = []
        for i in 0..<20 {
            referenceRows.append(desc(Float(i)))
        }
        let query = packDescriptors([desc(0)])
        let reference = packDescriptors(referenceRows)
        let knn = OpenCVBridge.knnMatchL2(
            queryDescriptors: query,
            referenceDescriptors: reference,
            descriptorDim: Int32(MatchingConfig.descriptorDim),
            k: Int32(MatchingConfig.candidateK)
        )
        XCTAssertTrue(knn.ok)
        XCTAssertEqual(knn.queryCount, 1)
        XCTAssertEqual(knn.k, 16)
        let (indices, distances) = MatchingKNN.unpack(
            indicesInt32: knn.indicesInt32,
            distancesFloat32: knn.distancesFloat32,
            queryCount: 1,
            k: 16
        )
        XCTAssertEqual(indices[0].filter { $0 >= 0 }.count, 16)
        let point3d = Array(1...20).map(Int64.init)
        let result = try Point3DMatcher.match(
            queryCount: 1,
            knnIndices: indices,
            knnDistances: distances,
            point3dIds: point3d
        )
        XCTAssertEqual(result.records[0].rawDescriptorCandidates, 16)
        XCTAssertGreaterThanOrEqual(result.records[0].uniquePoint3DCandidates, 2)
    }

    func testOpenCVKNNEmptyDoesNotCrash() {
        let empty = Data()
        let knn = OpenCVBridge.knnMatchL2(
            queryDescriptors: empty,
            referenceDescriptors: packDescriptors([desc(1)]),
            descriptorDim: 128,
            k: 16
        )
        XCTAssertTrue(knn.ok)
        XCTAssertEqual(knn.queryCount, 0)
        let knnRef = OpenCVBridge.knnMatchL2(
            queryDescriptors: packDescriptors([desc(1)]),
            referenceDescriptors: empty,
            descriptorDim: 128,
            k: 16
        )
        XCTAssertTrue(knnRef.ok)
        XCTAssertEqual(knnRef.queryCount, 1)
        let (indices, _) = MatchingKNN.unpack(
            indicesInt32: knnRef.indicesInt32,
            distancesFloat32: knnRef.distancesFloat32,
            queryCount: 1,
            k: 16
        )
        XCTAssertTrue(indices[0].allSatisfy { $0 < 0 })
    }

    func testSIFTResultRetainsRowMajorFloat32Descriptors() {
        let image = makeTexturedGray(width: 96, height: 72)
        let result = image.withUnsafeBytes { raw in
            OpenCVBridge.extractSIFT(
                fromGrayBytes: raw.bindMemory(to: UInt8.self).baseAddress,
                width: 96,
                height: 72,
                stride: 96,
                targetWidth: 0,
                targetHeight: 0,
                overlayCap: 0
            )
        }
        XCTAssertTrue(result.ok)
        XCTAssertGreaterThan(result.descriptorRows, 0)
        XCTAssertEqual(result.descriptorCols, 128)
        let data = result.descriptorData
        XCTAssertNotNil(data)
        XCTAssertEqual(data?.count, Int(result.descriptorRows) * 128 * 4)
    }

    func testRuntimeMatcherTinyDatabaseDoesNotUseSceneOrPose() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("runtime-match-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let descriptors = packDescriptors([desc(1), desc(0)])
        try RVS1Artifact.write(descriptors: descriptors, to: dir.appendingPathComponent("descriptors.bin"))
        let landmarks: [String: Any] = [
            "schema": 1,
            "wallId": "wall_fixture",
            "developmentFixtureOnly": true,
            "notAWallPackage": true,
            "matcherHotPath": ["descriptor", "point3DID"],
            "landmarks": [
                [
                    "index": 0,
                    "referenceImageID": 4,
                    "referenceImageName": "DJI_TEST.JPG",
                    "referenceKeypointX": 12.0,
                    "referenceKeypointY": 34.0,
                    "point3DID": 100,
                ],
                [
                    "index": 1,
                    "referenceImageID": 5,
                    "referenceImageName": "OTHER.JPG",
                    "referenceKeypointX": 1.0,
                    "referenceKeypointY": 2.0,
                    "point3DID": 200,
                ],
            ],
        ]
        try JSONSerialization.data(withJSONObject: landmarks).write(to: dir.appendingPathComponent("landmarks.json"))
        let database = try ReferenceDatabase.load(
            descriptorsURL: dir.appendingPathComponent("descriptors.bin"),
            landmarksURL: dir.appendingPathComponent("landmarks.json")
        )
        let matched = RuntimeMatcher.match(
            queryDescriptors: packDescriptors([desc(1)]),
            descriptorRows: 1,
            descriptorCols: 128,
            descriptorsFinite: true,
            nativeX: [10],
            nativeY: [20],
            database: database,
            siftTotalMs: 40
        )
        XCTAssertEqual(matched.status, "active")
        XCTAssertEqual(matched.queryKeypoints, 1)
        XCTAssertGreaterThanOrEqual(matched.acceptedUniquePoint3D, 1)
        XCTAssertEqual(matched.diagnosticMatches.first?.queryXY, [10, 20])
        XCTAssertEqual(matched.diagnosticMatches.first?.referenceImageName, "DJI_TEST.JPG")
        XCTAssertGreaterThan(matched.stage3TotalMs, 40)
        XCTAssertEqual(matched.stage3TotalMs, 40 + matched.matchingLatencyMs, accuracy: 1e-6)

        let empty = RuntimeMatcher.match(
            queryDescriptors: Data(),
            descriptorRows: 0,
            descriptorCols: 128,
            descriptorsFinite: true,
            nativeX: [],
            nativeY: [],
            database: database,
            siftTotalMs: 1
        )
        XCTAssertEqual(empty.status, "active")
        XCTAssertEqual(empty.queryKeypoints, 0)
        XCTAssertEqual(empty.acceptedUniquePoint3D, 0)
    }

    private func padKNN(_ values: [Int], k: Int) -> [Int] {
        values + Array(repeating: -1, count: max(0, k - values.count))
    }

    private func padDist(_ values: [Double], k: Int) -> [Double] {
        values + Array(repeating: Double.infinity, count: max(0, k - values.count))
    }

    private func desc(_ values: Float...) -> Data {
        var row = [Float](repeating: 0, count: 128)
        for (i, value) in values.enumerated() where i < 128 {
            row[i] = value
        }
        return row.withUnsafeBufferPointer { Data(buffer: $0) }
    }

    private func packDescriptors(_ rows: [Data]) -> Data {
        rows.reduce(into: Data()) { $0.append($1) }
    }

    private func readU32(_ data: Data, _ offset: Int) -> UInt32 {
        var value: UInt32 = 0
        _ = withUnsafeMutableBytes(of: &value) { dest in
            data.copyBytes(to: dest, from: offset..<(offset + 4))
        }
        return UInt32(littleEndian: value)
    }

    private func makeTexturedGray(width: Int, height: Int) -> Data {
        var pixels = [UInt8](repeating: 0, count: width * height)
        for y in 0..<height {
            for x in 0..<width {
                let checker = ((x / 12) + (y / 12)) % 2 == 0 ? 40 : 210
                let blob = hypot(Double(x - width / 3), Double(y - height / 3)) < 18 ? 255 : 0
                let blob2 = hypot(Double(x - 2 * width / 3), Double(y - 2 * height / 3)) < 14 ? 10 : 0
                let stripe = (x % 23 == 0) ? 180 : 0
                let value = min(255, max(0, checker + (blob > 0 ? 40 : 0) - (blob2 > 0 ? 30 : 0) + (stripe > 0 ? 20 : 0)))
                pixels[y * width + x] = UInt8(value)
            }
        }
        return Data(pixels)
    }
}
