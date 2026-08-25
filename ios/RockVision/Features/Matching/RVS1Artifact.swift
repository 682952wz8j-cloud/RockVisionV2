import Foundation

enum MatchingError: Error, Equatable, LocalizedError {
    case badDescriptorDimension(Int)
    case truncatedRVS1
    case badMagic
    case unsupportedVersion(UInt32)
    case unsupportedDtype(UInt32)
    case lengthMismatch(expected: Int, actual: Int)
    case nonFiniteDescriptors
    case landmarkCountMismatch(descriptors: Int, landmarks: Int)
    case knnFailed(String)
    case missingFixtureFile(String)
    case sha256Mismatch(file: String, expected: String, actual: String)
    case uniquePoint3DMismatch(expected: Int, actual: Int)
    case fixtureIdentityMismatch(String)

    var errorDescription: String? {
        switch self {
        case .badDescriptorDimension(let dim):
            return "descriptor dim \(dim) != \(MatchingConfig.descriptorDim)"
        case .truncatedRVS1:
            return "truncated RVS1 header"
        case .badMagic:
            return "bad RVS1 magic"
        case .unsupportedVersion(let version):
            return "unsupported RVS1 version \(version)"
        case .unsupportedDtype(let dtype):
            return "unsupported RVS1 dtype \(dtype)"
        case .lengthMismatch(let expected, let actual):
            return "RVS1 length \(actual) != \(expected)"
        case .nonFiniteDescriptors:
            return "non-finite descriptors"
        case .landmarkCountMismatch(let descriptors, let landmarks):
            return "landmarks length \(landmarks) != descriptor rows \(descriptors)"
        case .knnFailed(let message):
            return message
        case .missingFixtureFile(let name):
            return "missing development fixture file \(name)"
        case .sha256Mismatch(let file, let expected, let actual):
            return "\(file) SHA-256 \(actual) != \(expected)"
        case .uniquePoint3DMismatch(let expected, let actual):
            return "unique Point3D \(actual) != \(expected)"
        case .fixtureIdentityMismatch(let message):
            return message
        }
    }
}

enum DescriptorMatrix {
    static func byteCount(rows: Int, dim: Int = MatchingConfig.descriptorDim) -> Int {
        rows * dim * MemoryLayout<Float>.size
    }

    static func rowCount(data: Data, dim: Int = MatchingConfig.descriptorDim) -> Int {
        guard dim > 0 else { return 0 }
        return data.count / (dim * MemoryLayout<Float>.size)
    }

    static func validateNonEmptyDimension(_ dim: Int, count: Int) throws {
        if count > 0, dim != MatchingConfig.descriptorDim {
            throw MatchingError.badDescriptorDimension(dim)
        }
    }

    static func finiteFlags(data: Data, count: Int, dim: Int = MatchingConfig.descriptorDim) -> [Bool] {
        guard count > 0, dim > 0, data.count >= byteCount(rows: count, dim: dim) else {
            return Array(repeating: true, count: max(0, count))
        }
        return data.withUnsafeBytes { raw -> [Bool] in
            guard let base = raw.bindMemory(to: Float.self).baseAddress else {
                return Array(repeating: false, count: count)
            }
            return (0..<count).map { row in
                let start = row * dim
                for c in 0..<dim {
                    if !base[start + c].isFinite { return false }
                }
                return true
            }
        }
    }

    static func allFinite(_ data: Data) -> Bool {
        data.withUnsafeBytes { raw in
            let floats = raw.bindMemory(to: Float.self)
            for value in floats where !value.isFinite {
                return false
            }
            return true
        }
    }
}

enum MatchingKNN {
    static func unpack(indicesInt32: Data, distancesFloat32: Data, queryCount: Int, k: Int) -> ([[Int]], [[Double]]) {
        let indexCount = queryCount * k
        var indices = Array(repeating: Array(repeating: -1, count: k), count: queryCount)
        var distances = Array(repeating: Array(repeating: Double.infinity, count: k), count: queryCount)
        indicesInt32.withUnsafeBytes { raw in
            let ints = raw.bindMemory(to: Int32.self)
            let n = min(indexCount, ints.count)
            for i in 0..<n {
                indices[i / k][i % k] = Int(ints[i])
            }
        }
        distancesFloat32.withUnsafeBytes { raw in
            let floats = raw.bindMemory(to: Float.self)
            let n = min(indexCount, floats.count)
            for i in 0..<n {
                distances[i / k][i % k] = Double(floats[i])
            }
        }
        return (indices, distances)
    }
}

enum RVS1Artifact {
    static let headerByteCount = 20

    static func write(descriptors: Data, dim: Int = MatchingConfig.descriptorDim, to url: URL) throws {
        try validateNonEmptyDimensionForWrite(descriptors: descriptors, dim: dim)
        if !DescriptorMatrix.allFinite(descriptors) {
            throw MatchingError.nonFiniteDescriptors
        }
        let count = DescriptorMatrix.rowCount(data: descriptors, dim: dim)
        var payload = Data()
        payload.reserveCapacity(headerByteCount + descriptors.count)
        payload.append(MatchingConfig.rvs1Magic)
        appendUInt32(&payload, MatchingConfig.rvs1Version)
        appendUInt32(&payload, MatchingConfig.rvs1DtypeFloat32)
        appendUInt32(&payload, UInt32(dim))
        appendUInt32(&payload, UInt32(count))
        payload.append(descriptors)
        try payload.write(to: url, options: .atomic)
    }

    static func read(from url: URL) throws -> (count: Int, dim: Int, data: Data) {
        try read(data: try Data(contentsOf: url))
    }

    static func read(data: Data) throws -> (count: Int, dim: Int, data: Data) {
        guard data.count >= headerByteCount else { throw MatchingError.truncatedRVS1 }
        let magic = data.prefix(4)
        if magic != MatchingConfig.rvs1Magic { throw MatchingError.badMagic }
        let version = readUInt32(data, offset: 4)
        if version != MatchingConfig.rvs1Version { throw MatchingError.unsupportedVersion(version) }
        let dtype = readUInt32(data, offset: 8)
        if dtype != MatchingConfig.rvs1DtypeFloat32 { throw MatchingError.unsupportedDtype(dtype) }
        let dim = Int(readUInt32(data, offset: 12))
        if dim != MatchingConfig.descriptorDim { throw MatchingError.badDescriptorDimension(dim) }
        let count = Int(readUInt32(data, offset: 16))
        let expected = headerByteCount + DescriptorMatrix.byteCount(rows: count, dim: dim)
        if data.count != expected {
            throw MatchingError.lengthMismatch(expected: expected, actual: data.count)
        }
        let descriptors = data.dropFirst(headerByteCount)
        if !DescriptorMatrix.allFinite(Data(descriptors)) {
            throw MatchingError.nonFiniteDescriptors
        }
        return (count, dim, Data(descriptors))
    }

    private static func validateNonEmptyDimensionForWrite(descriptors: Data, dim: Int) throws {
        if dim != MatchingConfig.descriptorDim {
            throw MatchingError.badDescriptorDimension(dim)
        }
        let rowBytes = dim * MemoryLayout<Float>.size
        if rowBytes == 0 || descriptors.count % rowBytes != 0 {
            throw MatchingError.badDescriptorDimension(dim)
        }
    }

    private static func appendUInt32(_ data: inout Data, _ value: UInt32) {
        var le = value.littleEndian
        Swift.withUnsafeBytes(of: &le) { data.append(contentsOf: $0) }
    }

    private static func readUInt32(_ data: Data, offset: Int) -> UInt32 {
        var value: UInt32 = 0
        _ = withUnsafeMutableBytes(of: &value) { dest in
            data.copyBytes(to: dest, from: offset..<(offset + 4))
        }
        return UInt32(littleEndian: value)
    }
}
