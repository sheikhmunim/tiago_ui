# Single detected object with 3D location
# Published per object; array is wrapped in DetectedObjectArray

# Object identity
string label          # e.g. "person", "chair", "bottle"
float32 confidence    # 0.0 – 1.0 detection confidence

# 2D bounding box in image space (pixels)
uint32 bbox_x
uint32 bbox_y
uint32 bbox_width
uint32 bbox_height

# 3D position in robot base frame (metres)
# RESEARCH: which frame to use — base_footprint vs map vs odom
# base_footprint = relative to robot now (simpler)
# map = absolute position (needs SLAM/localisation running)
geometry_msgs/Point position

# Optional: axis-aligned bounding box in 3D (from point cloud)
# RESEARCH: do you need full 3D bbox or just centroid?
geometry_msgs/Vector3 dimensions  # width, depth, height in metres
