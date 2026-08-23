#import <Foundation/Foundation.h>
#import <CoreVideo/CoreVideo.h>

NS_ASSUME_NONNULL_BEGIN

/// Diagnostics from one locked PixelBuffer → cv::Mat pass. No C++ types.
@interface OpenCVFrameDiagnostics : NSObject
@property (nonatomic, assign) BOOL ok;
@property (nonatomic, copy) NSString *status;
@property (nonatomic, copy) NSString *pixelFormat;
@property (nonatomic, assign) int planeCount;
@property (nonatomic, assign) int usedPlaneIndex;
@property (nonatomic, copy) NSString *inputDescription;
@property (nonatomic, assign) int bufferWidth;
@property (nonatomic, assign) int bufferHeight;
@property (nonatomic, assign) int planeWidth;
@property (nonatomic, assign) int planeHeight;
@property (nonatomic, assign) size_t bytesPerRow;
@property (nonatomic, assign) BOOL zeroCopy;
@property (nonatomic, assign) int rows;
@property (nonatomic, assign) int cols;
@property (nonatomic, assign) int matType;
@property (nonatomic, assign) BOOL dataNonNull;
@property (nonatomic, assign) double meanIntensity;
@property (nonatomic, assign) double minIntensity;
@property (nonatomic, assign) double maxIntensity;
@property (nonatomic, assign) double latencyMilliseconds;
@property (nonatomic, copy, nullable) NSString *error;
@end

/// Minimal Objective-C++ facade. Swift must not include OpenCV C++ headers.
/// Decoupled from UI, ARSessionHost, and any localization state machine.
@interface OpenCVBridge : NSObject

+ (NSString *)openCVVersion;
+ (NSString *)openCVBuildSummary;

/// Creates `cv::SIFT` and immediately releases it. Does not extract features.
+ (BOOL)siftCreateAvailable;

/// Compile/link proof only. Does not call solvePnPRansac with points.
+ (BOOL)solvePnPRansacLinked;

/// Lock PixelBuffer, wrap Y plane as grayscale Mat, compute stats, unlock.
/// The returned object never retains PixelBuffer memory.
+ (nullable OpenCVFrameDiagnostics *)processPixelBuffer:(nullable CVPixelBufferRef)pixelBuffer;

@end

/// One SIFT extraction. Descriptors are validated then discarded (not persisted).
@interface OpenCVSIFTResult : NSObject
@property (nonatomic, assign) BOOL ok;
@property (nonatomic, copy) NSString *status;
@property (nonatomic, assign) int nativeWidth;
@property (nonatomic, assign) int nativeHeight;
@property (nonatomic, assign) int processingWidth;
@property (nonatomic, assign) int processingHeight;
@property (nonatomic, assign) double scaleX;
@property (nonatomic, assign) double scaleY;
@property (nonatomic, assign) int keypointCount;
@property (nonatomic, assign) int descriptorRows;
@property (nonatomic, assign) int descriptorCols;
@property (nonatomic, assign) int descriptorTypeCode;
@property (nonatomic, copy) NSString *descriptorTypeName;
@property (nonatomic, assign) BOOL descriptorsFinite;
@property (nonatomic, assign) BOOL rowsMatchKeypoints;
@property (nonatomic, assign) double preprocessMilliseconds;
@property (nonatomic, assign) double siftMilliseconds;
@property (nonatomic, assign) double totalMilliseconds;
@property (nonatomic, copy) NSArray<NSNumber *> *nativeX;
@property (nonatomic, copy) NSArray<NSNumber *> *nativeY;
@property (nonatomic, copy) NSArray<NSNumber *> *overlayNativeX;
@property (nonatomic, copy) NSArray<NSNumber *> *overlayNativeY;
@property (nonatomic, copy, nullable) NSString *error;
@property (nonatomic, copy) NSString *parameterSummary;
@end

@interface OpenCVBridge (SIFT)
+ (NSString *)siftParameterSummary;

/// Extract SIFT from an ARKit PixelBuffer. target 0,0 means native size.
+ (OpenCVSIFTResult *)extractSIFTFromPixelBuffer:(nullable CVPixelBufferRef)pixelBuffer
                                    targetWidth:(int)targetWidth
                                   targetHeight:(int)targetHeight
                                     overlayCap:(int)overlayCap;

/// Test helper: raw 8-bit gray (no PixelBuffer).
+ (OpenCVSIFTResult *)extractSIFTFromGrayBytes:(nullable const uint8_t *)bytes
                                         width:(int)width
                                        height:(int)height
                                        stride:(size_t)stride
                                   targetWidth:(int)targetWidth
                                  targetHeight:(int)targetHeight
                                    overlayCap:(int)overlayCap;
@end

NS_ASSUME_NONNULL_END
