import CoreGraphics
import Foundation

/// Resize that preserves aspect ratio and never crops. Does not upscale.
enum SIFTProcessingGeometry {
    static func sizeFitting(nativeWidth: Int, nativeHeight: Int, targetWidth: Int, targetHeight: Int) -> (width: Int, height: Int) {
        guard nativeWidth > 0, nativeHeight > 0 else { return (0, 0) }
        guard targetWidth > 0, targetHeight > 0 else { return (0, 0) }
        if nativeWidth <= targetWidth && nativeHeight <= targetHeight {
            return (nativeWidth, nativeHeight)
        }
        let scale = min(Double(targetWidth) / Double(nativeWidth), Double(targetHeight) / Double(nativeHeight))
        let width = max(1, Int((Double(nativeWidth) * scale).rounded()))
        let height = max(1, Int((Double(nativeHeight) * scale).rounded()))
        return (width, height)
    }

    static func scales(nativeWidth: Int, nativeHeight: Int, processingWidth: Int, processingHeight: Int) -> (scaleX: Double, scaleY: Double)? {
        guard nativeWidth > 0, nativeHeight > 0, processingWidth > 0, processingHeight > 0 else { return nil }
        return (
            Double(processingWidth) / Double(nativeWidth),
            Double(processingHeight) / Double(nativeHeight)
        )
    }

    /// processed → native captured-image pixels. Canonical output space for later PnP.
    static func nativePoint(processedX: Double, processedY: Double, scaleX: Double, scaleY: Double) -> CGPoint? {
        guard scaleX > 0, scaleY > 0, processedX.isFinite, processedY.isFinite else { return nil }
        return CGPoint(x: processedX / scaleX, y: processedY / scaleY)
    }
}

/// 4×3 cells over the native captured image. Used only for distribution diagnostics.
enum SIFTGrid {
    static let columns = 4
    static let rows = 3
    static var cellCount: Int { columns * rows }

    static func cellIndex(x: Double, y: Double, nativeWidth: Int, nativeHeight: Int) -> Int? {
        guard nativeWidth > 0, nativeHeight > 0, x.isFinite, y.isFinite else { return nil }
        if x < 0 || y < 0 || x > Double(nativeWidth) || y > Double(nativeHeight) {
            return nil
        }
        var col = Int((x / Double(nativeWidth)) * Double(columns))
        var row = Int((y / Double(nativeHeight)) * Double(rows))
        if col >= columns { col = columns - 1 }
        if row >= rows { row = rows - 1 }
        if col < 0 { col = 0 }
        if row < 0 { row = 0 }
        return row * columns + col
    }

    static func occupancy(nativePoints: [CGPoint], nativeWidth: Int, nativeHeight: Int) -> (counts: [Int], occupied: Int, ratio: Double) {
        var counts = Array(repeating: 0, count: cellCount)
        for point in nativePoints {
            if let index = cellIndex(x: point.x, y: point.y, nativeWidth: nativeWidth, nativeHeight: nativeHeight) {
                counts[index] += 1
            }
        }
        let occupied = counts.filter { $0 > 0 }.count
        return (counts, occupied, Double(occupied) / Double(cellCount))
    }
}

enum SIFTProcessingPreset: Int, CaseIterable, Sendable {
    case native
    case medium
    case low

    var targetWidth: Int {
        switch self {
        case .native: return 1920
        case .medium: return 1280
        case .low: return 960
        }
    }

    var targetHeight: Int {
        switch self {
        case .native: return 1440
        case .medium: return 960
        case .low: return 720
        }
    }

    var label: String {
        "\(targetWidth)×\(targetHeight)"
    }
}

enum SIFTSceneLabel: String, CaseIterable, Sendable {
    case unlabeled
    case A
    case B
    case C

    var buttonTitle: String {
        switch self {
        case .unlabeled: return "Unlabeled"
        case .A, .B, .C: return rawValue
        }
    }
}

enum SIFTStatistics {
    static func percentile(_ values: [Double], _ p: Double) -> Double? {
        guard !values.isEmpty else { return nil }
        let ordered = values.sorted()
        let idx = min(ordered.count - 1, max(0, Int((p / 100.0) * Double(ordered.count - 1))))
        return ordered[idx]
    }

    static func percentile(_ values: [Int], _ p: Double) -> Int? {
        guard let value = percentile(values.map(Double.init), p) else { return nil }
        return Int(value.rounded())
    }
}
