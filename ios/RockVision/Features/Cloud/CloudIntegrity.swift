import CryptoKit
import Foundation

enum CloudIntegrity {
    static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func verify(data: Data, descriptor: WallAssetDescriptor) throws {
        guard data.count == descriptor.bytes else {
            throw CloudAssetError.integrityFailure("bytes mismatch for \(descriptor.assetId)")
        }
        let actual = sha256Hex(data)
        guard actual == descriptor.sha256.lowercased() else {
            throw CloudAssetError.integrityFailure("sha256 mismatch for \(descriptor.assetId)")
        }
    }
}
