// Gate 3D PnP CLI linked against pinned OpenCV 4.14.0. Never uses Python cv2.
#include <opencv2/core.hpp>
#include <opencv2/calib3d.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <tuple>
#include <vector>

namespace {

constexpr bool kUseExtrinsicGuess = false;
constexpr int kIterations = 100;
constexpr float kReprojErr = 8.0f;
constexpr double kConfidence = 0.99;
constexpr int kFlags = cv::SOLVEPNP_EPNP;

struct Reproj {
    double mean = 0;
    double median = 0;
    double p90 = 0;
    double max = 0;
    int count = 0;
};

double percentile(std::vector<double> values, double p) {
    if (values.empty()) {
        return 0;
    }
    std::sort(values.begin(), values.end());
    const size_t idx = std::min(values.size() - 1, static_cast<size_t>((p / 100.0) * (values.size() - 1)));
    return values[idx];
}

cv::Mat rotation_from_rvec(const cv::Mat &rvec) {
    cv::Mat R;
    cv::Rodrigues(rvec, R);
    return R;
}

cv::Vec3d camera_center(const cv::Mat &R, const cv::Mat &t) {
    const cv::Mat c = -R.t() * t;
    return cv::Vec3d(c.at<double>(0), c.at<double>(1), c.at<double>(2));
}

double rotation_angle_deg(const cv::Mat &Rest, const cv::Mat &Rgt) {
    const cv::Mat err = Rest * Rgt.t();
    const double tr = err.at<double>(0, 0) + err.at<double>(1, 1) + err.at<double>(2, 2);
    const double c = std::max(-1.0, std::min(1.0, (tr - 1.0) * 0.5));
    return std::acos(c) * 180.0 / CV_PI;
}

Reproj reprojection(
    const std::vector<cv::Point3d> &obj,
    const std::vector<cv::Point2d> &img,
    const std::vector<int> &inliers,
    const cv::Mat &rvec,
    const cv::Mat &tvec,
    const cv::Mat &K,
    const cv::Mat &dist
) {
    std::vector<cv::Point3d> o;
    std::vector<cv::Point2d> observed;
    for (int idx : inliers) {
        if (idx < 0 || idx >= static_cast<int>(obj.size())) {
            continue;
        }
        o.push_back(obj[static_cast<size_t>(idx)]);
        observed.push_back(img[static_cast<size_t>(idx)]);
    }
    Reproj out;
    out.count = static_cast<int>(o.size());
    if (o.empty()) {
        return out;
    }
    std::vector<cv::Point2d> projected;
    cv::projectPoints(o, rvec, tvec, K, dist, projected);
    std::vector<double> errors;
    errors.reserve(projected.size());
    double sum = 0;
    double mx = 0;
    for (size_t i = 0; i < projected.size(); ++i) {
        const double du = projected[i].x - observed[i].x;
        const double dv = projected[i].y - observed[i].y;
        const double e = std::sqrt(du * du + dv * dv);
        errors.push_back(e);
        sum += e;
        mx = std::max(mx, e);
    }
    out.mean = sum / static_cast<double>(errors.size());
    out.median = percentile(errors, 50);
    out.p90 = percentile(errors, 90);
    out.max = mx;
    return out;
}

struct Cheirality {
    int positive = 0;
    int count = 0;
    double ratio = 0;
    double medianZ = 0;
};

Cheirality cheirality(
    const std::vector<cv::Point3d> &obj,
    const std::vector<int> &inliers,
    const cv::Mat &R,
    const cv::Mat &t
) {
    std::vector<double> zs;
    Cheirality out;
    for (int idx : inliers) {
        if (idx < 0 || idx >= static_cast<int>(obj.size())) {
            continue;
        }
        const cv::Mat X = (cv::Mat_<double>(3, 1) << obj[static_cast<size_t>(idx)].x, obj[static_cast<size_t>(idx)].y, obj[static_cast<size_t>(idx)].z);
        const cv::Mat Xc = R * X + t;
        const double z = Xc.at<double>(2);
        zs.push_back(z);
        if (z > 0) {
            ++out.positive;
        }
    }
    out.count = static_cast<int>(zs.size());
    out.ratio = out.count == 0 ? 0 : static_cast<double>(out.positive) / static_cast<double>(out.count);
    out.medianZ = percentile(zs, 50);
    return out;
}

void emit_vec3(std::ostream &o, const cv::Mat &m) {
    o << "[" << m.at<double>(0) << ", " << m.at<double>(1) << ", " << m.at<double>(2) << "]";
}

void emit_mat33(std::ostream &o, const cv::Mat &m) {
    o << "[";
    for (int r = 0; r < 3; ++r) {
        if (r) {
            o << ", ";
        }
        o << "[" << m.at<double>(r, 0) << ", " << m.at<double>(r, 1) << ", " << m.at<double>(r, 2) << "]";
    }
    o << "]";
}

void emit_T(std::ostream &o, const cv::Mat &R, const cv::Mat &t) {
    o << "[";
    for (int r = 0; r < 3; ++r) {
        o << "[" << R.at<double>(r, 0) << ", " << R.at<double>(r, 1) << ", " << R.at<double>(r, 2) << ", " << t.at<double>(r) << "], ";
    }
    o << "[0, 0, 0, 1]]";
}

void emit_reproj(std::ostream &o, const Reproj &r) {
    o << "{\"mean\":" << r.mean << ",\"median\":" << r.median << ",\"p90\":" << r.p90 << ",\"max\":" << r.max << ",\"count\":" << r.count << "}";
}

struct SolveOut {
    bool ransacSuccess = false;
    bool refineOk = false;
    std::string error;
    cv::Mat rvecRansac;
    cv::Mat tvecRansac;
    cv::Mat rvecRefined;
    cv::Mat tvecRefined;
    std::vector<int> inliers;
};

SolveOut solve_pnp(
    const std::vector<cv::Point3d> &obj,
    const std::vector<cv::Point2d> &img,
    const cv::Mat &K,
    const cv::Mat &dist
) {
    SolveOut out;
    out.rvecRansac = cv::Mat::zeros(3, 1, CV_64F);
    out.tvecRansac = cv::Mat::zeros(3, 1, CV_64F);
    out.rvecRefined = out.rvecRansac.clone();
    out.tvecRefined = out.tvecRansac.clone();
    if (obj.size() != img.size()) {
        out.error = "object/image count mismatch";
        return out;
    }
    if (obj.size() < 4) {
        out.error = "fewer than 4 correspondences";
        return out;
    }
    cv::Mat inliers;
    out.ransacSuccess = cv::solvePnPRansac(
        obj, img, K, dist, out.rvecRansac, out.tvecRansac,
        kUseExtrinsicGuess, kIterations, kReprojErr, kConfidence, inliers, kFlags
    );
    if (!inliers.empty()) {
        for (int i = 0; i < inliers.rows; ++i) {
            out.inliers.push_back(inliers.type() == CV_32S ? inliers.at<int>(i, 0) : static_cast<int>(inliers.at<double>(i, 0)));
        }
    }
    if (!out.ransacSuccess) {
        return out;
    }
    std::vector<cv::Point3d> oIn;
    std::vector<cv::Point2d> iIn;
    for (int idx : out.inliers) {
        if (idx >= 0 && idx < static_cast<int>(obj.size())) {
            oIn.push_back(obj[static_cast<size_t>(idx)]);
            iIn.push_back(img[static_cast<size_t>(idx)]);
        }
    }
    if (oIn.size() < 4) {
        out.error = "fewer than 4 RANSAC inliers for RefineLM";
        return out;
    }
    out.rvecRefined = out.rvecRansac.clone();
    out.tvecRefined = out.tvecRansac.clone();
    try {
        cv::solvePnPRefineLM(oIn, iIn, K, dist, out.rvecRefined, out.tvecRefined);
        out.refineOk = std::isfinite(out.rvecRefined.at<double>(0)) && std::isfinite(out.tvecRefined.at<double>(0));
        if (!out.refineOk) {
            out.error = "RefineLM produced non-finite pose";
        }
    } catch (const cv::Exception &ex) {
        out.refineOk = false;
        out.error = std::string("RefineLM exception: ") + ex.what();
    }
    return out;
}

void write_solve_json(std::ostream &o, const SolveOut &s, const std::vector<cv::Point3d> &obj, const std::vector<cv::Point2d> &img, const cv::Mat &K, const cv::Mat &dist) {
    const std::vector<int> metric = s.inliers.empty() ? [&] {
        std::vector<int> all(obj.size());
        for (size_t i = 0; i < obj.size(); ++i) {
            all[i] = static_cast<int>(i);
        }
        return all;
    }() : s.inliers;
    const cv::Mat poseRvec = s.refineOk ? s.rvecRefined : s.rvecRansac;
    const cv::Mat poseTvec = s.refineOk ? s.tvecRefined : s.tvecRansac;
    const cv::Mat R = rotation_from_rvec(poseRvec);
    const cv::Vec3d C = camera_center(R, poseTvec);
    const Reproj reprojR = reprojection(obj, img, metric, s.rvecRansac, s.tvecRansac, K, dist);
    const Reproj reprojF = reprojection(obj, img, metric, poseRvec, poseTvec, K, dist);
    const Cheirality ch = cheirality(obj, metric, R, poseTvec);
    o << "{\n";
    o << "  \"cvVersion\": \"" << CV_VERSION << "\",\n";
    o << "  \"importedCv2\": false,\n";
    o << "  \"baseline\": {\n";
    o << "    \"useExtrinsicGuess\": false,\n";
    o << "    \"iterationsCount\": " << kIterations << ",\n";
    o << "    \"reprojectionError\": " << kReprojErr << ",\n";
    o << "    \"confidence\": " << kConfidence << ",\n";
    o << "    \"flagsName\": \"SOLVEPNP_EPNP\",\n";
    o << "    \"flagsValue\": " << kFlags << ",\n";
    o << "    \"distortionModel\": \"zeros\"\n";
    o << "  },\n";
    o << "  \"ransacSuccess\": " << (s.ransacSuccess ? "true" : "false") << ",\n";
    o << "  \"refineOk\": " << (s.refineOk ? "true" : "false") << ",\n";
    o << "  \"error\": \"" << s.error << "\",\n";
    o << "  \"inlierCount\": " << s.inliers.size() << ",\n";
    o << "  \"inputCorrespondenceCount\": " << obj.size() << ",\n";
    o << "  \"inlierRatio\": " << (obj.empty() ? 0 : static_cast<double>(s.inliers.size()) / static_cast<double>(obj.size())) << ",\n";
    o << "  \"inliers\": [";
    for (size_t i = 0; i < s.inliers.size(); ++i) {
        if (i) {
            o << ", ";
        }
        o << s.inliers[i];
    }
    o << "],\n";
    o << "  \"rvecRansac\": "; emit_vec3(o, s.rvecRansac); o << ",\n";
    o << "  \"tvecRansac\": "; emit_vec3(o, s.tvecRansac); o << ",\n";
    o << "  \"rvecRefined\": "; emit_vec3(o, s.rvecRefined); o << ",\n";
    o << "  \"tvecRefined\": "; emit_vec3(o, s.tvecRefined); o << ",\n";
    o << "  \"rotationMatrix\": "; emit_mat33(o, R); o << ",\n";
    o << "  \"T_opencvCam_colmap\": "; emit_T(o, R, poseTvec); o << ",\n";
    o << "  \"C_colmap\": [" << C[0] << ", " << C[1] << ", " << C[2] << "],\n";
    o << "  \"poseConvention\": \"X_cam = R * X_colmap + t\",\n";
    o << "  \"cameraCenterConvention\": \"C_colmap = -R^T * t\",\n";
    o << "  \"tvecIsNotCameraCenter\": true,\n";
    o << "  \"reprojectionRansac\": "; emit_reproj(o, reprojR); o << ",\n";
    o << "  \"reprojectionRefined\": "; emit_reproj(o, reprojF); o << ",\n";
    o << "  \"positiveDepthCount\": " << ch.positive << ",\n";
    o << "  \"positiveDepthRatio\": " << ch.ratio << ",\n";
    o << "  \"medianInlierDepthCam\": " << ch.medianZ << "\n";
    o << "}\n";
}

int print_version() {
    std::cout << "cvVersion=" << CV_VERSION << "\n";
    std::cout << "flags=SOLVEPNP_EPNP\n";
    std::cout << "flagsValue=" << kFlags << "\n";
    std::cout << "iterationsCount=" << kIterations << "\n";
    std::cout << "reprojectionError=" << kReprojErr << "\n";
    std::cout << "confidence=" << kConfidence << "\n";
    std::cout << "useExtrinsicGuess=false\n";
    return std::string(CV_VERSION) == "4.14.0" ? 0 : 1;
}

bool parse_request(const std::string &path, std::vector<cv::Point3d> &obj, std::vector<cv::Point2d> &img, cv::Mat &K, cv::Mat &dist) {
    std::ifstream in(path);
    if (!in) {
        return false;
    }
    std::string line;
    int n = 0;
    if (!(in >> n)) {
        return false;
    }
    obj.clear();
    img.clear();
    for (int i = 0; i < n; ++i) {
        double X, Y, Z, u, v;
        if (!(in >> X >> Y >> Z >> u >> v)) {
            return false;
        }
        obj.emplace_back(X, Y, Z);
        img.emplace_back(u, v);
    }
    double fx, fy, cx, cy;
    if (!(in >> fx >> fy >> cx >> cy)) {
        return false;
    }
    K = (cv::Mat_<double>(3, 3) << fx, 0, cx, 0, fy, cy, 0, 0, 1);
    dist = cv::Mat::zeros(5, 1, CV_64F);
    return true;
}

int self_test(const std::string &outPath) {
    const double fx = 1450, fy = 1450, cx = 960, cy = 720;
    const cv::Mat K = (cv::Mat_<double>(3, 3) << fx, 0, cx, 0, fy, cy, 0, 0, 1);
    const cv::Mat dist = cv::Mat::zeros(5, 1, CV_64F);
    const cv::Mat rvecGT = (cv::Mat_<double>(3, 1) << 0.12, -0.18, 0.07);
    const cv::Mat tGT = (cv::Mat_<double>(3, 1) << 0.4, -0.3, 6.5);
    std::vector<cv::Point3d> obj;
    for (int iy = 0; iy < 5; ++iy) {
        for (int ix = 0; ix < 5; ++ix) {
            obj.emplace_back(-1.6 + 0.8 * ix, -1.6 + 0.8 * iy, 0);
        }
    }
    obj.emplace_back(-0.4, 0.2, 0.35);
    obj.emplace_back(0.5, -0.6, 0.4);
    obj.emplace_back(0.0, 0.0, 0.25);
    std::vector<cv::Point2d> img;
    cv::projectPoints(obj, rvecGT, tGT, K, dist, img);
    const SolveOut correct = solve_pnp(obj, img, K, dist);
    const cv::Mat Rgt = rotation_from_rvec(rvecGT);
    const cv::Mat Rest = rotation_from_rvec(correct.refineOk ? correct.rvecRefined : correct.rvecRansac);
    const cv::Mat tEst = correct.refineOk ? correct.tvecRefined : correct.tvecRansac;
    const cv::Vec3d Cgt = camera_center(Rgt, tGT);
    const cv::Vec3d Cest = camera_center(Rest, tEst);
    const double rot = rotation_angle_deg(Rest, Rgt);
    const double center = cv::norm(Cest - Cgt);
    const std::vector<int> allIdx = [&] {
        std::vector<int> v(obj.size());
        for (size_t i = 0; i < obj.size(); ++i) {
            v[i] = static_cast<int>(i);
        }
        return v;
    }();
    const cv::Mat poseR = correct.refineOk ? correct.rvecRefined : correct.rvecRansac;
    const Reproj reproj = reprojection(obj, img, correct.inliers.empty() ? allIdx : correct.inliers, poseR, tEst, K, dist);

    const double scale = 960.0 / 1920.0;
    const cv::Mat Kwrong = (cv::Mat_<double>(3, 3) << fx * scale, 0, cx * scale, 0, fy * scale, cy * scale, 0, 0, 1);
    const SolveOut wrongK = solve_pnp(obj, img, Kwrong, dist);
    std::vector<cv::Point2d> imgScaled;
    imgScaled.reserve(img.size());
    for (const auto &p : img) {
        imgScaled.emplace_back(p.x * scale, p.y * scale);
    }
    const SolveOut wrongUV = solve_pnp(obj, imgScaled, K, dist);

    auto metrics = [&](const SolveOut &s, const cv::Mat &usedK, const std::vector<cv::Point2d> &usedImg) {
        const cv::Mat r = s.refineOk ? s.rvecRefined : s.rvecRansac;
        const cv::Mat t = s.refineOk ? s.tvecRefined : s.tvecRansac;
        const cv::Mat R = rotation_from_rvec(r);
        const cv::Vec3d C = camera_center(R, t);
        const std::vector<int> idxs = s.inliers.empty() ? allIdx : s.inliers;
        return std::tuple<double, double, double, double>(
            rotation_angle_deg(R, Rgt),
            cv::norm(C - Cgt),
            reprojection(obj, usedImg, idxs, r, t, usedK, dist).median,
            cheirality(obj, idxs, R, t).ratio
        );
    };
    const auto mK = metrics(wrongK, Kwrong, img);
    const auto mUV = metrics(wrongUV, K, imgScaled);

    const bool passCorrect = correct.ransacSuccess && rot < 0.05 && center < 1e-3 && reproj.median < 0.05;
    const bool worseK = std::get<0>(mK) > 5.0 && std::get<1>(mK) > 1.0 && std::get<2>(mK) > std::max(0.5, reproj.median * 10.0);
    const bool worseUV = std::get<0>(mUV) > 5.0 && std::get<1>(mUV) > 1.0 && std::get<2>(mUV) > std::max(0.5, reproj.median * 10.0);
    const bool pass = passCorrect && worseK && worseUV && std::string(CV_VERSION) == "4.14.0";

    std::ostringstream body;
    body << "{\n";
    body << "  \"cvVersion\": \"" << CV_VERSION << "\",\n";
    body << "  \"importedCv2\": false,\n";
    body << "  \"pass\": " << (pass ? "true" : "false") << ",\n";
    body << "  \"correct\": {\n";
    body << "    \"ransacSuccess\": " << (correct.ransacSuccess ? "true" : "false") << ",\n";
    body << "    \"refineOk\": " << (correct.refineOk ? "true" : "false") << ",\n";
    body << "    \"rotationDeg\": " << rot << ",\n";
    body << "    \"centerError\": " << center << ",\n";
    body << "    \"reprojMedian\": " << reproj.median << ",\n";
    body << "    \"inlierCount\": " << correct.inliers.size() << "\n";
    body << "  },\n";
    body << "  \"nativeUV_scaledK\": {\"rotationDeg\": " << std::get<0>(mK) << ", \"centerError\": " << std::get<1>(mK) << ", \"reprojMedian\": " << std::get<2>(mK) << ", \"positiveDepthRatio\": " << std::get<3>(mK) << "},\n";
    body << "  \"scaledUV_nativeK\": {\"rotationDeg\": " << std::get<0>(mUV) << ", \"centerError\": " << std::get<1>(mUV) << ", \"reprojMedian\": " << std::get<2>(mUV) << ", \"positiveDepthRatio\": " << std::get<3>(mUV) << "}\n";
    body << "}\n";
    if (!outPath.empty()) {
        std::ofstream f(outPath);
        f << body.str();
    }
    std::cout << body.str();
    return pass ? 0 : 1;
}

}  // namespace

int main(int argc, char **argv) {
    if (argc >= 2 && std::string(argv[1]) == "--version") {
        return print_version();
    }
    if (argc >= 2 && std::string(argv[1]) == "--self-test") {
        std::string out;
        if (argc >= 4 && std::string(argv[2]) == "--out") {
            out = argv[3];
        }
        return self_test(out);
    }
    if (argc >= 5 && std::string(argv[1]) == "--solve" && std::string(argv[2]) == "--in") {
        const std::string inPath = argv[3];
        std::string outPath = "-";
        if (argc >= 7 && std::string(argv[4]) == "--out") {
            outPath = argv[5];
        } else if (argc >= 5 && std::string(argv[4]) == "--out") {
            outPath = argv[5];
        }
        std::vector<cv::Point3d> obj;
        std::vector<cv::Point2d> img;
        cv::Mat K, dist;
        if (!parse_request(inPath, obj, img, K, dist)) {
            std::cerr << "STOP: failed to parse PnP request\n";
            return 2;
        }
        try {
            const SolveOut solved = solve_pnp(obj, img, K, dist);
            if (outPath == "-") {
                write_solve_json(std::cout, solved, obj, img, K, dist);
            } else {
                std::ofstream f(outPath);
                write_solve_json(f, solved, obj, img, K, dist);
            }
            return 0;
        } catch (const cv::Exception &ex) {
            std::cerr << "STOP: " << ex.what() << "\n";
            return 3;
        }
    }
    std::cerr << "usage: rv_pnp --version | --self-test [--out report.json] | --solve --in request.txt --out result.json\n";
    return 2;
}
