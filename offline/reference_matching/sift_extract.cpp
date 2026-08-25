// Native-resolution OpenCV SIFT extractor linked against the pinned 4.14.0 Mac build.
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/features2d.hpp>

#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

constexpr int kNFeatures = 0;
constexpr int kNOctaveLayers = 3;
constexpr double kContrast = 0.04;
constexpr double kEdge = 10.0;
constexpr double kSigma = 1.6;
constexpr uint32_t kDim = 128;

bool write_u32(std::ofstream &out, uint32_t value) {
    return static_cast<bool>(out.write(reinterpret_cast<const char *>(&value), sizeof(value)));
}

int print_version() {
    std::cout << "cvVersion=" << CV_VERSION << "\n";
    std::cout << "cvMajor=" << CV_VERSION_MAJOR << "\n";
    std::cout << "cvMinor=" << CV_VERSION_MINOR << "\n";
    std::cout << "cvRevision=" << CV_VERSION_REVISION << "\n";
    const std::string info = cv::getBuildInformation();
    std::istringstream stream(info);
    std::string line;
    while (std::getline(stream, line)) {
        if (line.find("Version control") != std::string::npos ||
            line.find("To be built") != std::string::npos ||
            line.find("features2d") != std::string::npos) {
            std::cout << line << "\n";
        }
    }
    return std::string(CV_VERSION) == "4.14.0" ? 0 : 1;
}

int extract(const std::string &input, const std::string &output) {
    cv::Mat bgr = cv::imread(input, cv::IMREAD_COLOR);
    if (bgr.empty()) {
        std::cerr << "STOP: OpenCV failed to read " << input << "\n";
        return 2;
    }
    cv::Mat gray;
    cv::cvtColor(bgr, gray, cv::COLOR_BGR2GRAY);
    auto sift = cv::SIFT::create(kNFeatures, kNOctaveLayers, kContrast, kEdge, kSigma);
    std::vector<cv::KeyPoint> keypoints;
    cv::Mat descriptors;
    sift->detectAndCompute(gray, cv::noArray(), keypoints, descriptors);
    if (descriptors.empty()) {
        descriptors = cv::Mat(0, kDim, CV_32F);
    }
    if (descriptors.type() != CV_32F) {
        descriptors.convertTo(descriptors, CV_32F);
    }
    if (static_cast<uint32_t>(descriptors.cols) != kDim && descriptors.rows > 0) {
        std::cerr << "STOP: descriptor dim " << descriptors.cols << " != 128\n";
        return 3;
    }
    if (descriptors.rows != static_cast<int>(keypoints.size())) {
        std::cerr << "STOP: descriptor rows != keypoints\n";
        return 3;
    }
    for (int r = 0; r < descriptors.rows; ++r) {
        const float *row = descriptors.ptr<float>(r);
        for (int c = 0; c < descriptors.cols; ++c) {
            if (!std::isfinite(row[c])) {
                std::cerr << "STOP: non-finite descriptor\n";
                return 3;
            }
        }
    }

    std::ofstream out(output, std::ios::binary);
    if (!out) {
        std::cerr << "STOP: cannot write " << output << "\n";
        return 2;
    }
    out.write("RVE1", 4);
    write_u32(out, 1);
    write_u32(out, static_cast<uint32_t>(bgr.cols));
    write_u32(out, static_cast<uint32_t>(bgr.rows));
    write_u32(out, static_cast<uint32_t>(keypoints.size()));
    write_u32(out, kDim);
    for (const auto &kp : keypoints) {
        const double xy[2] = {static_cast<double>(kp.pt.x), static_cast<double>(kp.pt.y)};
        out.write(reinterpret_cast<const char *>(xy), sizeof(xy));
    }
    if (descriptors.rows > 0) {
        cv::Mat contiguous = descriptors.isContinuous() ? descriptors : descriptors.clone();
        out.write(reinterpret_cast<const char *>(contiguous.ptr<float>(0)),
                  static_cast<std::streamsize>(contiguous.total() * sizeof(float)));
    }
    if (!out) {
        std::cerr << "STOP: write failed\n";
        return 2;
    }
    std::cout << "width=" << bgr.cols << " height=" << bgr.rows << " keypoints=" << keypoints.size() << "\n";
    return 0;
}

}  // namespace

int main(int argc, char **argv) {
    if (argc == 2 && std::string(argv[1]) == "--version") {
        return print_version();
    }
    if (argc != 3) {
        std::cerr << "usage: rv_sift_extract --version | <input.jpg> <output.rve1>\n";
        return 1;
    }
    return extract(argv[1], argv[2]);
}
