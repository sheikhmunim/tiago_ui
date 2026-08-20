#include "vision/detector.h"
#include <ros/ros.h>
#include <algorithm>
#include <numeric>

namespace tiago_vision {

// COCO 80 class names
static const std::vector<std::string> COCO_LABELS = {
    "person","bicycle","car","motorcycle","airplane","bus","train","truck",
    "boat","traffic light","fire hydrant","stop sign","parking meter","bench",
    "bird","cat","dog","horse","sheep","cow","elephant","bear","zebra","giraffe",
    "backpack","umbrella","handbag","tie","suitcase","frisbee","skis","snowboard",
    "sports ball","kite","baseball bat","baseball glove","skateboard","surfboard",
    "tennis racket","bottle","wine glass","cup","fork","knife","spoon","bowl",
    "banana","apple","sandwich","orange","broccoli","carrot","hot dog","pizza",
    "donut","cake","chair","couch","potted plant","bed","dining table","toilet",
    "tv","laptop","mouse","remote","keyboard","cell phone","microwave","oven",
    "toaster","sink","refrigerator","book","clock","vase","scissors","teddy bear",
    "hair drier","toothbrush"
};

Detector::Detector(const std::string& model_path, float conf_threshold)
    : conf_threshold_(conf_threshold),
      env_(ORT_LOGGING_LEVEL_WARNING, "tiago_vision")
{
    session_opts_.SetIntraOpNumThreads(1);
    session_opts_.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_EXTENDED);

    session_ = std::make_unique<Ort::Session>(env_, model_path.c_str(), session_opts_);

    // Get input name
    auto in_name = session_->GetInputNameAllocated(0, allocator_);
    input_names_owned_.push_back(in_name.get());
    input_names_.push_back(input_names_owned_[0].c_str());

    // Get output name
    auto out_name = session_->GetOutputNameAllocated(0, allocator_);
    output_names_owned_.push_back(out_name.get());
    output_names_.push_back(output_names_owned_[0].c_str());

    labels_ = COCO_LABELS;

    ROS_INFO("Detector ready — model: %s, threshold: %.2f",
             model_path.c_str(), conf_threshold_);
}

std::vector<float> Detector::preprocess(const cv::Mat& image)
{
    cv::Mat resized, rgb, normalized;

    // Resize to 640x640
    cv::resize(image, resized, cv::Size(input_width_, input_height_));

    // BGR → RGB
    cv::cvtColor(resized, rgb, cv::COLOR_BGR2RGB);

    // Convert to float and normalize 0-255 → 0.0-1.0
    rgb.convertTo(normalized, CV_32F, 1.0 / 255.0);

    // HWC → CHW (height,width,channels → channels,height,width)
    // ONNX Runtime expects [1, 3, 640, 640]
    std::vector<float> tensor(3 * input_height_ * input_width_);
    for (int c = 0; c < 3; ++c)
        for (int h = 0; h < input_height_; ++h)
            for (int w = 0; w < input_width_; ++w)
                tensor[c * input_height_ * input_width_ + h * input_width_ + w] =
                    normalized.at<cv::Vec3f>(h, w)[c];

    return tensor;
}

std::vector<Detection> Detector::detect(const cv::Mat& image)
{
    if (image.empty()) return {};

    float scale_x = static_cast<float>(image.cols) / input_width_;
    float scale_y = static_cast<float>(image.rows) / input_height_;

    // Preprocess
    auto tensor_data = preprocess(image);

    // Create input tensor
    std::array<int64_t, 4> input_shape{1, 3, input_height_, input_width_};
    auto memory_info = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
        memory_info,
        tensor_data.data(), tensor_data.size(),
        input_shape.data(), input_shape.size()
    );

    // Run inference
    auto output_tensors = session_->Run(
        Ort::RunOptions{nullptr},
        input_names_.data(), &input_tensor, 1,
        output_names_.data(), 1
    );

    // Parse output — shape [1, 84, 8400]
    // 84 = 4 bbox coords (cx,cy,w,h) + 80 class scores
    auto& out = output_tensors[0];
    auto shape = out.GetTensorTypeAndShapeInfo().GetShape();
    const float* data = out.GetTensorData<float>();

    int num_detections = shape[2];  // 8400
    int num_classes    = shape[1] - 4;  // 80

    std::vector<cv::Rect>  boxes;
    std::vector<float>     scores;
    std::vector<int>       class_ids;

    for (int i = 0; i < num_detections; ++i) {
        // Find best class score for this detection
        float max_score = 0.0f;
        int   best_class = 0;
        for (int c = 0; c < num_classes; ++c) {
            float score = data[(4 + c) * num_detections + i];
            if (score > max_score) {
                max_score  = score;
                best_class = c;
            }
        }

        if (max_score < conf_threshold_) continue;

        // bbox is cx, cy, w, h — normalized to input size
        float cx = data[0 * num_detections + i];
        float cy = data[1 * num_detections + i];
        float w  = data[2 * num_detections + i];
        float h  = data[3 * num_detections + i];

        // Convert to pixel coords in original image
        int x = static_cast<int>((cx - w / 2) * scale_x);
        int y = static_cast<int>((cy - h / 2) * scale_y);
        int bw = static_cast<int>(w * scale_x);
        int bh = static_cast<int>(h * scale_y);

        boxes.push_back(cv::Rect(x, y, bw, bh));
        scores.push_back(max_score);
        class_ids.push_back(best_class);
    }

    // NMS — remove overlapping boxes
    std::vector<int> indices;
    cv::dnn::NMSBoxes(boxes, scores, conf_threshold_, 0.45f, indices);

    std::vector<Detection> results;
    for (int idx : indices) {
        Detection det;
        det.label      = (class_ids[idx] < (int)labels_.size())
                         ? labels_[class_ids[idx]] : "unknown";
        det.confidence = scores[idx];
        det.bbox       = boxes[idx];
        results.push_back(det);
    }

    return results;
}

} // namespace tiago_vision
