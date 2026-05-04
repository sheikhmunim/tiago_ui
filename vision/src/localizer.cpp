#include "vision/localizer.h"
#include <pcl/common/centroid.h>
#include <pcl/filters/extract_indices.h>
#include <ros/ros.h>

namespace tiago_vision {

Localizer::Localizer(const std::string& target_frame)
    : target_frame_(target_frame)
{
    // RESEARCH: initialise tf2 buffer + listener if frame transforms are needed
    // tf_buffer_   = std::make_shared<tf2_ros::Buffer>();
    // tf_listener_ = std::make_shared<tf2_ros::TransformListener>(*tf_buffer_);
}

std::optional<Location3D> Localizer::localize(
    const cv::Rect& bbox,
    const pcl::PointCloud<pcl::PointXYZ>::ConstPtr& cloud)
{
    // RESEARCH: the point cloud from Xtion is organized (width x height matches image)
    // so you can index directly by pixel row/col — no projection math needed.
    // If unorganized, you need camera intrinsics to back-project pixels to 3D.

    // Step 1: extract points within the 2D bounding box
    pcl::PointCloud<pcl::PointXYZ>::Ptr roi(new pcl::PointCloud<pcl::PointXYZ>);

    // RESEARCH: cloud->width and cloud->height must match image resolution
    // Typical Xtion: 640x480
    for (int row = bbox.y; row < bbox.y + bbox.height; ++row) {
        for (int col = bbox.x; col < bbox.x + bbox.width; ++col) {
            const auto& pt = cloud->at(col, row); // organized cloud indexing
            if (std::isfinite(pt.x) && std::isfinite(pt.y) && std::isfinite(pt.z)) {
                roi->push_back(pt);
            }
        }
    }

    if (roi->empty()) {
        return std::nullopt; // no valid depth in this region
    }

    // Step 2: compute centroid
    Eigen::Vector4f centroid;
    pcl::compute3DCentroid(*roi, centroid);

    // Step 3: compute axis-aligned bounding box dimensions
    Eigen::Vector4f min_pt, max_pt;
    pcl::getMinMax3D(*roi, min_pt, max_pt);

    Location3D loc;
    loc.position.x = centroid[0];
    loc.position.y = centroid[1];
    loc.position.z = centroid[2];

    loc.dimensions.x = max_pt[0] - min_pt[0]; // width
    loc.dimensions.y = max_pt[1] - min_pt[1]; // depth
    loc.dimensions.z = max_pt[2] - min_pt[2]; // height

    // RESEARCH: if cloud frame != target_frame_, transform here using tf2:
    // geometry_msgs::PointStamped in_pt, out_pt;
    // in_pt.header.frame_id = cloud->header.frame_id;
    // in_pt.point = loc.position;
    // tf_buffer_->transform(in_pt, out_pt, target_frame_);
    // loc.position = out_pt.point;

    return loc;
}

} // namespace tiago_vision
