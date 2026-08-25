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

/// One SIFT extraction. Descriptors are copied as row-major float32 NSData; the C++ Mat is released.
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
@property (nonatomic, copy, nullable) NSData *descriptorData;
@property (nonatomic, copy, nullable) NSString *error;
@property (nonatomic, copy) NSString *parameterSummary;
@end

/// Packed BFMatcher KNN. indicesInt32 is queryCount * k little-endian int32 (-1 pad).
/// distancesFloat32 is queryCount * k little-endian float32 (+inf pad).
@interface OpenCVKNNResult : NSObject
@property (nonatomic, assign) BOOL ok;
@property (nonatomic, copy, nullable) NSString *error;
@property (nonatomic, assign) int queryCount;
@property (nonatomic, assign) int k;
@property (nonatomic, copy) NSData *indicesInt32;
@property (nonatomic, copy) NSData *distancesFloat32;
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

@interface OpenCVBridge (Matching)
/// OpenCV BFMatcher NORM_L2, crossCheck=NO, k neighbors. Grouping / ratio stay in Swift.
+ (OpenCVKNNResult *)knnMatchL2QueryDescriptors:(nullable NSData *)query
                           referenceDescriptors:(nullable NSData *)reference
                                  descriptorDim:(int)dim
                                              k:(int)k
    NS_SWIFT_NAME(knnMatchL2(queryDescriptors:referenceDescriptors:descriptorDim:k:));
@end

@interface OpenCVProjectedPoints : NSObject
@property (nonatomic, assign) BOOL ok;
@property (nonatomic, copy, nullable) NSString *error;
@property (nonatomic, copy) NSArray<NSArray<NSNumber *> *> *imagePoints;
@end

@interface OpenCVRodriguesResult : NSObject
@property (nonatomic, assign) BOOL ok;
@property (nonatomic, copy, nullable) NSString *error;
@property (nonatomic, copy) NSArray<NSArray<NSNumber *> *> *rotationMatrix;
@property (nonatomic, copy) NSArray<NSNumber *> *rvec;
@end

@interface OpenCVPnPResult : NSObject
@property (nonatomic, assign) BOOL ok;
@property (nonatomic, copy, nullable) NSString *error;
@property (nonatomic, copy) NSString *cvVersion;
@property (nonatomic, assign) BOOL ransacSuccess;
@property (nonatomic, copy) NSArray<NSNumber *> *rvecRansac;
@property (nonatomic, copy) NSArray<NSNumber *> *tvecRansac;
@property (nonatomic, copy) NSArray<NSNumber *> *rvecRefined;
@property (nonatomic, copy) NSArray<NSNumber *> *tvecRefined;
@property (nonatomic, assign) BOOL refineOk;
@property (nonatomic, copy) NSArray<NSNumber *> *inlierIndices;
@property (nonatomic, assign) BOOL useExtrinsicGuess;
@property (nonatomic, assign) int iterationsCount;
@property (nonatomic, assign) double reprojectionError;
@property (nonatomic, assign) double confidence;
@property (nonatomic, copy) NSString *flagsName;
@property (nonatomic, assign) int flagsValue;
@property (nonatomic, copy) NSString *distortionModel;
@end

@interface OpenCVBridge (PnP)
+ (int)solvePnPFlagsEPNP;
+ (NSString *)solvePnPBaselineSummary;

+ (OpenCVProjectedPoints *)projectPointsObjectPoints:(NSArray<NSArray<NSNumber *> *> *)objectPoints
                                                rvec:(NSArray<NSNumber *> *)rvec
                                                tvec:(NSArray<NSNumber *> *)tvec
                                        cameraMatrix:(NSArray<NSArray<NSNumber *> *> *)cameraMatrix
                                          distCoeffs:(NSArray<NSNumber *> *)distCoeffs
    NS_SWIFT_NAME(projectPoints(objectPoints:rvec:tvec:cameraMatrix:distCoeffs:));

+ (OpenCVRodriguesResult *)rodriguesRotationFromRvec:(NSArray<NSNumber *> *)rvec
    NS_SWIFT_NAME(rodriguesRotation(fromRvec:));

+ (OpenCVRodriguesResult *)rodriguesRvecFromRotation:(NSArray<NSArray<NSNumber *> *> *)rotationMatrix
    NS_SWIFT_NAME(rodriguesRvec(fromRotation:));

/// Frozen Gate 3D baseline: EPNP + RANSAC, then RefineLM on RANSAC inliers only.
+ (OpenCVPnPResult *)solvePnPRansacThenRefineObjectPoints:(NSArray<NSArray<NSNumber *> *> *)objectPoints
                                              imagePoints:(NSArray<NSArray<NSNumber *> *> *)imagePoints
                                             cameraMatrix:(NSArray<NSArray<NSNumber *> *> *)cameraMatrix
                                               distCoeffs:(NSArray<NSNumber *> *)distCoeffs
    NS_SWIFT_NAME(solvePnPRansacThenRefine(objectPoints:imagePoints:cameraMatrix:distCoeffs:));
@end

NS_ASSUME_NONNULL_END
