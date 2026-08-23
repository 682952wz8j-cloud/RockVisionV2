import CoreVideo
import Darwin
import XCTest
@testable import RockVision

final class SIFTExtractionTests: XCTestCase {
    func testSIFTCreationUsesFrozenBaseline() {
        XCTAssertTrue(OpenCVBridge.siftCreateAvailable())
        let summary = OpenCVBridge.siftParameterSummary()
        XCTAssertEqual(
            summary,
            "nfeatures=0 nOctaveLayers=3 contrastThreshold=0.04 edgeThreshold=10.0 sigma=1.6"
        )
        XCTAssertEqual(SIFTParameterRecord.nfeatures, 0)
        XCTAssertEqual(SIFTParameterRecord.nOctaveLayers, 3)
        XCTAssertEqual(SIFTParameterRecord.contrastThreshold, 0.04, accuracy: 0.0001)
        XCTAssertEqual(SIFTParameterRecord.edgeThreshold, 10.0, accuracy: 0.0001)
        XCTAssertEqual(SIFTParameterRecord.sigma, 1.6, accuracy: 0.0001)
    }

    func testEmptyImageHandling() {
        let missing = OpenCVBridge.extractSIFT(
            fromGrayBytes: nil,
            width: 16,
            height: 16,
            stride: 16,
            targetWidth: 0,
            targetHeight: 0,
            overlayCap: 0
        )
        XCTAssertFalse(missing.ok)
        XCTAssertEqual(missing.error, "empty image")
        XCTAssertEqual(missing.keypointCount, 0)

        let nullBuffer = OpenCVBridge.extractSIFT(from: nil, targetWidth: 0, targetHeight: 0, overlayCap: 0)
        XCTAssertFalse(nullBuffer.ok)
        XCTAssertEqual(nullBuffer.error, "null CVPixelBuffer")
    }

    func testInvalidDimensions() {
        let bytes = [UInt8](repeating: 80, count: 8)
        let zeroWidth = bytes.withUnsafeBytes { raw in
            OpenCVBridge.extractSIFT(
                fromGrayBytes: raw.bindMemory(to: UInt8.self).baseAddress,
                width: 0,
                height: 8,
                stride: 8,
                targetWidth: 0,
                targetHeight: 0,
                overlayCap: 0
            )
        }
        XCTAssertFalse(zeroWidth.ok)

        let badStride = bytes.withUnsafeBytes { raw in
            OpenCVBridge.extractSIFT(
                fromGrayBytes: raw.bindMemory(to: UInt8.self).baseAddress,
                width: 8,
                height: 1,
                stride: 4,
                targetWidth: 0,
                targetHeight: 0,
                overlayCap: 0
            )
        }
        XCTAssertFalse(badStride.ok)
        XCTAssertEqual(SIFTProcessingGeometry.sizeFitting(nativeWidth: 0, nativeHeight: 1440, targetWidth: 960, targetHeight: 720).width, 0)
        XCTAssertNil(SIFTProcessingGeometry.scales(nativeWidth: 0, nativeHeight: 10, processingWidth: 5, processingHeight: 5))
        XCTAssertNil(SIFTProcessingGeometry.nativePoint(processedX: 1, processedY: 1, scaleX: 0, scaleY: 1))
    }

    func testProcessingResizeKeepsAspectAndDoesNotCrop() {
        let native = SIFTProcessingGeometry.sizeFitting(nativeWidth: 1920, nativeHeight: 1440, targetWidth: 1920, targetHeight: 1440)
        XCTAssertEqual(native.width, 1920)
        XCTAssertEqual(native.height, 1440)

        let medium = SIFTProcessingGeometry.sizeFitting(nativeWidth: 1920, nativeHeight: 1440, targetWidth: 1280, targetHeight: 960)
        XCTAssertEqual(medium.width, 1280)
        XCTAssertEqual(medium.height, 960)

        let low = SIFTProcessingGeometry.sizeFitting(nativeWidth: 1920, nativeHeight: 1440, targetWidth: 960, targetHeight: 720)
        XCTAssertEqual(low.width, 960)
        XCTAssertEqual(low.height, 720)

        XCTAssertEqual(Double(medium.width) / Double(1920), Double(medium.height) / Double(1440), accuracy: 1e-9)
        XCTAssertEqual(Double(low.width) / Double(1920), Double(low.height) / Double(1440), accuracy: 1e-9)
    }

    func testKeypointProcessedToNativeMapping() throws {
        let scales = try XCTUnwrap(SIFTProcessingGeometry.scales(nativeWidth: 1920, nativeHeight: 1440, processingWidth: 960, processingHeight: 720))
        XCTAssertEqual(scales.scaleX, 0.5, accuracy: 1e-12)
        XCTAssertEqual(scales.scaleY, 0.5, accuracy: 1e-12)
        let mapped = try XCTUnwrap(SIFTProcessingGeometry.nativePoint(processedX: 240, processedY: 180, scaleX: scales.scaleX, scaleY: scales.scaleY))
        XCTAssertEqual(mapped.x, 480, accuracy: 1e-9)
        XCTAssertEqual(mapped.y, 360, accuracy: 1e-9)
    }

    func testRuntimeResizeReportsNativeMappedCoordinates() throws {
        let image = Self.makeTexturedGray(width: 160, height: 120)
        let result = try XCTUnwrap(image.withUnsafeBytes { raw in
            OpenCVBridge.extractSIFT(
                fromGrayBytes: raw.bindMemory(to: UInt8.self).baseAddress,
                width: 160,
                height: 120,
                stride: 160,
                targetWidth: 80,
                targetHeight: 60,
                overlayCap: 16
            )
        })
        XCTAssertTrue(result.ok)
        XCTAssertEqual(result.nativeWidth, 160)
        XCTAssertEqual(result.nativeHeight, 120)
        XCTAssertEqual(result.processingWidth, 80)
        XCTAssertEqual(result.processingHeight, 60)
        XCTAssertEqual(result.scaleX, 0.5, accuracy: 1e-9)
        XCTAssertEqual(result.scaleY, 0.5, accuracy: 1e-9)
        XCTAssertGreaterThan(result.keypointCount, 0)
        XCTAssertEqual(result.nativeX.count, Int(result.keypointCount))
        for (x, y) in zip(result.nativeX, result.nativeY) {
            XCTAssertGreaterThanOrEqual(x.doubleValue, -2)
            XCTAssertGreaterThanOrEqual(y.doubleValue, -2)
            XCTAssertLessThanOrEqual(x.doubleValue, 162)
            XCTAssertLessThanOrEqual(y.doubleValue, 122)
            let processedX = x.doubleValue * result.scaleX
            let remapped = try XCTUnwrap(SIFTProcessingGeometry.nativePoint(
                processedX: processedX,
                processedY: y.doubleValue * result.scaleY,
                scaleX: result.scaleX,
                scaleY: result.scaleY
            ))
            XCTAssertEqual(remapped.x, x.doubleValue, accuracy: 1e-6)
            XCTAssertEqual(remapped.y, y.doubleValue, accuracy: 1e-6)
        }
    }

    func testDescriptorShapeAndFiniteValidation() throws {
        let image = Self.makeTexturedGray(width: 192, height: 144)
        let result = try XCTUnwrap(image.withUnsafeBytes { raw in
            OpenCVBridge.extractSIFT(
                fromGrayBytes: raw.bindMemory(to: UInt8.self).baseAddress,
                width: 192,
                height: 144,
                stride: 192,
                targetWidth: 0,
                targetHeight: 0,
                overlayCap: 8
            )
        })
        XCTAssertTrue(result.ok)
        XCTAssertGreaterThan(result.keypointCount, 0)
        XCTAssertEqual(result.descriptorRows, result.keypointCount)
        XCTAssertTrue(result.rowsMatchKeypoints)
        XCTAssertGreaterThan(result.descriptorCols, 0)
        XCTAssertEqual(result.descriptorTypeName, "CV_32F")
        XCTAssertTrue(result.descriptorsFinite)
        XCTAssertEqual(Int(result.descriptorRows), result.nativeX.count)
        print("SIFT_RUNTIME type=\(result.descriptorTypeName) dim=\(result.descriptorCols) rows=\(result.descriptorRows) kp=\(result.keypointCount) typeCode=\(result.descriptorTypeCode)")
    }

    func testOverlayCapDoesNotChangeExtractedCount() throws {
        let image = Self.makeTexturedGray(width: 160, height: 120)
        let full = try XCTUnwrap(image.withUnsafeBytes { raw in
            OpenCVBridge.extractSIFT(
                fromGrayBytes: raw.bindMemory(to: UInt8.self).baseAddress,
                width: 160,
                height: 120,
                stride: 160,
                targetWidth: 0,
                targetHeight: 0,
                overlayCap: 200
            )
        })
        let capped = try XCTUnwrap(image.withUnsafeBytes { raw in
            OpenCVBridge.extractSIFT(
                fromGrayBytes: raw.bindMemory(to: UInt8.self).baseAddress,
                width: 160,
                height: 120,
                stride: 160,
                targetWidth: 0,
                targetHeight: 0,
                overlayCap: 3
            )
        })
        XCTAssertEqual(full.keypointCount, capped.keypointCount)
        XCTAssertEqual(full.descriptorRows, capped.descriptorRows)
        XCTAssertLessThanOrEqual(capped.overlayNativeX.count, 3)
        XCTAssertEqual(capped.overlayNativeX.count, capped.overlayNativeY.count)
    }

    func testGridAssignmentAndBoundaries() {
        XCTAssertEqual(SIFTGrid.cellIndex(x: 0, y: 0, nativeWidth: 1920, nativeHeight: 1440), 0)
        XCTAssertEqual(SIFTGrid.cellIndex(x: 479.9, y: 479.9, nativeWidth: 1920, nativeHeight: 1440), 0)
        XCTAssertEqual(SIFTGrid.cellIndex(x: 480, y: 0, nativeWidth: 1920, nativeHeight: 1440), 1)
        XCTAssertEqual(SIFTGrid.cellIndex(x: 1919, y: 0, nativeWidth: 1920, nativeHeight: 1440), 3)
        XCTAssertEqual(SIFTGrid.cellIndex(x: 0, y: 1439, nativeWidth: 1920, nativeHeight: 1440), 8)
        XCTAssertEqual(SIFTGrid.cellIndex(x: 1920, y: 1440, nativeWidth: 1920, nativeHeight: 1440), 11)
        XCTAssertNil(SIFTGrid.cellIndex(x: -0.1, y: 10, nativeWidth: 1920, nativeHeight: 1440))
        XCTAssertNil(SIFTGrid.cellIndex(x: 1920.1, y: 10, nativeWidth: 1920, nativeHeight: 1440))
        XCTAssertNil(SIFTGrid.cellIndex(x: 10, y: -1, nativeWidth: 1920, nativeHeight: 1440))

        let points = [
            CGPoint(x: 10, y: 10),
            CGPoint(x: 500, y: 10),
            CGPoint(x: 500, y: 10),
            CGPoint(x: 1000, y: 800),
        ]
        let occupancy = SIFTGrid.occupancy(nativePoints: points, nativeWidth: 1920, nativeHeight: 1440)
        XCTAssertEqual(occupancy.counts.reduce(0, +), 4)
        XCTAssertEqual(occupancy.occupied, 3)
        XCTAssertEqual(occupancy.ratio, 3.0 / 12.0, accuracy: 1e-12)
    }

    func testResultModelAndLabels() {
        let result = SIFTFrameResult(
            frameID: 7,
            timestamp: 1.5,
            ok: true,
            status: "active",
            nativeImageWidth: 1920,
            nativeImageHeight: 1440,
            processingWidth: 960,
            processingHeight: 720,
            scaleX: 0.5,
            scaleY: 0.5,
            keypointCount: 12,
            descriptorCount: 12,
            descriptorDimension: 128,
            descriptorType: "CV_32F",
            descriptorRows: 12,
            descriptorCols: 128,
            descriptorsFinite: true,
            rowsMatchKeypoints: true,
            preprocessLatencyMs: 1.2,
            siftLatencyMs: 8.4,
            totalLatencyMs: 9.6,
            gridCounts: Array(repeating: 1, count: 12),
            occupiedCells: 12,
            occupancyRatio: 1,
            keypointsNative: [],
            overlayNative: [CGPoint(x: 10, y: 20)],
            error: nil
        )
        XCTAssertEqual(result.processingLabel, "960 × 720")
        XCTAssertEqual(result.descriptorLabel, "12 × 128")
        XCTAssertEqual(result.gridLabel, "12 / 12")
        XCTAssertEqual(result, result)
        let empty = SIFTFrameResult.empty(frameID: 1, timestamp: 0, error: "empty image")
        XCTAssertFalse(empty.ok)
        XCTAssertEqual(empty.gridCounts.count, SIFTGrid.cellCount)
    }

    func testPixelBufferYPlaneExtraction() throws {
        let buffer = try XCTUnwrap(Self.makeTextured420f(width: 128, height: 96))
        let result = OpenCVBridge.extractSIFT(from: buffer, targetWidth: 96, targetHeight: 72, overlayCap: 10)
        XCTAssertTrue(result.ok)
        XCTAssertEqual(result.nativeWidth, 128)
        XCTAssertEqual(result.nativeHeight, 96)
        XCTAssertEqual(result.processingWidth, 96)
        XCTAssertEqual(result.processingHeight, 72)
        XCTAssertTrue(result.rowsMatchKeypoints)
        XCTAssertTrue(result.descriptorsFinite)
    }

    func testRepeatedExtractionLifecycle() throws {
        let image = Self.makeTexturedGray(width: 128, height: 96)
        var lastCount = -1
        for _ in 0..<8 {
            let result = try XCTUnwrap(image.withUnsafeBytes { raw in
                OpenCVBridge.extractSIFT(
                    fromGrayBytes: raw.bindMemory(to: UInt8.self).baseAddress,
                    width: 128,
                    height: 96,
                    stride: 128,
                    targetWidth: 96,
                    targetHeight: 72,
                    overlayCap: 4
                )
            })
            XCTAssertTrue(result.ok)
            XCTAssertTrue(result.rowsMatchKeypoints)
            XCTAssertTrue(result.descriptorsFinite)
            XCTAssertEqual(result.nativeX.count, Int(result.keypointCount))
            if lastCount >= 0 {
                XCTAssertEqual(Int(result.keypointCount), lastCount)
            }
            lastCount = Int(result.keypointCount)
        }
    }

    func testSceneLabelsAreExplicitAndSettable() {
        XCTAssertEqual(SIFTSceneLabel.allCases.map(\.rawValue), ["unlabeled", "A", "B", "C"])
        XCTAssertEqual(SIFTSceneLabel.unlabeled.buttonTitle, "Unlabeled")
        let processor = OpenCVFrameProcessor()
        XCTAssertEqual(processor.siftSnapshot.scene, "unlabeled")
        let sequence = ["A", "B", "C", "unlabeled"]
        for scene in sequence {
            let done = expectation(description: "scene \(scene)")
            processor.setScene(scene)
            DispatchQueue.main.async {
                XCTAssertEqual(processor.siftSnapshot.scene, scene)
                done.fulfill()
            }
            wait(for: [done], timeout: 1.0)
        }
        processor.setScene("not-a-scene")
        let ignored = expectation(description: "invalid scene ignored")
        DispatchQueue.main.async {
            XCTAssertEqual(processor.siftSnapshot.scene, "unlabeled")
            ignored.fulfill()
        }
        wait(for: [ignored], timeout: 1.0)
    }

    func testResolutionAndDotsAreIndependentControls() {
        let processor = OpenCVFrameProcessor()
        XCTAssertTrue(processor.siftSnapshot.showKeypoints)
        let presetDone = expectation(description: "preset")
        processor.setPreset(.low)
        DispatchQueue.main.async {
            XCTAssertEqual(processor.siftSnapshot.presetLabel, SIFTProcessingPreset.low.label)
            presetDone.fulfill()
        }
        wait(for: [presetDone], timeout: 1.0)
        processor.toggleKeypointOverlay()
        let dotsDone = expectation(description: "dots")
        DispatchQueue.main.async {
            XCTAssertFalse(processor.siftSnapshot.showKeypoints)
            XCTAssertEqual(processor.siftSnapshot.presetLabel, SIFTProcessingPreset.low.label)
            dotsDone.fulfill()
        }
        wait(for: [dotsDone], timeout: 1.0)
    }

    func testPercentileHelper() {
        XCTAssertNil(SIFTStatistics.percentile([Int](), 50))
        XCTAssertEqual(SIFTStatistics.percentile([1, 2, 3, 4, 5], 50), 3)
        XCTAssertEqual(SIFTStatistics.percentile([1, 2, 3, 4, 5], 90), 4)
        XCTAssertEqual(SIFTStatistics.percentile([10.0, 20.0, 30.0], 0), 10.0)
    }

    private static func makeTexturedGray(width: Int, height: Int) -> [UInt8] {
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
        return pixels
    }

    private static func makeTextured420f(width: Int, height: Int) -> CVPixelBuffer? {
        var buffer: CVPixelBuffer?
        let status = CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
            nil,
            &buffer
        )
        guard status == kCVReturnSuccess, let buffer else { return nil }
        let gray = makeTexturedGray(width: width, height: height)
        CVPixelBufferLockBaseAddress(buffer, [])
        let stride = CVPixelBufferGetBytesPerRowOfPlane(buffer, 0)
        if let base = CVPixelBufferGetBaseAddressOfPlane(buffer, 0) {
            gray.withUnsafeBytes { raw in
                guard let src = raw.baseAddress else { return }
                for row in 0..<height {
                    memcpy(base.advanced(by: row * stride), src.advanced(by: row * width), width)
                }
            }
        }
        CVPixelBufferUnlockBaseAddress(buffer, [])
        return buffer
    }
}
