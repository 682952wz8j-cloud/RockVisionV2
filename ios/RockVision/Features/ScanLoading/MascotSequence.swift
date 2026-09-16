import Foundation
import UIKit

/// Lime PNG sequence clips packed at `Resources/MascotLime/`.
/// Original ZIP/MOV: `design-assets/mascot/source/` (not in the App bundle).
/// Confirmed fill #D7FF3F. Blender deliveries are obsolete.
///
/// Run loop: source frames 0029, 0030, 0032, 0033, 0034, 0035, 0037, 0038.
/// Duplicate holds stripped so footfall cadence stays even. Seam of 0038→0029
/// matched source 0039≈0029 (mean RGBA delta 0.18). Playback 12 fps.
///
/// Jump: source 0178…0232 unique frames (crouch, launch, air, land). The PNG
/// already contains vertical body travel — HUD must not add a second hop.
enum MascotSequence {
    static let framesPerSecond: Double = 12
    static let runFrameCount = 8
    static let jumpFrameCount = 23
    static let runSourceFrames = [29, 30, 32, 33, 34, 35, 37, 38]
    static let jumpSourceFrames = [
        178, 179, 182, 184, 187, 189, 192, 194, 197, 199, 202, 204, 207,
        209, 212, 214, 217, 219, 222, 224, 227, 229, 232,
    ]

    private static let cache = NSCache<NSString, UIImage>()

    static func image(clip: MascotClipKind, index: Int) -> UIImage? {
        let count = clip == .run ? runFrameCount : jumpFrameCount
        guard count > 0 else { return nil }
        let wrapped = ((index % count) + count) % count
        let folder = clip == .run ? "run" : "jump"
        let name = String(format: "%@_%02d", clip == .run ? "run" : "jump", wrapped)
        let key = "\(folder)/\(name)" as NSString
        if let cached = cache.object(forKey: key) {
            return cached
        }
        let image = loadPNG(folder: folder, name: name)
        if let image {
            cache.setObject(image, forKey: key)
        }
        return image
    }

    private static func loadPNG(folder: String, name: String) -> UIImage? {
        let bundle = Bundle(for: ScanSessionBridge.self)
        if let url = bundle.url(forResource: name, withExtension: "png", subdirectory: "MascotLime/\(folder)") {
            return UIImage(contentsOfFile: url.path)
        }
        if let url = bundle.url(forResource: name, withExtension: "png", subdirectory: folder) {
            return UIImage(contentsOfFile: url.path)
        }
        return UIImage(named: name)
    }
}
