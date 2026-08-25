import Foundation

/// Frozen Gate 3C matcher names. Not magic numbers.
enum MatchingConfig {
    static let candidateK = 16
    static let candidateKName = "candidateK"
    static let minDistinctPoint3DForRatio = 2
    static let ratioThreshold = 0.8
    static let descriptorDim = 128
    static let diagnosticMatchCap = 20
    static let rvs1Magic = Data("RVS1".utf8)
    static let rvs1Version: UInt32 = 1
    static let rvs1DtypeFloat32: UInt32 = 1
}
