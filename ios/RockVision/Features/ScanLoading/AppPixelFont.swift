import CoreText
import SwiftUI
import UIKit

/// Bundled Ark Pixel 12px monospaced Simplified Chinese (`zh_cn` / zh-Hans).
/// Official release 2026.02.27. Missing glyphs such as 徽 fall back to PingFang SC.
enum AppPixelFont {
    static let pointSize: CGFloat = 12
    static let postScriptName = "Ark-Pixel-12px-Mono-zh_cn-Regular"
    static let fileName = "ark-pixel-12px-monospaced-zh_cn"
    static let releaseTag = "2026.02.27"

    static var font: Font { Font(uiFont as CTFont) }

    static var uiFont: UIFont {
        _ = registration
        let pixel = UIFont(name: postScriptName, size: pointSize)
            ?? UIFont.monospacedSystemFont(ofSize: pointSize, weight: .regular)
        let fallback = UIFont(name: "PingFangSC-Regular", size: pointSize)
            ?? UIFont.systemFont(ofSize: pointSize)
        let descriptor = pixel.fontDescriptor.addingAttributes([
            .cascadeList: [fallback.fontDescriptor],
        ])
        return UIFont(descriptor: descriptor, size: pointSize)
    }

    static var pixelFaceAvailable: Bool {
        _ = registration
        return UIFont(name: postScriptName, size: pointSize) != nil
    }

    static func glyphExists(_ scalar: UnicodeScalar) -> Bool {
        _ = uiFont
        let font = CTFontCreateWithName(postScriptName as CFString, pointSize, nil)
        var character = UniChar(scalar.value)
        var glyph: CGGlyph = 0
        return CTFontGetGlyphsForCharacters(font, &character, &glyph, 1) && glyph != 0
    }

    private static let registration: Void = {
        let bundle = Bundle(for: ScanSessionBridge.self)
        let url = bundle.url(forResource: fileName, withExtension: "otf", subdirectory: "Fonts")
            ?? bundle.url(forResource: fileName, withExtension: "otf")
        if let url {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
    }()
}

enum ScanLoadingCopy {
    static let identifyPending = "识别岩壁…"
    static let localizePending = "定位攀爬路线…"
    static let loadPending = "加载攀爬路线…"
    static let identifyTitle = "识别岩壁"
    static let localizeTitle = "定位攀爬路线"
    static let loadTitle = "加载攀爬路线"
    static let successLine = "成功！"

    static func columnText(pending: String, title: String, done: Bool) -> String {
        done ? "\(title)\n\(successLine)" : pending
    }
}
