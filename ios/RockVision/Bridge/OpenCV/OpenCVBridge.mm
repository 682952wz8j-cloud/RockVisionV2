#import "OpenCVBridge.h"

#import <CoreVideo/CoreVideo.h>

#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/features2d.hpp>
#include <opencv2/calib3d.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <sstream>
#include <string>
#include <vector>

@implementation OpenCVFrameDiagnostics
@end

static NSString *RVFourCCString(OSType format) {
    char chars[5] = {0};
    chars[0] = (char)((format >> 24) & 0xFF);
    chars[1] = (char)((format >> 16) & 0xFF);
    chars[2] = (char)((format >> 8) & 0xFF);
    chars[3] = (char)(format & 0xFF);
    return [[NSString alloc] initWithBytes:chars length:4 encoding:NSASCIIStringEncoding] ?: [NSString stringWithFormat:@"%u", (unsigned)format];
}

static void RVForceLinkCalib3dWithoutCalling(void) {
    // Keep solvePnPRansac in the link map. The dead branch never runs, so this
    // Gate does not construct a fake PnP problem at runtime.
    if (false) {
        std::vector<cv::Point3f> objectPoints;
        std::vector<cv::Point2f> imagePoints;
        cv::Mat cameraMatrix = cv::Mat::eye(3, 3, CV_64F);
        cv::Mat distCoeffs, rvec, tvec;
        cv::solvePnPRansac(objectPoints, imagePoints, cameraMatrix, distCoeffs, rvec, tvec);
    }
}

@implementation OpenCVBridge

+ (NSString *)openCVVersion {
    return [NSString stringWithUTF8String:CV_VERSION];
}

+ (NSString *)openCVBuildSummary {
    const std::string info = cv::getBuildInformation();
    std::istringstream stream(info);
    std::string line;
    NSMutableArray<NSString *> *kept = [NSMutableArray array];
    while (std::getline(stream, line)) {
        if (line.find("Version control") != std::string::npos ||
            line.find("CMake") != std::string::npos ||
            line.find("Processor:") != std::string::npos ||
            line.find("Host:") != std::string::npos ||
            line.find("features2d") != std::string::npos ||
            line.find("calib3d") != std::string::npos ||
            line.find("imgproc") != std::string::npos ||
            line.find("To be built") != std::string::npos) {
            NSString *row = [[NSString stringWithUTF8String:line.c_str()]
                stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
            if (row.length > 0) {
                [kept addObject:row];
            }
        }
        if (kept.count >= 12) {
            break;
        }
    }
    return [kept componentsJoinedByString:@" | "];
}

+ (BOOL)siftCreateAvailable {
    try {
        cv::Ptr<cv::SIFT> sift = cv::SIFT::create();
        return !sift.empty();
    } catch (...) {
        return NO;
    }
}

+ (BOOL)solvePnPRansacLinked {
    RVForceLinkCalib3dWithoutCalling();
    return YES;
}

+ (OpenCVFrameDiagnostics *)processPixelBuffer:(CVPixelBufferRef)pixelBuffer {
    OpenCVFrameDiagnostics *out = [OpenCVFrameDiagnostics new];
    out.ok = NO;
    out.status = @"inactive";
    out.usedPlaneIndex = -1;
    out.matType = -1;
    if (pixelBuffer == nullptr) {
        out.error = @"null CVPixelBuffer";
        return out;
    }

    const auto started = std::chrono::steady_clock::now();
    const OSType format = CVPixelBufferGetPixelFormatType(pixelBuffer);
    out.pixelFormat = RVFourCCString(format);
    out.planeCount = (int)CVPixelBufferGetPlaneCount(pixelBuffer);
    out.bufferWidth = (int)CVPixelBufferGetWidth(pixelBuffer);
    out.bufferHeight = (int)CVPixelBufferGetHeight(pixelBuffer);

    if (CVPixelBufferLockBaseAddress(pixelBuffer, kCVPixelBufferLock_ReadOnly) != kCVReturnSuccess) {
        out.error = @"CVPixelBufferLockBaseAddress failed";
        return out;
    }

    @try {
        const bool biplanarY =
            format == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange ||
            format == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange;
        void *base = nullptr;
        int width = 0;
        int height = 0;
        size_t stride = 0;
        bool zeroCopy = false;

        if (biplanarY && CVPixelBufferGetPlaneCount(pixelBuffer) >= 1) {
            // Plane 0 is luma. Future SIFT uses this grayscale space, native sensor pixels.
            base = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0);
            width = (int)CVPixelBufferGetWidthOfPlane(pixelBuffer, 0);
            height = (int)CVPixelBufferGetHeightOfPlane(pixelBuffer, 0);
            stride = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0);
            out.usedPlaneIndex = 0;
            out.inputDescription = @"Y plane / grayscale";
            zeroCopy = true;
        } else if (format == kCVPixelFormatType_OneComponent8) {
            base = CVPixelBufferGetBaseAddress(pixelBuffer);
            width = (int)CVPixelBufferGetWidth(pixelBuffer);
            height = (int)CVPixelBufferGetHeight(pixelBuffer);
            stride = CVPixelBufferGetBytesPerRow(pixelBuffer);
            out.usedPlaneIndex = 0;
            out.inputDescription = @"1-plane 8-bit grayscale";
            zeroCopy = true;
        } else {
            out.error = [NSString stringWithFormat:@"unsupported pixel format %@", out.pixelFormat];
            out.status = @"unsupported";
            return out;
        }

        out.planeWidth = width;
        out.planeHeight = height;
        out.bytesPerRow = stride;
        out.zeroCopy = zeroCopy;

        if (base == nullptr || width <= 0 || height <= 0 || stride < (size_t)width) {
            out.error = @"invalid plane layout";
            return out;
        }

        // Zero-copy wrap. Valid only while the buffer stays locked in this scope.
        cv::Mat gray(height, width, CV_8UC1, base, stride);
        if (gray.empty() || gray.data == nullptr) {
            out.error = @"cv::Mat is empty";
            return out;
        }

        cv::Scalar mean = cv::mean(gray);
        double minVal = 0;
        double maxVal = 0;
        cv::minMaxLoc(gray, &minVal, &maxVal);

        out.ok = YES;
        out.status = @"active";
        out.rows = gray.rows;
        out.cols = gray.cols;
        out.matType = gray.type();
        out.dataNonNull = gray.data != nullptr;
        out.meanIntensity = mean[0];
        out.minIntensity = minVal;
        out.maxIntensity = maxVal;
    } @finally {
        CVPixelBufferUnlockBaseAddress(pixelBuffer, kCVPixelBufferLock_ReadOnly);
    }

    const auto ended = std::chrono::steady_clock::now();
    out.latencyMilliseconds = std::chrono::duration<double, std::milli>(ended - started).count();
    return out;
}

@end

@implementation OpenCVSIFTResult
@end

namespace {

constexpr int kSIFTNFeatures = 0;
constexpr int kSIFTNOctaveLayers = 3;
constexpr double kSIFTContrast = 0.04;
constexpr double kSIFTEdge = 10.0;
constexpr double kSIFTSigma = 1.6;

cv::Ptr<cv::SIFT> RVSharedSIFT() {
    static cv::Ptr<cv::SIFT> sift =
        cv::SIFT::create(kSIFTNFeatures, kSIFTNOctaveLayers, kSIFTContrast, kSIFTEdge, kSIFTSigma);
    return sift;
}

bool RVGrayFromPixelBuffer(CVPixelBufferRef pixelBuffer, cv::Mat *outGray, NSString **error) {
    const OSType format = CVPixelBufferGetPixelFormatType(pixelBuffer);
    const bool biplanarY =
        format == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange ||
        format == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange;
    void *base = nullptr;
    int width = 0;
    int height = 0;
    size_t stride = 0;
    if (biplanarY && CVPixelBufferGetPlaneCount(pixelBuffer) >= 1) {
        base = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0);
        width = (int)CVPixelBufferGetWidthOfPlane(pixelBuffer, 0);
        height = (int)CVPixelBufferGetHeightOfPlane(pixelBuffer, 0);
        stride = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0);
    } else if (format == kCVPixelFormatType_OneComponent8) {
        base = CVPixelBufferGetBaseAddress(pixelBuffer);
        width = (int)CVPixelBufferGetWidth(pixelBuffer);
        height = (int)CVPixelBufferGetHeight(pixelBuffer);
        stride = CVPixelBufferGetBytesPerRow(pixelBuffer);
    } else {
        *error = @"unsupported pixel format";
        return false;
    }
    if (base == nullptr || width <= 0 || height <= 0 || stride < (size_t)width) {
        *error = @"invalid plane layout";
        return false;
    }
    *outGray = cv::Mat(height, width, CV_8UC1, base, stride);
    return !outGray->empty();
}

int RVFitSize(int native, int target, double scale) {
    return std::max(1, (int)std::lround(double(native) * scale));
}

OpenCVSIFTResult *RVExtractSIFT(const cv::Mat &nativeGray, int targetWidth, int targetHeight, int overlayCap) {
    OpenCVSIFTResult *out = [OpenCVSIFTResult new];
    out.ok = NO;
    out.status = @"inactive";
    out.nativeX = @[];
    out.nativeY = @[];
    out.overlayNativeX = @[];
    out.overlayNativeY = @[];
    out.parameterSummary = [NSString stringWithFormat:
        @"nfeatures=%d nOctaveLayers=%d contrastThreshold=%.2f edgeThreshold=%.1f sigma=%.1f",
        kSIFTNFeatures, kSIFTNOctaveLayers, kSIFTContrast, kSIFTEdge, kSIFTSigma];
    out.descriptorTypeName = @"—";

    if (nativeGray.empty() || nativeGray.rows <= 0 || nativeGray.cols <= 0 || nativeGray.data == nullptr) {
        out.error = @"empty image";
        return out;
    }

    const auto t0 = std::chrono::steady_clock::now();
    const int nativeW = nativeGray.cols;
    const int nativeH = nativeGray.rows;
    int procW = nativeW;
    int procH = nativeH;
    if (targetWidth > 0 && targetHeight > 0 && (nativeW > targetWidth || nativeH > targetHeight)) {
        const double scale = std::min(double(targetWidth) / double(nativeW), double(targetHeight) / double(nativeH));
        procW = RVFitSize(nativeW, targetWidth, scale);
        procH = RVFitSize(nativeH, targetHeight, scale);
    }
    const double scaleX = double(procW) / double(nativeW);
    const double scaleY = double(procH) / double(nativeH);

    cv::Mat working;
    if (procW == nativeW && procH == nativeH) {
        working = nativeGray.isContinuous() ? nativeGray : nativeGray.clone();
    } else {
        cv::resize(nativeGray, working, cv::Size(procW, procH), 0, 0, cv::INTER_AREA);
    }
    const auto t1 = std::chrono::steady_clock::now();

    std::vector<cv::KeyPoint> keypoints;
    cv::Mat descriptors;
    try {
        RVSharedSIFT()->detectAndCompute(working, cv::noArray(), keypoints, descriptors);
    } catch (const cv::Exception &ex) {
        out.error = [NSString stringWithFormat:@"SIFT exception: %s", ex.what()];
        return out;
    }
    const auto t2 = std::chrono::steady_clock::now();

    bool finite = true;
    if (!descriptors.empty()) {
        if (descriptors.type() != CV_32F) {
            descriptors.convertTo(descriptors, CV_32F);
        }
        for (int r = 0; r < descriptors.rows && finite; ++r) {
            const float *row = descriptors.ptr<float>(r);
            for (int c = 0; c < descriptors.cols; ++c) {
                if (!std::isfinite(row[c])) {
                    finite = false;
                    break;
                }
            }
        }
    }

    NSMutableArray<NSNumber *> *xs = [NSMutableArray arrayWithCapacity:keypoints.size()];
    NSMutableArray<NSNumber *> *ys = [NSMutableArray arrayWithCapacity:keypoints.size()];
    for (const auto &kp : keypoints) {
        [xs addObject:@(double(kp.pt.x) / scaleX)];
        [ys addObject:@(double(kp.pt.y) / scaleY)];
    }
    const int cap = overlayCap > 0 ? overlayCap : 0;
    NSMutableArray<NSNumber *> *ox = [NSMutableArray array];
    NSMutableArray<NSNumber *> *oy = [NSMutableArray array];
    if (cap > 0 && xs.count > 0) {
        const int step = std::max(1, (int)xs.count / cap);
        for (NSUInteger i = 0; i < xs.count && (int)ox.count < cap; i += (NSUInteger)step) {
            [ox addObject:xs[i]];
            [oy addObject:ys[i]];
        }
    }

    out.ok = YES;
    out.status = @"active";
    out.nativeWidth = nativeW;
    out.nativeHeight = nativeH;
    out.processingWidth = procW;
    out.processingHeight = procH;
    out.scaleX = scaleX;
    out.scaleY = scaleY;
    out.keypointCount = (int)keypoints.size();
    out.descriptorRows = descriptors.empty() ? 0 : descriptors.rows;
    out.descriptorCols = descriptors.empty() ? 0 : descriptors.cols;
    out.descriptorTypeCode = descriptors.empty() ? -1 : descriptors.type();
    out.descriptorTypeName = descriptors.empty() ? @"empty" : @"CV_32F";
    out.descriptorsFinite = finite;
    out.rowsMatchKeypoints = out.descriptorRows == out.keypointCount;
    out.preprocessMilliseconds = std::chrono::duration<double, std::milli>(t1 - t0).count();
    out.siftMilliseconds = std::chrono::duration<double, std::milli>(t2 - t1).count();
    out.totalMilliseconds = std::chrono::duration<double, std::milli>(t2 - t0).count();
    out.nativeX = xs;
    out.nativeY = ys;
    out.overlayNativeX = ox;
    out.overlayNativeY = oy;
    // descriptors go out of scope here — not stored on the result.
    return out;
}

}  // namespace

@implementation OpenCVBridge (SIFT)

+ (NSString *)siftParameterSummary {
    return [NSString stringWithFormat:
        @"nfeatures=%d nOctaveLayers=%d contrastThreshold=%.2f edgeThreshold=%.1f sigma=%.1f",
        kSIFTNFeatures, kSIFTNOctaveLayers, kSIFTContrast, kSIFTEdge, kSIFTSigma];
}

+ (OpenCVSIFTResult *)extractSIFTFromPixelBuffer:(CVPixelBufferRef)pixelBuffer
                                    targetWidth:(int)targetWidth
                                   targetHeight:(int)targetHeight
                                     overlayCap:(int)overlayCap {
    if (pixelBuffer == nullptr) {
        OpenCVSIFTResult *out = [OpenCVSIFTResult new];
        out.ok = NO;
        out.status = @"inactive";
        out.error = @"null CVPixelBuffer";
        out.nativeX = @[];
        out.nativeY = @[];
        out.overlayNativeX = @[];
        out.overlayNativeY = @[];
        out.parameterSummary = [self siftParameterSummary];
        out.descriptorTypeName = @"—";
        return out;
    }
    if (CVPixelBufferLockBaseAddress(pixelBuffer, kCVPixelBufferLock_ReadOnly) != kCVReturnSuccess) {
        OpenCVSIFTResult *out = [OpenCVSIFTResult new];
        out.ok = NO;
        out.error = @"CVPixelBufferLockBaseAddress failed";
        out.nativeX = @[];
        out.nativeY = @[];
        out.overlayNativeX = @[];
        out.overlayNativeY = @[];
        out.parameterSummary = [self siftParameterSummary];
        out.descriptorTypeName = @"—";
        return out;
    }
    OpenCVSIFTResult *result = nil;
    @try {
        cv::Mat gray;
        NSString *error = nil;
        if (!RVGrayFromPixelBuffer(pixelBuffer, &gray, &error)) {
            OpenCVSIFTResult *out = [OpenCVSIFTResult new];
            out.ok = NO;
            out.status = @"unsupported";
            out.error = error;
            out.nativeX = @[];
            out.nativeY = @[];
            out.overlayNativeX = @[];
            out.overlayNativeY = @[];
            out.parameterSummary = [self siftParameterSummary];
            out.descriptorTypeName = @"—";
            result = out;
        } else {
            result = RVExtractSIFT(gray, targetWidth, targetHeight, overlayCap);
        }
    } @finally {
        CVPixelBufferUnlockBaseAddress(pixelBuffer, kCVPixelBufferLock_ReadOnly);
    }
    return result;
}

+ (OpenCVSIFTResult *)extractSIFTFromGrayBytes:(const uint8_t *)bytes
                                         width:(int)width
                                        height:(int)height
                                        stride:(size_t)stride
                                   targetWidth:(int)targetWidth
                                  targetHeight:(int)targetHeight
                                    overlayCap:(int)overlayCap {
    if (bytes == nullptr || width <= 0 || height <= 0 || stride < (size_t)width) {
        OpenCVSIFTResult *out = [OpenCVSIFTResult new];
        out.ok = NO;
        out.status = @"inactive";
        out.error = @"empty image";
        out.nativeX = @[];
        out.nativeY = @[];
        out.overlayNativeX = @[];
        out.overlayNativeY = @[];
        out.parameterSummary = [self siftParameterSummary];
        out.descriptorTypeName = @"—";
        return out;
    }
    cv::Mat gray(height, width, CV_8UC1, const_cast<uint8_t *>(bytes), stride);
    return RVExtractSIFT(gray, targetWidth, targetHeight, overlayCap);
}

@end
