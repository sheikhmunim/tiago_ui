#pragma once

#include <opencv2/opencv.hpp>
#include <onnxruntime_cxx_api.h>
#include <string>
#include <vector>

namespace tiago_vision {

struct Detection {
    std::string label;
    float       confidence;
    cv::Rect    bbox;        // pixel coords in image
};

class Detector {
public:
    explicit Detector(const std::string& model_path, float conf_threshold = 0.5f);

    std::vector<Detection> detect(const cv::Mat& image);

private:
    float conf_threshold_;

    // ONNX Runtime
    Ort::Env                                  env_;
    Ort::SessionOptions                       session_opts_;
    std::unique_ptr<Ort::Session>             session_;
    Ort::AllocatorWithDefaultOptions          allocator_;

    // Model info
    int input_width_  = 640;
    int input_height_ = 640;
    std::vector<std::string>  input_names_owned_;
    std::vector<std::string>  output_names_owned_;
    std::vector<const char*>  input_names_;
    std::vector<const char*>  output_names_;

    // COCO class labels
    std::vector<std::string> labels_;

    // helpers
    std::vector<float> preprocess(const cv::Mat& image);
    void load_labels();
};

} // namespace tiago_vision