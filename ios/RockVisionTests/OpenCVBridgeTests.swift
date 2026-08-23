import CoreVideo
import simd
import XCTest
@testable import RockVision

final class OpenCVBridgeTests: XCTestCase {
    func testOpenCVBridgeLoadsVersion() {
        let version = OpenCVBridge.openCVVersion()
        XCTAssertFalse(version.isEmpty)
        XCTAssertTrue(version.hasPrefix("4.14"), "locked OpenCV 4.14.x, got \(version)")
    }

    func testOpenCVBuildSummaryAccessible() {
        let summary = OpenCVBridge.openCVBuildSummary()
        XCTAssertFalse(summary.isEmpty)
    }

    func testNullBufferDoesNotCrash() {
        let result = OpenCVBridge.processPixelBuffer(nil)
        XCTAssertNotNil(result)
        XCTAssertFalse(result?.ok ?? true)
        XCTAssertEqual(result?.error, "null CVPixelBuffer")
    }

    func testGrayscalePixelBufferToMat() throws {
        let buffer = try XCTUnwrap(Self.makeGrayPixelBuffer(width: 32, height: 24, value: 80))
        let result = try XCTUnwrap(OpenCVBridge.processPixelBuffer(buffer))
        XCTAssertTrue(result.ok)
        XCTAssertEqual(result.rows, 24)
        XCTAssertEqual(result.cols, 32)
        XCTAssertEqual(result.matType, 0) // CV_8UC1
        XCTAssertTrue(result.dataNonNull)
        XCTAssertEqual(result.meanIntensity, 80, accuracy: 0.5)
        XCTAssertEqual(result.minIntensity, 80, accuracy: 0.5)
        XCTAssertEqual(result.maxIntensity, 80, accuracy: 0.5)
    }

    func testBiplanarYPlaneToMat() throws {
        let buffer = try XCTUnwrap(Self.make420fPixelBuffer(width: 16, height: 16, y: 40))
        let result = try XCTUnwrap(OpenCVBridge.processPixelBuffer(buffer))
        XCTAssertTrue(result.ok)
        XCTAssertEqual(result.usedPlaneIndex, 0)
        XCTAssertEqual(result.rows, 16)
        XCTAssertEqual(result.cols, 16)
        XCTAssertEqual(result.meanIntensity, 40, accuracy: 1.0)
        XCTAssertTrue(result.zeroCopy)
    }

    func testUnsupportedPixelLayoutDoesNotCrash() throws {
        let buffer = try XCTUnwrap(Self.make32BGRAPixelBuffer(width: 8, height: 8))
        let result = try XCTUnwrap(OpenCVBridge.processPixelBuffer(buffer))
        XCTAssertFalse(result.ok)
        XCTAssertEqual(result.status, "unsupported")
        XCTAssertNotNil(result.error)
    }

    func testSIFTCreateAvailableWithoutExtraction() {
        XCTAssertTrue(OpenCVBridge.siftCreateAvailable())
    }

    func testSolvePnPRansacLinked() {
        XCTAssertTrue(OpenCVBridge.solvePnPRansacLinked())
    }

    func testIntrinsicsValidationHelper() {
        var matrix = simd_float3x3(0)
        matrix.columns.0 = SIMD3<Float>(1200, 0, 0)
        matrix.columns.1 = SIMD3<Float>(0, 1200, 0)
        matrix.columns.2 = SIMD3<Float>(640, 360, 1)
        let valid = CameraIntrinsicsValidator.make(
            cameraMatrix: matrix,
            imageResolution: CGSize(width: 1280, height: 720),
            capturedWidth: 1920,
            capturedHeight: 1440
        )
        XCTAssertTrue(valid.isValid)
        XCTAssertEqual(valid.fx, 1200, accuracy: 0.001)
        XCTAssertEqual(valid.cx, 640, accuracy: 0.001)

        var bad = matrix
        bad.columns.0.x = -1
        let invalid = CameraIntrinsicsValidator.make(
            cameraMatrix: bad,
            imageResolution: CGSize(width: 1280, height: 720),
            capturedWidth: 1920,
            capturedHeight: 1440
        )
        XCTAssertFalse(invalid.isValid)
    }

    private static func makeGrayPixelBuffer(width: Int, height: Int, value: UInt8) -> CVPixelBuffer? {
        var buffer: CVPixelBuffer?
        let status = CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_OneComponent8,
            nil,
            &buffer
        )
        guard status == kCVReturnSuccess, let buffer else { return nil }
        CVPixelBufferLockBaseAddress(buffer, [])
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        if let base = CVPixelBufferGetBaseAddress(buffer) {
            for row in 0..<height {
                memset(base.advanced(by: row * stride), Int32(value), width)
            }
        }
        CVPixelBufferUnlockBaseAddress(buffer, [])
        return buffer
    }

    private static func make420fPixelBuffer(width: Int, height: Int, y: UInt8) -> CVPixelBuffer? {
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
        CVPixelBufferLockBaseAddress(buffer, [])
        let yStride = CVPixelBufferGetBytesPerRowOfPlane(buffer, 0)
        if let yBase = CVPixelBufferGetBaseAddressOfPlane(buffer, 0) {
            for row in 0..<height {
                memset(yBase.advanced(by: row * yStride), Int32(y), width)
            }
        }
        CVPixelBufferUnlockBaseAddress(buffer, [])
        return buffer
    }

    private static func make32BGRAPixelBuffer(width: Int, height: Int) -> CVPixelBuffer? {
        var buffer: CVPixelBuffer?
        let status = CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_32BGRA,
            nil,
            &buffer
        )
        guard status == kCVReturnSuccess, let buffer else { return nil }
        return buffer
    }
}
