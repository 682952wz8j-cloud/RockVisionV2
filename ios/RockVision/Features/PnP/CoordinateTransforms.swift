import Foundation

enum CoordinateTransformError: Error, Equatable {
    case sim3Unavailable
    case nonFinite
    case invalidSim3
}

/// Unique home for OpenCV↔ARKit camera-basis and production Wall↔ARWorld alignment.
/// No other file may write y = -y / z = -z for camera-basis change.
enum CoordinateTransforms {
    /// T_arkitCam_opencvCam. OpenCV +Y down +Z forward → ARKit +Y up −Z forward.
    /// Unique proper rotation: S = diag(1, -1, -1), det = +1.
    static let T_arkitCam_opencvCam: [[Double]] = [
        [1, 0, 0, 0],
        [0, -1, 0, 0],
        [0, 0, -1, 0],
        [0, 0, 0, 1]
    ]

    static func openCVCameraToARKitCamera() -> [[Double]] {
        T_arkitCam_opencvCam
    }

    /// S_wall_colmap as 4×4: X_wall = s * R * X_colmap + t.
    static func sim3Matrix(_ sim3: ValidatedSim3) throws -> [[Double]] {
        guard sim3.scale.isFinite, sim3.scale > 0,
              PnPGeometry.isFiniteMatrix(sim3.rotationMatrix, rows: 3, cols: 3),
              PnPGeometry.isFiniteVec(sim3.translationMeters, count: 3)
        else { throw CoordinateTransformError.invalidSim3 }
        let r = sim3.rotationMatrix
        let s = sim3.scale
        let t = sim3.translationMeters
        return [
            [s * r[0][0], s * r[0][1], s * r[0][2], t[0]],
            [s * r[1][0], s * r[1][1], s * r[1][2], t[1]],
            [s * r[2][0], s * r[2][1], s * r[2][2], t[2]],
            [0, 0, 0, 1]
        ]
    }

    /// Sim(3) point-map inverse only: X_colmap = Rᵀ * (X_wall - t) / s.
    /// Linear part includes 1/s (meters → recon-unit). Do not treat this as
    /// a camera SE(3) or left-multiply it by T_opencvCam_colmap to get meters.
    static func inverseSim3(_ sim3: ValidatedSim3) throws -> [[Double]] {
        guard sim3.scale.isFinite, sim3.scale > 0,
              PnPGeometry.isFiniteMatrix(sim3.rotationMatrix, rows: 3, cols: 3),
              PnPGeometry.isFiniteVec(sim3.translationMeters, count: 3)
        else { throw CoordinateTransformError.invalidSim3 }
        let r = sim3.rotationMatrix
        let s = sim3.scale
        let t = sim3.translationMeters
        let rt00 = r[0][0] / s, rt01 = r[1][0] / s, rt02 = r[2][0] / s
        let rt10 = r[0][1] / s, rt11 = r[1][1] / s, rt12 = r[2][1] / s
        let rt20 = r[0][2] / s, rt21 = r[1][2] / s, rt22 = r[2][2] / s
        let tx = -(rt00 * t[0] + rt01 * t[1] + rt02 * t[2])
        let ty = -(rt10 * t[0] + rt11 * t[1] + rt12 * t[2])
        let tz = -(rt20 * t[0] + rt21 * t[1] + rt22 * t[2])
        return [
            [rt00, rt01, rt02, tx],
            [rt10, rt11, rt12, ty],
            [rt20, rt21, rt22, tz],
            [0, 0, 0, 1]
        ]
    }

    static func multiply(_ a: [[Double]], _ b: [[Double]]) throws -> [[Double]] {
        guard Homogeneous.isFinite4x4(a), Homogeneous.isFinite4x4(b) else {
            throw CoordinateTransformError.nonFinite
        }
        return Homogeneous.multiply(a, b)
    }

    static func apply(_ t: [[Double]], point: [Double]) throws -> [Double] {
        guard Homogeneous.isFinite4x4(t), PnPGeometry.isFiniteVec(point, count: 3) else {
            throw CoordinateTransformError.nonFinite
        }
        return Homogeneous.apply(t, point: point)
    }

    /// Gate 5B: apply an existing production `T_ARWorld_Wall` once to a
    /// WallMetricMeters route position. Does not construct `T`. Does not
    /// take Sim(3) or a second scale. Vertices are positions (`w = 1`).
    static func applyFrozenWallRoutePointToARWorld(
        wallPointMeters: [Double],
        T_ARWorld_Wall: [[Double]]
    ) throws -> [Double] {
        try apply(T_ARWorld_Wall, point: wallPointMeters)
    }

    static func rowMajor(fromColumnMajor columns: [[Double]]) throws -> [[Double]] {
        guard Homogeneous.isFinite4x4(columns) else { throw CoordinateTransformError.nonFinite }
        return (0..<4).map { r in (0..<4).map { c in columns[c][r] } }
    }

    /// Unique production entry for T_ARWorld_Wall. Refuses if S_wall_colmap
    /// is unavailable. No identity fallback.
    ///
    /// T_ARWorld_Wall =
    ///     T_ARWorld_arkitCam
    ///   * T_arkitCam_opencvCam
    ///   * T_opencvCamMeters_wall
    ///
    /// T_opencvCamMeters_wall is SE(3) Wall meters → OpenCV camera meters:
    ///   R_cam_wall = R_p R_sᵀ
    ///   t_cam_wall = s * t_p - R_p R_sᵀ t_s
    /// with s in meters/recon-unit. Does not left-multiply T_opencvCam_colmap
    /// by inverse(S).
    static func productionAlignment(
        T_opencvCam_colmap: [[Double]],
        S_wall_colmap: ValidatedSim3?,
        T_ARWorld_arkitCam: [[Double]]
    ) throws -> [[Double]] {
        guard let sim3 = S_wall_colmap, sim3.status == "VALIDATED" else {
            throw CoordinateTransformError.sim3Unavailable
        }
        guard Homogeneous.isFinite4x4(T_opencvCam_colmap), Homogeneous.isFinite4x4(T_ARWorld_arkitCam) else {
            throw CoordinateTransformError.nonFinite
        }
        let T_opencvCamMeters_wall = try opencvCamMetersWallTransform(
            T_opencvCam_colmap: T_opencvCam_colmap,
            sim3: sim3
        )
        return try multiply(multiply(T_ARWorld_arkitCam, T_arkitCam_opencvCam), T_opencvCamMeters_wall)
    }

    /// Pure helper for productionAlignment. Wall meters → OpenCV camera meters SE(3).
    /// Not a second T_ARWorld_Wall production path. Runtime must not call this.
    private static func opencvCamMetersWallTransform(
        T_opencvCam_colmap: [[Double]],
        sim3: ValidatedSim3
    ) throws -> [[Double]] {
        guard sim3.scale.isFinite, sim3.scale > 0,
              PnPGeometry.isFiniteMatrix(sim3.rotationMatrix, rows: 3, cols: 3),
              PnPGeometry.isFiniteVec(sim3.translationMeters, count: 3)
        else { throw CoordinateTransformError.invalidSim3 }
        let R_p = rotation3x3(T_opencvCam_colmap)
        let t_p = translation(T_opencvCam_colmap)
        guard PnPGeometry.isFiniteMatrix(R_p, rows: 3, cols: 3),
              PnPGeometry.isFiniteVec(t_p, count: 3)
        else { throw CoordinateTransformError.nonFinite }
        let R_sT = transpose3x3(sim3.rotationMatrix)
        let R_cam_wall = multiply3x3(R_p, R_sT)
        let RsT_ts = multiply3x3vec(R_sT, sim3.translationMeters)
        let Rp_RsT_ts = multiply3x3vec(R_p, RsT_ts)
        let s = sim3.scale
        let t_cam_wall = [
            s * t_p[0] - Rp_RsT_ts[0],
            s * t_p[1] - Rp_RsT_ts[1],
            s * t_p[2] - Rp_RsT_ts[2]
        ]
        guard PnPGeometry.isFiniteMatrix(R_cam_wall, rows: 3, cols: 3),
              t_cam_wall.allSatisfy(\.isFinite)
        else { throw CoordinateTransformError.nonFinite }
        return se3(rotation: R_cam_wall, translation: t_cam_wall)
    }

    private static func rotation3x3(_ t: [[Double]]) -> [[Double]] {
        [
            [t[0][0], t[0][1], t[0][2]],
            [t[1][0], t[1][1], t[1][2]],
            [t[2][0], t[2][1], t[2][2]]
        ]
    }

    private static func translation(_ t: [[Double]]) -> [Double] {
        [t[0][3], t[1][3], t[2][3]]
    }

    private static func se3(rotation r: [[Double]], translation t: [Double]) -> [[Double]] {
        [
            [r[0][0], r[0][1], r[0][2], t[0]],
            [r[1][0], r[1][1], r[1][2], t[1]],
            [r[2][0], r[2][1], r[2][2], t[2]],
            [0, 0, 0, 1]
        ]
    }

    private static func transpose3x3(_ r: [[Double]]) -> [[Double]] {
        [
            [r[0][0], r[1][0], r[2][0]],
            [r[0][1], r[1][1], r[2][1]],
            [r[0][2], r[1][2], r[2][2]]
        ]
    }

    private static func multiply3x3(_ a: [[Double]], _ b: [[Double]]) -> [[Double]] {
        var c = [[Double]](repeating: [Double](repeating: 0, count: 3), count: 3)
        for i in 0..<3 {
            for j in 0..<3 {
                c[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j]
            }
        }
        return c
    }

    private static func multiply3x3vec(_ r: [[Double]], _ v: [Double]) -> [Double] {
        [
            r[0][0] * v[0] + r[0][1] * v[1] + r[0][2] * v[2],
            r[1][0] * v[0] + r[1][1] * v[1] + r[1][2] * v[2],
            r[2][0] * v[0] + r[2][1] * v[1] + r[2][2] * v[2]
        ]
    }
}

enum Homogeneous {
    static func isFinite4x4(_ m: [[Double]]) -> Bool {
        PnPGeometry.isFiniteMatrix(m, rows: 4, cols: 4)
    }

    static func multiply(_ a: [[Double]], _ b: [[Double]]) -> [[Double]] {
        var c = Array(repeating: Array(repeating: 0.0, count: 4), count: 4)
        for i in 0..<4 {
            for j in 0..<4 {
                var s = 0.0
                for k in 0..<4 { s += a[i][k] * b[k][j] }
                c[i][j] = s
            }
        }
        return c
    }

    static func apply(_ t: [[Double]], point: [Double]) -> [Double] {
        let x = point[0], y = point[1], z = point[2]
        return [
            t[0][0] * x + t[0][1] * y + t[0][2] * z + t[0][3],
            t[1][0] * x + t[1][1] * y + t[1][2] * z + t[1][3],
            t[2][0] * x + t[2][1] * y + t[2][2] * z + t[2][3]
        ]
    }
}
