cmake_minimum_required(VERSION 3.0.2)
project(tiago_vision)

set(CMAKE_CXX_STANDARD 17)

# RESEARCH: if using YOLO via darknet_ros, add its find_package here
# RESEARCH: if using ONNX Runtime, find_package(onnxruntime) and link it

find_package(catkin REQUIRED COMPONENTS
  roscpp
  std_msgs
  sensor_msgs
  geometry_msgs
  cv_bridge
  image_transport
  pcl_ros
  pcl_conversions
  tf2
  tf2_ros
  tf2_geometry_msgs
  message_generation
)

find_package(OpenCV REQUIRED)
find_package(PCL REQUIRED)


# ONNX Runtime
find_library(ONNXRUNTIME_LIB onnxruntime HINTS /usr/local/lib)
set(ONNXRUNTIME_INCLUDE_DIR /usr/local/include)


# Custom messages
add_message_files(
  FILES
  DetectedObject.msg
  DetectedObjectArray.msg
)

generate_messages(
  DEPENDENCIES
  std_msgs
  geometry_msgs
)

catkin_package(
  INCLUDE_DIRS include
  LIBRARIES tiago_vision
  CATKIN_DEPENDS
    roscpp std_msgs sensor_msgs geometry_msgs
    cv_bridge image_transport pcl_ros tf2 tf2_ros
    message_runtime
)

include_directories(
  include
  ${catkin_INCLUDE_DIRS}
  ${OpenCV_INCLUDE_DIRS}
  ${PCL_INCLUDE_DIRS}
  ${ONNXRUNTIME_INCLUDE_DIR}
)

# Vision node executable
add_executable(vision_node
  src/vision_node.cpp
  src/detector.cpp
  src/localizer.cpp
)

add_dependencies(vision_node
  ${${PROJECT_NAME}_EXPORTED_TARGETS}
  ${catkin_EXPORTED_TARGETS}
)

target_link_libraries(vision_node
  ${catkin_LIBRARIES}
  ${OpenCV_LIBS}
  ${PCL_LIBRARIES}
  ${ONNXRUNTIME_LIB}
)

install(TARGETS vision_node
  RUNTIME DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch config
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)
