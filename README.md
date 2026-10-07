# Tiago Web Interface

A browser-based control console for the PAL Robotics **TiaGo** mobile robot. It lets you visually program a sequence of robot movements with a drag-and-drop block editor (Blockly), run them on the physical robot, and watch a live camera feed, LiDAR radar, and object-detection overlay while an always-on safety watchdog guards against collisions.

Everything runs from a single command (`bash start.sh`) inside a preconfigured dev container — no frontend build step, no manual ROS setup.

## What's in this repo

| Path | What it is |
|---|---|
| `backend/` | FastAPI server — serves the UI, bridges the browser to ROS over a WebSocket, runs the safety watchdog and block executor |
| `frontend/` | Static HTML/JS UI — Blockly block editor, live camera view, LiDAR radar HUD, safety/status panels |
| `vision/` | ROS (catkin) package — a C++ node that runs YOLOv8 object detection on the robot's camera feed and localizes detections in 3D using the depth point cloud |
| `models/` | YOLOv8n ONNX weights used by the vision node |
| `.devcontainer/` | Dockerfile + devcontainer config (ROS Noetic desktop-full, Node 20, vision/ML dependencies) |
| `start.sh` | One-command launcher: sets up ROS env vars and starts the FastAPI server |
| `ARCHITECTURE.md` | Deep-dive on system design, network layout, WebSocket/REST protocol, and the safety state machine |
| `TROUBLESHOOTING.md`, `CAMERA_FEED_FIX.md` | Notes on known issues and fixes |

### How it talks to the robot

The dev container runs on your lab computer and connects over WiFi to the TiaGo robot (hostname `bandit`, ROS master on port 11311). The browser talks only to the FastAPI server on your lab computer (port 8000); the server bridges that to ROS topics (`cmd_vel`, `/scan`, camera, detections) on the robot. See `ARCHITECTURE.md` for the full diagram.

## Prerequisites

- Docker (with VS Code **Dev Containers** extension, or any tool that can build/run a devcontainer)
- Network access to the TiaGo robot (`bandit`) — the container is launched with `--network=host` and `--add-host=bandit:10.234.6.53`
- Git

## Getting started

### 1. Get the code

```bash
git clone https://github.com/sheikhmunim/tiago_ui.git
cd tiago_ui
```

If you're working off a feature branch instead of `main`, check it out first, e.g.:

```bash
git checkout vision
```

### 2. Open the project in the dev container

The repo ships a `.devcontainer/` config, so the easiest path is VS Code:

1. Open the `tiago_ui` folder in VS Code.
2. Install the **Dev Containers** extension if you don't have it.
3. Run **"Dev Containers: Reopen in Container"** (Command Palette, `Ctrl+Shift+P`).
4. VS Code builds the image from `.devcontainer/Dockerfile` (ROS Noetic desktop-full, Node 20, rosbridge/web_video_server, OpenCV, Ultralytics, ONNX Runtime, FastAPI/uvicorn — this can take several minutes the first time) and drops you into a shell inside the container at `/tiago_ui`.

If you'd rather not use VS Code, you can build and run the same image manually with plain Docker:

```bash
docker build -t tiago_ui .devcontainer
docker run -it --privileged --network=host \
  --add-host=bandit:10.234.6.53 \
  -v "$(pwd)":/tiago_ui \
  -w /tiago_ui \
  tiago_ui bash
```

### 3. Start the server

From a shell **inside the container**:

```bash
bash start.sh
```

This script:
- Sources the ROS Noetic environment
- Points ROS at the robot (`ROS_MASTER_URI=http://bandit:11311`) and figures out this machine's IP for `ROS_IP`
- Warns (but doesn't fail) if the robot isn't reachable yet — rospy will keep retrying in the background
- Kills any stale process already bound to port 8000
- Starts the FastAPI app with `uvicorn` on `0.0.0.0:8000`

### 4. Open the UI

Once `start.sh` prints the URLs, open one of them in a browser on the same network:

```
http://<lab-computer-ip>:8000
http://localhost:8000
```

From there you can:
- Drag blocks together to build a movement sequence and run it on the robot
- Watch the live camera feed and YOLO object-detection overlay
- Watch the LiDAR radar HUD and safety status (the watchdog runs continuously and will stop the robot if something gets too close, independent of whatever sequence is executing)

Press `Ctrl+C` in the terminal running `start.sh` to shut the server down.

## Notes

- The vision ROS package (`vision/`) is a catkin package; if you need to build/run it standalone (outside of what the backend launches for you), build it in a catkin workspace in the usual way (`catkin_make` / `catkin build`) and `roslaunch vision vision.launch`.
- See `TROUBLESHOOTING.md` and `CAMERA_FEED_FIX.md` if the camera feed or robot connection isn't working.
- See `ARCHITECTURE.md` for the full system design, including the WebSocket protocol, REST API, and safety state machine.
