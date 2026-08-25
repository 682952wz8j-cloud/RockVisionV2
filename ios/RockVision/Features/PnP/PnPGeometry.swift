import Foundation

struct PnPReprojectionStats: Codable, Equatable, Sendable {
    var mean: Double
    var median: Double
    var p90: Double
    var max: Double
    var count: Int
}

struct PnPCheiralityStats: Equatable, Sendable {
    var positiveDepthCount: Int
    var inlierCount: Int
    var positiveDepthRatio: Double
    var medianInlierDepthCam: Double?
}

enum PnPGeometry {
    /// C_colmap = -Rᵀ * t. Do not treat t as camera position.
    static func cameraCenter(rotationRowMajor3x3: [[Double]], t: [Double]) -> [Double] {
        let r = flatten(rotationRowMajor3x3)
        let tx = t[0], ty = t[1], tz = t[2]
        return [
            -(r[0] * tx + r[3] * ty + r[6] * tz),
            -(r[1] * tx + r[4] * ty + r[7] * tz),
            -(r[2] * tx + r[5] * ty + r[8] * tz)
        ]
    }

    /// T_opencvCam_colmap = [R t; 0 1], mapping COLMAP → OpenCV camera.
    static func transformOpenCVCamColmap(rotationRowMajor3x3: [[Double]], t: [Double]) -> [[Double]] {
        let r = rotationRowMajor3x3
        return [
            [r[0][0], r[0][1], r[0][2], t[0]],
            [r[1][0], r[1][1], r[1][2], t[1]],
            [r[2][0], r[2][1], r[2][2], t[2]],
            [0, 0, 0, 1]
        ]
    }

    /// X_cam = R * X_colmap + t
    static func cameraPoint(rotationRowMajor3x3: [[Double]], t: [Double], world: [Double]) -> [Double] {
        let r = rotationRowMajor3x3
        return [
            r[0][0] * world[0] + r[0][1] * world[1] + r[0][2] * world[2] + t[0],
            r[1][0] * world[0] + r[1][1] * world[1] + r[1][2] * world[2] + t[1],
            r[2][0] * world[0] + r[2][1] * world[1] + r[2][2] * world[2] + t[2]
        ]
    }

    static func rotationAngleDegrees(estimated: [[Double]], groundTruth: [[Double]]) -> Double {
        let a = flatten(estimated)
        let b = flatten(groundTruth)
        // R_err = R_est * R_gtᵀ
        var err = [Double](repeating: 0, count: 9)
        for i in 0..<3 {
            for j in 0..<3 {
                err[i * 3 + j] =
                    a[i * 3 + 0] * b[j * 3 + 0] +
                    a[i * 3 + 1] * b[j * 3 + 1] +
                    a[i * 3 + 2] * b[j * 3 + 2]
            }
        }
        let trace = err[0] + err[4] + err[8]
        let c = max(-1.0, min(1.0, (trace - 1.0) * 0.5))
        return acos(c) * 180.0 / Double.pi
    }

    static func l2(_ a: [Double], _ b: [Double]) -> Double {
        zip(a, b).reduce(0) { $0 + ($1.0 - $1.1) * ($1.0 - $1.1) }.squareRoot()
    }

    static func cheirality(
        rotationRowMajor3x3: [[Double]],
        t: [Double],
        objectPoints: [[Double]],
        inlierIndices: [Int]
    ) -> PnPCheiralityStats {
        var depths: [Double] = []
        var positive = 0
        for index in inlierIndices where index >= 0 && index < objectPoints.count {
            let cam = cameraPoint(rotationRowMajor3x3: rotationRowMajor3x3, t: t, world: objectPoints[index])
            depths.append(cam[2])
            if cam[2] > 0 { positive += 1 }
        }
        return PnPCheiralityStats(
            positiveDepthCount: positive,
            inlierCount: inlierIndices.count,
            positiveDepthRatio: inlierIndices.isEmpty ? 0 : Double(positive) / Double(inlierIndices.count),
            medianInlierDepthCam: SIFTStatistics.percentile(depths, 50)
        )
    }

    static func reprojectionStats(observed: [[Double]], projected: [[Double]]) -> PnPReprojectionStats? {
        let n = min(observed.count, projected.count)
        guard n > 0 else { return nil }
        var errors: [Double] = []
        errors.reserveCapacity(n)
        for i in 0..<n {
            errors.append(l2(observed[i], projected[i]))
        }
        guard let median = SIFTStatistics.percentile(errors, 50),
              let p90 = SIFTStatistics.percentile(errors, 90),
              let maxV = errors.max()
        else { return nil }
        let mean = errors.reduce(0, +) / Double(n)
        return PnPReprojectionStats(mean: mean, median: median, p90: p90, max: maxV, count: n)
    }

    static func scaleCameraMatrix(_ k: [[Double]], factor: Double) -> [[Double]] {
        [
            [k[0][0] * factor, k[0][1] * factor, k[0][2] * factor],
            [k[1][0] * factor, k[1][1] * factor, k[1][2] * factor],
            [k[2][0], k[2][1], k[2][2]]
        ]
    }

    static func scalePoints(_ points: [[Double]], factor: Double) -> [[Double]] {
        points.map { [$0[0] * factor, $0[1] * factor] }
    }

    static func isFiniteVec(_ values: [Double]?, count: Int) -> Bool {
        guard let values, values.count == count else { return false }
        return values.allSatisfy(\.isFinite)
    }

    static func isFiniteMatrix(_ matrix: [[Double]]?, rows: Int, cols: Int) -> Bool {
        guard let matrix, matrix.count == rows else { return false }
        return matrix.allSatisfy { $0.count == cols && $0.allSatisfy(\.isFinite) }
    }

    private static func flatten(_ m: [[Double]]) -> [Double] {
        [m[0][0], m[0][1], m[0][2], m[1][0], m[1][1], m[1][2], m[2][0], m[2][1], m[2][2]]
    }
}
