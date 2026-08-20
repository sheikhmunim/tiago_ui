#pragma once

#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <geometry_msgs/Point.h>
#include <geometry_msgs/Vector3.h>
#include <opencv2/opencv.hpp>
#include <optional>

namespace tiago_vision {

struct Location3D {
    geometry_msgs::Point   position;   // centroid in target frame
    geometry_msgs::Vector3 dimensions; // w x d x h bounding box
};

class Localizer {
public:
    // RESEARCH: target_frame options
    //   "base_footprint" : position relative to robot (simple, no SLAM needed)
    //   "map"            : absolute position (needs nav stack running)
    explicit Localizer(const std::string& target_frame = "base_footprint");

    // Given a 2D bbox and the current point cloud, extract 3D location
    // Returns nullopt if the ROI has no valid depth points
    std::optional<Location3D> localize(
        const cv::Rect& bbox,
        const pcl::PointCloud<pcl::PointXYZ>::ConstPtr& cloud
    );

private:
    std::string target_frame_;

    // RESEARCH: tf2 buffer + listener needed to transform point cloud
    // into target_frame if cloud is in a different frame (e.g. xtion_rgb_optical_frame)
};

} // namespace tiago_vision
