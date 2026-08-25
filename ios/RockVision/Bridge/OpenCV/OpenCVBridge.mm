#import "OpenCVBridge.h"

#import <CoreVideo/CoreVideo.h>

#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/features2d.hpp>
#include <opencv2/calib3d.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <limits>
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

@implementation OpenCVKNNResult
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
    if (!descriptors.empty() && descriptors.type() == CV_32F && descriptors.data != nullptr) {
        cv::Mat contiguous = descriptors.isContinuous() ? descriptors : descriptors.clone();
        out.descriptorData = [NSData dataWithBytes:contiguous.ptr<float>(0)
                                            length:(NSUInteger)contiguous.total() * sizeof(float)];
    }
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

namespace {

OpenCVKNNResult *RVKNNEmpty(int queryCount, int k, NSString *error, BOOL ok) {
    OpenCVKNNResult *out = [OpenCVKNNResult new];
    out.ok = ok;
    out.error = error;
    out.queryCount = queryCount;
    out.k = k;
    const int cells = std::max(0, queryCount) * std::max(0, k);
    std::vector<int32_t> indices((size_t)cells, -1);
    std::vector<float> distances((size_t)cells, std::numeric_limits<float>::infinity());
    out.indicesInt32 = [NSData dataWithBytes:indices.data() length:(NSUInteger)cells * sizeof(int32_t)];
    out.distancesFloat32 = [NSData dataWithBytes:distances.data() length:(NSUInteger)cells * sizeof(float)];
    return out;
}

}  // namespace

@implementation OpenCVBridge (Matching)

+ (OpenCVKNNResult *)knnMatchL2QueryDescriptors:(NSData *)query
                           referenceDescriptors:(NSData *)reference
                                  descriptorDim:(int)dim
                                              k:(int)k {
    const int rowBytes = dim > 0 ? dim * (int)sizeof(float) : 0;
    const int qn = (query != nil && rowBytes > 0 && (int)query.length % rowBytes == 0) ? (int)query.length / rowBytes : 0;
    const int rn = (reference != nil && rowBytes > 0 && (int)reference.length % rowBytes == 0) ? (int)reference.length / rowBytes : 0;
    if (dim <= 0 || k < 0) {
        return RVKNNEmpty(0, 0, @"invalid knn dimensions", NO);
    }
    if (query != nil && rowBytes > 0 && (int)query.length % rowBytes != 0) {
        return RVKNNEmpty(0, k, @"query descriptor bytes not a multiple of dim", NO);
    }
    if (reference != nil && rowBytes > 0 && (int)reference.length % rowBytes != 0) {
        return RVKNNEmpty(qn, k, @"reference descriptor bytes not a multiple of dim", NO);
    }
    if (qn == 0 || rn == 0 || k == 0) {
        return RVKNNEmpty(qn, k, nil, YES);
    }
    try {
        cv::Mat qMat(qn, dim, CV_32F, const_cast<void *>(query.bytes));
        cv::Mat rMat(rn, dim, CV_32F, const_cast<void *>(reference.bytes));
        cv::Mat q = qMat.isContinuous() ? qMat : qMat.clone();
        cv::Mat r = rMat.isContinuous() ? rMat : rMat.clone();
        cv::BFMatcher matcher(cv::NORM_L2, false);
        const int kk = std::min(k, rn);
        std::vector<std::vector<cv::DMatch>> pairs;
        matcher.knnMatch(q, r, pairs, kk);
        std::vector<int32_t> indices((size_t)qn * (size_t)k, -1);
        std::vector<float> distances((size_t)qn * (size_t)k, std::numeric_limits<float>::infinity());
        for (int qi = 0; qi < qn && qi < (int)pairs.size(); ++qi) {
            const auto &matches = pairs[(size_t)qi];
            const int n = std::min((int)matches.size(), k);
            for (int j = 0; j < n; ++j) {
                const cv::DMatch &m = matches[(size_t)j];
                indices[(size_t)qi * (size_t)k + (size_t)j] = (int32_t)m.trainIdx;
                distances[(size_t)qi * (size_t)k + (size_t)j] = m.distance;
            }
        }
        OpenCVKNNResult *out = [OpenCVKNNResult new];
        out.ok = YES;
        out.queryCount = qn;
        out.k = k;
        out.indicesInt32 = [NSData dataWithBytes:indices.data() length:indices.size() * sizeof(int32_t)];
        out.distancesFloat32 = [NSData dataWithBytes:distances.data() length:distances.size() * sizeof(float)];
        return out;
    } catch (const cv::Exception &ex) {
        return RVKNNEmpty(qn, k, [NSString stringWithFormat:@"knn exception: %s", ex.what()], NO);
    }
}

@end

@implementation OpenCVProjectedPoints
@end
@implementation OpenCVRodriguesResult
@end
@implementation OpenCVPnPResult
@end

namespace {

bool RVParseVec3(NSArray<NSNumber *> *arr, cv::Vec3d &out) {
    if (arr.count != 3) {
        return false;
    }
    out[0] = arr[0].doubleValue;
    out[1] = arr[1].doubleValue;
    out[2] = arr[2].doubleValue;
    return std::isfinite(out[0]) && std::isfinite(out[1]) && std::isfinite(out[2]);
}

bool RVParseMat33(NSArray<NSArray<NSNumber *> *> *arr, cv::Mat &K) {
    if (arr.count != 3) {
        return false;
    }
    K = cv::Mat::zeros(3, 3, CV_64F);
    for (int r = 0; r < 3; ++r) {
        NSArray<NSNumber *> *row = arr[(NSUInteger)r];
        if (row.count != 3) {
            return false;
        }
        for (int c = 0; c < 3; ++c) {
            const double v = row[(NSUInteger)c].doubleValue;
            if (!std::isfinite(v)) {
                return false;
            }
            K.at<double>(r, c) = v;
        }
    }
    return true;
}

bool RVParseObjectPoints(NSArray<NSArray<NSNumber *> *> *arr, std::vector<cv::Point3d> &out) {
    out.clear();
    out.reserve(arr.count);
    for (NSArray<NSNumber *> *item in arr) {
        if (item.count != 3) {
            return false;
        }
        const double x = item[0].doubleValue;
        const double y = item[1].doubleValue;
        const double z = item[2].doubleValue;
        if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
            return false;
        }
        out.emplace_back(x, y, z);
    }
    return true;
}

bool RVParseImagePoints(NSArray<NSArray<NSNumber *> *> *arr, std::vector<cv::Point2d> &out) {
    out.clear();
    out.reserve(arr.count);
    for (NSArray<NSNumber *> *item in arr) {
        if (item.count != 2) {
            return false;
        }
        const double u = item[0].doubleValue;
        const double v = item[1].doubleValue;
        if (!std::isfinite(u) || !std::isfinite(v)) {
            return false;
        }
        out.emplace_back(u, v);
    }
    return true;
}

bool RVParseDist(NSArray<NSNumber *> *arr, cv::Mat &dist) {
    if (arr.count == 0) {
        dist = cv::Mat::zeros(5, 1, CV_64F);
        return true;
    }
    dist = cv::Mat::zeros((int)arr.count, 1, CV_64F);
    for (NSUInteger i = 0; i < arr.count; ++i) {
        const double v = arr[i].doubleValue;
        if (!std::isfinite(v)) {
            return false;
        }
        dist.at<double>((int)i, 0) = v;
    }
    return true;
}

NSArray<NSNumber *> *RVVec3Array(const cv::Mat &m) {
    return @[ @(m.at<double>(0)), @(m.at<double>(1)), @(m.at<double>(2)) ];
}

NSArray<NSArray<NSNumber *> *> *RVMat33Array(const cv::Mat &m) {
    NSMutableArray<NSArray<NSNumber *> *> *rows = [NSMutableArray arrayWithCapacity:3];
    for (int r = 0; r < 3; ++r) {
        [rows addObject:@[ @(m.at<double>(r, 0)), @(m.at<double>(r, 1)), @(m.at<double>(r, 2)) ]];
    }
    return rows;
}

OpenCVPnPResult *RVEmptyPnP(NSString *error, BOOL ok) {
    OpenCVPnPResult *out = [OpenCVPnPResult new];
    out.ok = ok;
    out.error = error;
    out.cvVersion = [NSString stringWithUTF8String:CV_VERSION];
    out.ransacSuccess = NO;
    out.rvecRansac = @[ @0, @0, @0 ];
    out.tvecRansac = @[ @0, @0, @0 ];
    out.rvecRefined = @[ @0, @0, @0 ];
    out.tvecRefined = @[ @0, @0, @0 ];
    out.refineOk = NO;
    out.inlierIndices = @[];
    out.useExtrinsicGuess = false;
    out.iterationsCount = 100;
    out.reprojectionError = 8.0;
    out.confidence = 0.99;
    out.flagsName = @"SOLVEPNP_EPNP";
    out.flagsValue = (int)cv::SOLVEPNP_EPNP;
    out.distortionModel = @"zeros";
    return out;
}

}  // namespace

@implementation OpenCVBridge (PnP)

+ (int)solvePnPFlagsEPNP {
    return (int)cv::SOLVEPNP_EPNP;
}

+ (NSString *)solvePnPBaselineSummary {
    return [NSString stringWithFormat:
            @"useExtrinsicGuess=false iterationsCount=100 reprojectionError=8.0 confidence=0.99 flags=SOLVEPNP_EPNP(%d) distCoeffs=zeros cv=%s",
            (int)cv::SOLVEPNP_EPNP, CV_VERSION];
}

+ (OpenCVProjectedPoints *)projectPointsObjectPoints:(NSArray<NSArray<NSNumber *> *> *)objectPoints
                                                rvec:(NSArray<NSNumber *> *)rvec
                                                tvec:(NSArray<NSNumber *> *)tvec
                                        cameraMatrix:(NSArray<NSArray<NSNumber *> *> *)cameraMatrix
                                          distCoeffs:(NSArray<NSNumber *> *)distCoeffs {
    OpenCVProjectedPoints *out = [OpenCVProjectedPoints new];
    out.ok = NO;
    out.imagePoints = @[];
    std::vector<cv::Point3d> obj;
    cv::Vec3d rv, tv;
    cv::Mat K, dist;
    if (!RVParseObjectPoints(objectPoints, obj) || !RVParseVec3(rvec, rv) || !RVParseVec3(tvec, tv) ||
        !RVParseMat33(cameraMatrix, K) || !RVParseDist(distCoeffs, dist)) {
        out.error = @"invalid projectPoints arguments";
        return out;
    }
    try {
        std::vector<cv::Point2d> img;
        cv::projectPoints(obj, rv, tv, K, dist, img);
        NSMutableArray<NSArray<NSNumber *> *> *points = [NSMutableArray arrayWithCapacity:img.size()];
        for (const auto &p : img) {
            if (!std::isfinite(p.x) || !std::isfinite(p.y)) {
                out.error = @"non-finite projected point";
                return out;
            }
            [points addObject:@[ @(p.x), @(p.y) ]];
        }
        out.ok = YES;
        out.imagePoints = points;
        return out;
    } catch (const cv::Exception &ex) {
        out.error = [NSString stringWithFormat:@"projectPoints exception: %s", ex.what()];
        return out;
    }
}

+ (OpenCVRodriguesResult *)rodriguesRotationFromRvec:(NSArray<NSNumber *> *)rvec {
    OpenCVRodriguesResult *out = [OpenCVRodriguesResult new];
    out.ok = NO;
    cv::Vec3d rv;
    if (!RVParseVec3(rvec, rv)) {
        out.error = @"invalid rvec";
        return out;
    }
    try {
        cv::Mat R;
        cv::Rodrigues(rv, R);
        out.ok = YES;
        out.rotationMatrix = RVMat33Array(R);
        out.rvec = @[ @(rv[0]), @(rv[1]), @(rv[2]) ];
        return out;
    } catch (const cv::Exception &ex) {
        out.error = [NSString stringWithFormat:@"Rodrigues exception: %s", ex.what()];
        return out;
    }
}

+ (OpenCVRodriguesResult *)rodriguesRvecFromRotation:(NSArray<NSArray<NSNumber *> *> *)rotationMatrix {
    OpenCVRodriguesResult *out = [OpenCVRodriguesResult new];
    out.ok = NO;
    cv::Mat R;
    if (!RVParseMat33(rotationMatrix, R)) {
        out.error = @"invalid rotation matrix";
        return out;
    }
    try {
        cv::Mat rvec;
        cv::Rodrigues(R, rvec);
        out.ok = YES;
        out.rotationMatrix = RVMat33Array(R);
        out.rvec = RVVec3Array(rvec);
        return out;
    } catch (const cv::Exception &ex) {
        out.error = [NSString stringWithFormat:@"Rodrigues exception: %s", ex.what()];
        return out;
    }
}

+ (OpenCVPnPResult *)solvePnPRansacThenRefineObjectPoints:(NSArray<NSArray<NSNumber *> *> *)objectPoints
                                              imagePoints:(NSArray<NSArray<NSNumber *> *> *)imagePoints
                                             cameraMatrix:(NSArray<NSArray<NSNumber *> *> *)cameraMatrix
                                               distCoeffs:(NSArray<NSNumber *> *)distCoeffs {
    const int iterations = 100;
    const float reproj = 8.0f;
    const double confidence = 0.99;
    const int flags = (int)cv::SOLVEPNP_EPNP;
    std::vector<cv::Point3d> obj;
    std::vector<cv::Point2d> img;
    cv::Mat K, dist;
    if (!RVParseObjectPoints(objectPoints, obj) || !RVParseImagePoints(imagePoints, img) ||
        !RVParseMat33(cameraMatrix, K) || !RVParseDist(distCoeffs, dist)) {
        return RVEmptyPnP(@"invalid PnP arguments", NO);
    }
    if (obj.size() != img.size()) {
        return RVEmptyPnP(@"object/image count mismatch", NO);
    }
    OpenCVPnPResult *out = RVEmptyPnP(nil, YES);
    out.iterationsCount = iterations;
    out.reprojectionError = reproj;
    out.confidence = confidence;
    out.flagsValue = flags;
    if (obj.size() < 4) {
        out.ok = YES;
        out.ransacSuccess = NO;
        out.error = @"fewer than 4 correspondences";
        return out;
    }
    try {
        cv::Mat rvec, tvec, inliers;
        const bool success = cv::solvePnPRansac(
            obj,
            img,
            K,
            dist,
            rvec,
            tvec,
            false,
            iterations,
            reproj,
            confidence,
            inliers,
            flags
        );
        out.ransacSuccess = success;
        if (rvec.total() >= 3 && tvec.total() >= 3) {
            out.rvecRansac = RVVec3Array(rvec);
            out.tvecRansac = RVVec3Array(tvec);
        }
        NSMutableArray<NSNumber *> *idx = [NSMutableArray array];
        if (!inliers.empty()) {
            for (int i = 0; i < inliers.rows; ++i) {
                const int value = inliers.type() == CV_32S ? inliers.at<int>(i, 0) : (int)inliers.at<double>(i, 0);
                [idx addObject:@(value)];
            }
        }
        out.inlierIndices = idx;
        if (!success) {
            return out;
        }
        std::vector<cv::Point3d> objIn;
        std::vector<cv::Point2d> imgIn;
        objIn.reserve((size_t)idx.count);
        imgIn.reserve((size_t)idx.count);
        for (NSNumber *n in idx) {
            const int i = n.intValue;
            if (i < 0 || i >= (int)obj.size()) {
                continue;
            }
            objIn.push_back(obj[(size_t)i]);
            imgIn.push_back(img[(size_t)i]);
        }
        if (objIn.size() < 4) {
            out.refineOk = NO;
            out.error = @"fewer than 4 RANSAC inliers for RefineLM";
            return out;
        }
        cv::Mat rRef = rvec.clone();
        cv::Mat tRef = tvec.clone();
        try {
            cv::solvePnPRefineLM(objIn, imgIn, K, dist, rRef, tRef);
            if (rRef.total() >= 3 && tRef.total() >= 3 &&
                std::isfinite(rRef.at<double>(0)) && std::isfinite(tRef.at<double>(0))) {
                out.rvecRefined = RVVec3Array(rRef);
                out.tvecRefined = RVVec3Array(tRef);
                out.refineOk = YES;
            } else {
                out.refineOk = NO;
                out.error = @"RefineLM produced non-finite pose";
            }
        } catch (const cv::Exception &ex) {
            out.refineOk = NO;
            out.error = [NSString stringWithFormat:@"RefineLM exception: %s", ex.what()];
        }
        return out;
    } catch (const cv::Exception &ex) {
        out.ok = NO;
        out.ransacSuccess = NO;
        out.error = [NSString stringWithFormat:@"solvePnPRansac exception: %s", ex.what()];
        return out;
    }
}

@end
