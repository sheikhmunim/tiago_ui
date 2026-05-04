#include <ros/ros.h>
#include <sensor_msgs/Image.h>
#include <sensor_msgs/PointCloud2.h>
#include <cv_bridge/cv_bridge.h>
#include <pcl_conversions/pcl_conversions.h>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <message_filters/subscriber.h>
#include <message_filters/synchronizer.h>
#include <message_filters/sync_policies/approximate_time.h>

#include "vision/detector.h"
#include "vision/localizer.h"
#include "tiago_vision/DetectedObjectArray.h"
#include "tiago_vision/DetectedObject.h"

// RESEARCH: Xtion topics on TiaGo — verify with: rostopic list | grep xtion
// Typical:
//   RGB image : /xtion/rgb/image_raw
//   Point cloud: /xtion/depth_registered/points  (depth aligned to RGB frame)
static const std::string IMAGE_TOPIC  = "/xtion/rgb/image_raw";
static const std::string CLOUD_TOPIC  = "/xtion/depth_registered/points";
static const std::string OUTPUT_TOPIC = "/detected_objects";

// Synchronisation policy: image + cloud must arrive within this time window
// RESEARCH: tune this if you get dropped frames (ApproximateTime is more robust than Exact)
using SyncPolicy = message_filters::sync_policies::ApproximateTime<
    sensor_msgs::Image,
    sensor_msgs::PointCloud2
>;

class VisionNode {
public:
    VisionNode(ros::NodeHandle& nh, ros::NodeHandle& pnh)
    {
        // Load params from config/params.yaml
        std::string model_path;
        float conf_threshold;
        std::string target_frame;

        pnh.param<std::string>("model_path",    model_path,    "");
        pnh.param<float>      ("conf_threshold", conf_threshold, 0.5f);
        pnh.param<std::string>("target_frame",  target_frame,  "base_footprint");

        if (model_path.empty()) {
            ROS_FATAL("~model_path param is required");
            ros::shutdown();
            return;
        }

        detector_  = std::make_unique<tiago_vision::Detector>(model_path, conf_threshold);
        localizer_ = std::make_unique<tiago_vision::Localizer>(target_frame);

        pub_ = nh.advertise<tiago_vision::DetectedObjectArray>(OUTPUT_TOPIC, 10);

        // Synchronise RGB image + point cloud by timestamp
        image_sub_.subscribe(nh, IMAGE_TOPIC, 1);
        cloud_sub_.subscribe(nh, CLOUD_TOPIC, 1);

        sync_ = std::make_unique<message_filters::Synchronizer<SyncPolicy>>(
            SyncPolicy(10), image_sub_, cloud_sub_
        );
        sync_->registerCallback(&VisionNode::callback, this);

        ROS_INFO("Vision node ready — listening on %s + %s",
                 IMAGE_TOPIC.c_str(), CLOUD_TOPIC.c_str());
        ROS_INFO("Publishing detections to %s", OUTPUT_TOPIC.c_str());
    }

private:
    void callback(const sensor_msgs::ImageConstPtr&      img_msg,
                  const sensor_msgs::PointCloud2ConstPtr& cloud_msg)
    {
        // Convert ROS image → OpenCV
        cv_bridge::CvImagePtr cv_ptr;
        try {
            cv_ptr = cv_bridge::toCvCopy(img_msg, sensor_msgs::image_encodings::BGR8);
        } catch (cv_bridge::Exception& e) {
            ROS_ERROR("cv_bridge error: %s", e.what());
            return;
        }

        // Convert ROS PointCloud2 → PCL
        pcl::PointCloud<pcl::PointXYZ>::Ptr cloud(new pcl::PointCloud<pcl::PointXYZ>);
        pcl::fromROSMsg(*cloud_msg, *cloud);

        // Run detection
        auto detections = detector_->detect(cv_ptr->image);

        // Build output message
        tiago_vision::DetectedObjectArray out;
        out.header = img_msg->header;

        for (const auto& det : detections) {
            auto loc = localizer_->localize(det.bbox, cloud);
            if (!loc) continue; // skip if no valid depth

            tiago_vision::DetectedObject obj;
            obj.label      = det.label;
            obj.confidence = det.confidence;
            obj.bbox_x     = det.bbox.x;
            obj.bbox_y     = det.bbox.y;
            obj.bbox_width  = det.bbox.width;
            obj.bbox_height = det.bbox.height;
            obj.position   = loc->position;
            obj.dimensions = loc->dimensions;

            out.objects.push_back(obj);
        }

        pub_.publish(out);
    }

    std::unique_ptr<tiago_vision::Detector>  detector_;
    std::unique_ptr<tiago_vision::Localizer> localizer_;

    ros::Publisher pub_;

    message_filters::Subscriber<sensor_msgs::Image>       image_sub_;
    message_filters::Subscriber<sensor_msgs::PointCloud2> cloud_sub_;

    std::unique_ptr<message_filters::Synchronizer<SyncPolicy>> sync_;
};


int main(int argc, char** argv)
{
    ros::init(argc, argv, "tiago_vision");
    ros::NodeHandle nh;
    ros::NodeHandle pnh("~");

    VisionNode node(nh, pnh);
    ros::spin();
    return 0;
}
