# Tiago Interface — Troubleshooting Log

## Problem: Backend not connecting to robot

### Root Cause Summary

Three separate issues were found and fixed:

---

## Issue 1: Wrong ROS_MASTER_URI

**Symptom:** `rospy.topics: topicmanager initialized` then stuck forever.

**Cause:** The environment variable `ROS_MASTER_URI` was set to `http://localhost:11311` instead of `http://bandit:11311`. rospy was trying to connect to a local ROS master that doesn't exist.

**Fix:** `start.sh` now sets `export ROS_MASTER_URI=http://bandit:11311` on startup.

---

## Issue 2: Wrong ROS_IP (Docker networking)

**Symptom:** rospy connected to the master but pub/sub never worked. Robot could not send data back to the container.

**Cause:** The backend runs inside a Docker container with internal IP `192.168.65.6`. This IP is on Docker's internal bridge network — the robot at `10.234.6.53` cannot route to it. ROS requires bidirectional TCP connections for pub/sub, so it silently hung.

The robot sees the lab computer as `10.234.7.132` (lab WiFi IP), but `hostname -I` inside the container returns `192.168.65.6` first, so `ROS_IP` was set wrong.

**Why rospy was the wrong approach:** Even fixing `ROS_IP` wouldn't work because the container doesn't own the `10.234.7.132` address — it belongs to the Docker host. rospy cannot bind to an IP it doesn't have.

**Fix:** Switched from rospy to rosbridge WebSocket protocol (see Issue 3).

---

## Issue 3: roslibpy (Twisted) conflicts with FastAPI (asyncio)

**Symptom:** After switching to roslibpy, connection kept failing with:
- `run_forever() got an unexpected keyword argument 'timeout'`
- `signal only works in main thread`
- `on_ready() missing 1 required positional argument`

**Cause:** roslibpy uses Twisted as its networking backend. Twisted's reactor:
- Cannot install signal handlers in background threads (only main thread)
- Conflicts with FastAPI which uses asyncio
- Has a different API in version 2.0.0 (callback signatures changed)

**Fix:** Dropped roslibpy entirely. Replaced with `websockets` library (pure asyncio) implementing the rosbridge JSON protocol directly. This integrates perfectly with FastAPI's asyncio event loop and has no threading issues.

The rosbridge protocol is simple JSON:
- **Subscribe:** `{"op": "subscribe", "topic": "/scan", "type": "sensor_msgs/LaserScan"}`
- **Publish:** `{"op": "publish", "topic": "/cmd_vel", "msg": {...}}`

---

## Issue 4: Scan ranges contain null values

**Symptom:** `scan callback error: must be real number, not NoneType` — spamming logs, safety state never becoming CLEAR.

**Cause:** The LiDAR scan message contains invalid readings encoded as `Inf` in ROS, but rosbridge sends them as `null` in JSON. The safety watchdog tried to do math on `None`.

**Fix:** Added `r is not None` check in `safety.py` before the `math.isfinite()` check.

---

## Issue 5: Duplicate ROS packages on bandit

**Symptom:** `roslaunch rosbridge_server rosbridge_websocket.launch` failed with hundreds of "Multiple packages found" errors.

**Cause:** Someone ran `wstool` or cloned the workspace repos inside `catkin_ws/src/` instead of at the workspace root. This created `catkin_ws/src/src/` — a full duplicate of all packages nested inside the real `src/`.

**Fix (temporary, per session):**
```bash
export ROS_PACKAGE_PATH=$(echo $ROS_PACKAGE_PATH | tr ':' '\n' | grep -v 'catkin_ws/src/src' | tr '\n' ':')
```

**Fix (permanent, run once on bandit):**
```bash
echo 'export ROS_PACKAGE_PATH=$(echo $ROS_PACKAGE_PATH | tr ":" "\n" | grep -v "catkin_ws/src/src" | tr "\n" ":")' >> ~/.bashrc
source ~/.bashrc
```

**To start rosbridge on bandit (use PAL startup system — avoids node conflicts):**
```bash
sshpass -p pal ssh pal@10.234.6.53 "source /opt/ros/noetic/setup.bash && source /opt/pal/gallium/setup.bash && rosservice call /pal_startup_startup_extras/start '{app: rosbridge}'"
```
Do NOT use `nohup` or `roslaunch` directly — PAL's startup system manages rosbridge and will kill any manually started instance.

---

## How to start everything correctly

### On bandit (robot):
```bash
# Fix duplicate packages (if not already in ~/.bashrc)
export ROS_PACKAGE_PATH=$(echo $ROS_PACKAGE_PATH | tr ':' '\n' | grep -v 'catkin_ws/src/src' | tr '\n' ':')

# Start rosbridge
/opt/ros/noetic/lib/rosbridge_server/rosbridge_websocket
```

### On the lab computer (dev container):
```bash
cd /tiago_interface
pkill -f "uvicorn main:app"  # kill any old instance
bash start.sh
```

### Verify it's working:
```bash
curl http://localhost:8000/status
```
Expected response:
```json
{"ros_ready": true, "safety": {"state": "CLEAR", "min_dist": 1.016}, "executor_running": false, "services": {}}
```

---

## Issue 6: Running RViz from the dev container (Docker/WSL2)

**Symptom:** RViz fails with `could not connect to display` or connects but shows no TF data.

**Cause:** The dev container runs inside Docker on WSL2. Two separate problems:
1. No display available in the container — needs an X server on Windows
2. ROS pub/sub is bidirectional — the robot (`10.234.6.53`) cannot route back to the container's internal IP (`192.168.65.x`), so no TF or topic data flows to RViz

**Fix:** Run RViz **on the robot** and point its display directly at VcXsrv on Windows. Both the robot and the Windows machine are on the same lab network (`10.234.x.x/23`), so the connection works without any tunneling.

**Setup (one-time):**
1. Install [VcXsrv](https://sourceforge.net/projects/vcxsrv/) on Windows
2. Launch **XLaunch** → Multiple windows → Start no client → check **Disable access control** → Finish

**Launch RViz:**
```bash
sshpass -p pal ssh pal@10.234.6.53 "export DISPLAY=10.234.7.132:0 && source /opt/ros/noetic/setup.bash && rviz"
```

- `10.234.6.53` — robot IP
- `10.234.7.132` — Windows lab WiFi IP (where VcXsrv is running)
- Password: `pal`

---

## Downloading files from the robot

Use `sshpass` with `scp` to pull files from the robot to the local project directory:

```bash
sshpass -p pal scp pal@10.234.6.53:~/filename /tiago_interface/filename
```

- **Robot IP:** `10.234.6.53` (hostname: `bandit`)
- **User:** `pal`
- **Password:** `pal`

Example — download multiple files at once:

```bash
sshpass -p pal scp pal@10.234.6.53:~/{frames.pdf,fixed_description.yaml,raw_description.txt} /tiago_interface/
```

---

## Visualizing the Tiago Robot Description in RViz

This guide shows how to view the Tiago robot 3D model in RViz, remotely from your computer, using a VNC viewer.

**What you need on your computer:**
- TigerVNC Viewer installed
- `sshpass` installed (`sudo apt install sshpass` on Ubuntu)
- `python3` installed

---

### Step 1 — Download the robot description from the robot

The robot stores its URDF (robot model) as a ROS parameter. First, download the raw file:

```bash
sshpass -p pal scp pal@10.234.6.53:~/raw_description.txt /tiago_interface/raw_description.txt
```

This file contains the URDF as an escaped string (it looks like a big quoted XML blob).

---

### Step 2 — Convert it to a clean URDF file

The raw file has escaped characters that need to be cleaned up. Run this Python one-liner:

```bash
python3 -c "
import ast
with open('/tiago_interface/raw_description.txt', 'r') as f:
    content = f.read().strip()
urdf = ast.literal_eval(content)
with open('/tiago_interface/tiago.urdf', 'w') as f:
    f.write(urdf)
print('Done!')
"
```

This creates `tiago.urdf` — a proper XML file that RViz can use.

---

### Step 3 — Upload the URDF back to the robot

```bash
sshpass -p pal scp /tiago_interface/tiago.urdf pal@10.234.6.53:~/tiago.urdf
```

---

### Step 4 — Start a virtual display on the robot

The robot has no physical monitor. We create a virtual one using `Xvfb`, then share it over VNC so you can see it from your computer.

SSH into the robot and start Xvfb:

```bash
sshpass -p pal ssh pal@10.234.6.53 "nohup Xvfb :1 -screen 0 1920x1080x24 > /tmp/xvfb.log 2>&1 &"
```

---

### Step 5 — Start the VNC server on the robot

This shares the virtual display so you can connect to it with TigerVNC:

```bash
sshpass -p pal ssh pal@10.234.6.53 "nohup x11vnc -display :1 -nopw -listen 0.0.0.0 -rfbport 5901 -forever > /tmp/x11vnc.log 2>&1 &"
```

- `-nopw` means no password required
- `-rfbport 5901` is the port TigerVNC will connect to
- `-forever` keeps the server running after you disconnect

---

### Step 6 — Launch RViz on the robot

```bash
sshpass -p pal ssh pal@10.234.6.53 "
export DISPLAY=:1
source /opt/ros/noetic/setup.bash
source /opt/pal/gallium/setup.bash
export ROS_MASTER_URI=http://10.234.6.53:11311
export ROS_IP=10.234.6.53
nohup rviz > /tmp/rviz.log 2>&1 &
"
```

> **Important:** Use `ROS_MASTER_URI=http://10.234.6.53:11311` (the IP, not the hostname `bandit`). Using the hostname can cause RViz to fail to contact the ROS master.

Wait a few seconds for RViz to start.

---

### Step 7 — Connect with TigerVNC

Open TigerVNC Viewer and connect to:

```
10.234.6.53:5901
```

You should see the RViz window on the virtual display.

---

### Step 8 — Configure RViz to show the robot model

Once RViz is open:

1. In the **Displays** panel on the left, find **Fixed Frame** (under Global Options) and set it to:
   ```
   base_footprint
   ```
2. Click the **Add** button at the bottom of the Displays panel
3. Select **RobotModel** from the list and click **OK**

The Tiago robot 3D model will appear in the viewport.

---

### Troubleshooting this setup

**"Could not contact ROS master"** — RViz was launched with the wrong `ROS_MASTER_URI`. Make sure you use the IP address (`10.234.6.53`) not the hostname (`bandit`). Kill RViz and relaunch:
```bash
sshpass -p pal ssh pal@10.234.6.53 "kill \$(pgrep rviz)"
```
Then repeat Step 6.

**VNC shows a blank/black screen** — Xvfb or x11vnc may not have started. Check:
```bash
sshpass -p pal ssh pal@10.234.6.53 "cat /tmp/xvfb.log; cat /tmp/x11vnc.log"
```

**RViz shows no robot model** — The `robot_state_publisher` is already running on the robot from PAL's startup system, so the `/robot_description` parameter should already be set. If the model is missing, make sure you added the **RobotModel** display in Step 8.

---

## Architecture (final)

```
Browser  ──WebSocket──▶  FastAPI backend (:8000)
                              │
                              └──WebSocket──▶  rosbridge (:9090 on bandit)
                                                    │
                                              ROS topics on bandit
                                          /scan, /mobile_base_controller/cmd_vel
```

- **No rospy** in the backend — avoids all ROS networking/IP issues
- **No roslibpy** — avoids Twisted/asyncio conflicts
- **Pure websockets** — asyncio-native, clean integration with FastAPI




## https://colab.research.google.com/drive/1-yZg6hFg27uCPSycRCRtyezHhq_VAHxQ?usp=sharing#scrollTo=71wR2PxM5pfF