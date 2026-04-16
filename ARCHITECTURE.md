# Tiago Web Interface — Architecture Documentation

**Version:** 1.0.0 (Demo)
**ROS Distro:** Noetic
**Robot:** PAL Robotics TiaGo

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Architecture](#2-system-architecture)
3. [Network Layout](#3-network-layout)
4. [Backend](#4-backend)
5. [Frontend](#5-frontend)
6. [Safety System](#6-safety-system)
7. [WebSocket Protocol](#7-websocket-protocol)
8. [REST API](#8-rest-api)
9. [ROS Interface](#9-ros-interface)
10. [Launch System](#10-launch-system)
11. [File Structure](#11-file-structure)
12. [Running the Application](#12-running-the-application)
13. [Configuration](#13-configuration)
14. [Known Limitations & Future Work](#14-known-limitations--future-work)
15. [Version History](#15-version-history)

---

## 1. Overview

The Tiago Web Interface is a browser-based robot control system for the PAL Robotics TiaGo mobile robot. It allows operators to visually program a sequence of robot movements using **Blockly** (a drag-and-drop block programming environment), execute them on the physical robot, and monitor safety in real time.

The system is designed for use in a lab environment where the robot may operate around people. Safety is the primary design constraint — the LiDAR-based watchdog runs continuously and independently of any user action.

### Design Principles

- **Safety first** — the watchdog is always-on, not tied to execution state
- **Simplicity** — no frontend build toolchain; one command starts the entire system
- **Accessibility** — any device on the lab WiFi can open the interface in a browser
- **Graceful degradation** — the server starts and serves the UI even when the robot is unreachable; ROS reconnects automatically

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Lab Network (WiFi)                        │
│                                                                  │
│  ┌──────────────────────────────┐   ┌───────────────────────┐   │
│  │      Lab Computer            │   │   TiaGo Robot         │   │
│  │   (Dev Container)            │   │   hostname: bandit    │   │
│  │                              │   │   IP: 10.234.6.53     │   │
│  │  ┌────────────────────────┐  │   │                       │   │
│  │  │  FastAPI (port 8000)   │  │   │  ┌─────────────────┐  │   │
│  │  │  ├─ Static frontend    │  │   │  │   ROS Master    │  │   │
│  │  │  ├─ WebSocket /ws      │  │   │  │   port 11311    │  │   │
│  │  │  ├─ POST /execute      │◄─┼───┼──►                 │  │   │
│  │  │  └─ POST /abort        │  │   │  ├─────────────────┤  │   │
│  │  │                        │  │   │  │  rosbridge      │  │   │
│  │  │  ┌────────────────────┐│  │   │  │  port 9090      │  │   │
│  │  │  │  rospy (thread)    ││  │   │  ├─────────────────┤  │   │
│  │  │  │  cmd_vel publisher ││  │   │  │ web_video_server│  │   │
│  │  │  │  /scan subscriber  ││  │   │  │  port 8080      │  │   │
│  │  │  └────────────────────┘│  │   │  └─────────────────┘  │   │
│  │  └────────────────────────┘  │   └───────────────────────┘   │
│  └──────────────────────────────┘              ▲                 │
│                ▲                               │                 │
│                │ HTTP / WebSocket              │ MJPEG stream    │
│                │                              │ ws://bandit:9090 │
│  ┌─────────────┴──────────────────────────────┴──────────────┐  │
│  │              Any Browser on Lab WiFi                       │  │
│  │         http://<lab-computer-ip>:8000                      │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Where it runs | Responsibility |
|---|---|---|
| FastAPI server | Lab computer (dev container) | Serves UI, handles execute/abort, bridges browser ↔ ROS |
| rospy thread | Lab computer (dev container) | Publishes `cmd_vel`, subscribes to `/scan` |
| Safety watchdog | Lab computer (dev container) | Always-on obstacle detection, state machine |
| Block executor | Lab computer (dev container) | Runs block sequences step-by-step |
| rosbridge | TiaGo robot | WebSocket gateway to ROS topics (browser-facing) |
| web_video_server | TiaGo robot | Serves camera as MJPEG stream |
| Browser UI | Any lab device | Blockly editor, safety display, launch panel |

---

## 3. Network Layout

| Host | Address | Role |
|---|---|---|
| bandit (TiaGo) | `10.234.6.53` | ROS master, robot hardware |
| Lab computer | Lab WiFi IP (dynamic) | Runs FastAPI, serves the web UI |

### Ports

| Port | Host | Service |
|---|---|---|
| 8000 | Lab computer | FastAPI web server (UI + API) |
| 11311 | bandit | ROS Master (XMLRPC) |
| 9090 | bandit | rosbridge WebSocket |
| 8080 | bandit | web_video_server (MJPEG) |

### Environment Variables (set by `start.sh`)

| Variable | Value | Purpose |
|---|---|---|
| `ROS_MASTER_URI` | `http://bandit:11311` | Points rospy at the robot's ROS master |
| `ROS_IP` | Lab computer's WiFi IP | Tells ROS which IP to use for callbacks |

The dev container runs with `--network=host`, so the container shares the host machine's network stack. Port 8000 on the container is port 8000 on the lab computer.

---

## 4. Backend

The backend is a Python **FastAPI** application (`backend/main.py`) that starts with the ROS Noetic environment sourced. It combines a standard HTTP server, a WebSocket hub, and a rospy node in a single process.

### Module Overview

```
backend/
├── main.py           — FastAPI app, WebSocket manager, REST endpoints
├── ros_interface.py  — rospy node (background thread), cmd_vel, /scan
├── safety.py         — LiDAR safety watchdog, state machine
├── executor.py       — sequential block runner, safety-aware
├── launcher.py       — subprocess manager for ROS services
└── requirements.txt  — Python dependencies
```

### Startup Sequence

```
bash start.sh
    │
    ├─ source /opt/ros/noetic/setup.bash
    ├─ detect bandit reachability (ping)
    ├─ set ROS_MASTER_URI and ROS_IP if reachable
    └─ python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
           │
           ├─ ROSInterface.start()       → background thread, rospy init
           ├─ SafetyWatchdog()           → attaches /scan callback
           ├─ safety_broadcast_loop()    → asyncio task, 5 Hz broadcast
           └─ serve frontend static files
```

### Threading Model

```
Main process (asyncio event loop)
│
├── FastAPI request handlers (async)
├── WebSocket handler (async)
├── safety_broadcast_loop task (async, 5 Hz)
├── BlockExecutor.execute() task (async, created on /execute)
└── ServiceLauncher log stream tasks (async, one per service)

Background thread (daemon)
└── rospy spin loop
    ├── cmd_vel publisher
    └── /scan subscriber → SafetyWatchdog._on_scan() callback
```

rospy runs in a daemon thread and communicates with the asyncio layer through simple shared state variables. Python's GIL makes reads/writes of single object references safe without additional locking. The safety watchdog updates `self.state` and `self.min_dist` from the rospy thread; the asyncio broadcast loop reads them at 5 Hz.

---

## 5. Frontend

A single-page application with no build step. All dependencies loaded from CDN.

```
frontend/
├── index.html    — page structure and layout
└── js/
    ├── blocks.js — custom Blockly block definitions + workspaceToCommands()
    └── app.js    — WebSocket client, UI logic, execute/abort, launch panel
```

### Dependencies (CDN)

| Library | Version | Purpose |
|---|---|---|
| Tailwind CSS | latest (play CDN) | Utility-first styling |
| Blockly | latest (unpkg) | Visual block programming |

### UI Layout

```
┌─────────────────────────────────────────────────────┐
│  SAFETY: ● CLEAR   0.87 m        ○ ROS Ready   [⬛ EMERGENCY STOP] │
├──────────────────────────┬──────────────────────────┤
│                          │                          │
│    Blockly Workspace     │    Robot Camera (MJPEG)  │
│    (drag & drop blocks)  │    <img src=bandit:8080> │
│                          ├──────────────────────────┤
│                          │    Execution Log         │
├─────────┬────────────────┴──────────────────────────┤
│ SERVICES│ [○ ROSBridge] [○ Video Server] [log line] │
├─────────┴──────────────────────────────────────────┤
│  Drag blocks → Execute          [Clear] [▶ Execute] │
└─────────────────────────────────────────────────────┘
```

### Blockly Blocks (v1)

| Block | Color | Parameters | Maps to `action` |
|---|---|---|---|
| Move Forward | Green | speed (m/s), duration (s) | `move_forward` |
| Move Backward | Blue | speed (m/s), duration (s) | `move_backward` |
| Turn Left | Yellow | speed (rad/s), duration (s) | `turn_left` |
| Turn Right | Yellow | speed (rad/s), duration (s) | `turn_right` |
| Stop | Red | — | `stop` |
| Wait | Purple | duration (s) | `wait` |

All blocks use `previousStatement / nextStatement` so they chain vertically. The toolbox presents them in a flyout panel on the left of the workspace.

### Block Execution Flow

```
User clicks Execute
    │
    ├─ workspaceToCommands(workspace)
    │   └─ traverse block chain → [{action, params}, ...]
    │
    ├─ POST /execute  {blocks: [...]}
    │
    └─ Server streams progress via WebSocket /ws
        └─ UI updates execution log per step
```

### WebSocket Auto-Reconnect

The browser WebSocket reconnects automatically on disconnect with exponential backoff (1 s → 2 s → 4 s … max 10 s). Safety state resets to `DISCONNECTED` while disconnected.

---

## 6. Safety System

The safety system is the most critical component. It operates independently of execution state and cannot be disabled from the UI.

### State Machine

```
                  /scan arrives, min > 1.0m
    ┌──────────────────────────────────────┐
    │                                      │
    ▼                                      │
DISCONNECTED ──► CLEAR ──► WARNING ──► DANGER
    ▲               │                    │
    │               │  min < 1.0m        │  min < 0.5m
    │               ▼                    │  → publish zero velocity immediately
    └──── no valid /scan data            │  → abort running sequence
                                         │  → block new /execute calls
                                         ▼
                                    (stays DANGER until
                                     obstacle moves away)
```

### Thresholds (v1 defaults)

| Zone | Distance | UI Color | Robot Action |
|---|---|---|---|
| Clear | > 1.0 m | Green | Normal operation |
| Warning | 0.5 – 1.0 m | Yellow | Audio beep, visual alert |
| Danger | < 0.5 m | Red | Immediate zero-velocity publish, execution abort |
| Disconnected | No `/scan` data | Gray | Cannot execute |

### Implementation Details

- `SafetyWatchdog._on_scan()` runs in the rospy thread for every LiDAR scan
- When `DANGER`: calls `ros.stop()` directly from the callback thread (safe with rospy publishers)
- Invalid scan readings (inf, NaN, out of range) are filtered before computing minimum distance
- The asyncio `safety_broadcast_loop` pushes state to all connected browsers at 5 Hz regardless of state changes
- `BlockExecutor._timed_move()` checks `safety.is_safe` every 100 ms during movement — it does not rely solely on the watchdog stopping the robot

### Emergency Stop Button

Always visible in the top-right corner. Calls `POST /abort` which:
1. Sets the executor abort flag
2. Calls `ros.stop()` (publishes zero velocity)

The button is independent of WebSocket state — it uses a direct HTTP POST.

---

## 7. WebSocket Protocol

All real-time communication uses a single WebSocket endpoint at `ws://<host>:8000/ws`.

### Server → Client messages

**Safety state** (broadcast at 5 Hz):
```json
{
  "type": "safety",
  "state": "CLEAR | WARNING | DANGER | DISCONNECTED",
  "min_dist": 0.87,
  "ros_ready": true
}
```

**Execution progress** (per block event):
```json
{
  "type": "execution",
  "status": "running | step_done | completed | aborted | error",
  "step": 2,
  "total": 4,
  "block": "move_forward",
  "reason": "safety_stop | user_abort",
  "message": "error description"
}
```

**Launch log line** (streamed from subprocess stdout):
```json
{
  "type": "launch_log",
  "service": "rosbridge | web_video_server",
  "line": "...",
  "level": "info | warn | error"
}
```

**Service status** (on connect and on service state change):
```json
{
  "type": "service_status",
  "services": {
    "rosbridge": true,
    "web_video_server": false
  }
}
```

### Client → Server messages

**Abort execution:**
```json
{ "type": "abort" }
```

**Launch a ROS service:**
```json
{ "type": "launch", "service": "rosbridge | web_video_server" }
```

**Stop a ROS service:**
```json
{ "type": "stop_service", "service": "rosbridge | web_video_server" }
```

---

## 8. REST API

Base URL: `http://<lab-computer-ip>:8000`

### `POST /execute`

Start executing a block sequence.

**Request body:**
```json
{
  "blocks": [
    { "action": "move_forward", "params": { "speed": 0.3, "duration": 2.0 } },
    { "action": "turn_left",    "params": { "speed": 0.5, "duration": 1.5 } },
    { "action": "stop",         "params": {} }
  ]
}
```

**Responses:**
| Status | Meaning |
|---|---|
| 200 | Sequence started |
| 400 | No blocks provided |
| 403 | Safety state is DANGER or DISCONNECTED |
| 409 | Another sequence is already running |

Progress is streamed via WebSocket, not this response.

### `POST /abort`

Emergency stop. Aborts execution and publishes zero velocity. Always returns 200.

### `GET /status`

System status snapshot.

```json
{
  "ros_ready": true,
  "safety": { "state": "CLEAR", "min_dist": 1.24 },
  "executor_running": false,
  "services": { "rosbridge": true, "web_video_server": false }
}
```

---

## 9. ROS Interface

### `ros_interface.py` — `ROSInterface`

Manages the rospy node lifecycle in a background daemon thread. If the ROS master is unreachable, it retries every 5 seconds automatically — this means the server can start without the robot and will connect when the robot comes online.

**Published topics:**

| Topic | Message type | Purpose |
|---|---|---|
| `/mobile_base_controller/cmd_vel` | `geometry_msgs/Twist` | Drive the mobile base |

**Subscribed topics:**

| Topic | Message type | Purpose |
|---|---|---|
| `/scan` | `sensor_msgs/LaserScan` | LiDAR data for safety watchdog |

> **Note:** `/scan` is a placeholder. The real topic name will be confirmed during lab testing and updated in `ros_interface.py`.

### Speed Limits

Hard caps enforced in `executor.py` regardless of block field values:

| Direction | Cap |
|---|---|
| Linear (forward/backward) | 0.5 m/s |
| Angular (turn left/right) | 1.0 rad/s |

### `cmd_vel` Publishing Pattern

During timed movement blocks, velocity is re-published every 100 ms. Some ROS mobile base controllers require a continuous stream and will stop automatically if the topic goes silent. The executor's inner loop handles this.

---

## 10. Launch System

`launcher.py` manages rosbridge and web_video_server as child processes of the FastAPI server. Operators start and stop these services from the UI without needing terminal access.

### Managed Services

| Service key | Command |
|---|---|
| `rosbridge` | `roslaunch rosbridge_server rosbridge_websocket.launch` |
| `web_video_server` | `rosrun web_video_server web_video_server` |

Child processes inherit the ROS environment (already sourced when `start.sh` launched FastAPI). stdout and stderr are merged and streamed line-by-line to all connected browsers via the WebSocket `launch_log` message type.

### Service Toggle

Each service button in the UI acts as a toggle:
- `○ ROSBridge` (gray) → click → sends `{"type": "launch", "service": "rosbridge"}`
- `● ROSBridge` (green) → click → sends `{"type": "stop_service", "service": "rosbridge"}`

---

## 11. File Structure

```
tiago_interface/
│
├── .devcontainer/
│   ├── Dockerfile          — ROS Noetic + Node.js 20 + Python deps + ROS packages
│   └── devcontainer.json   — host network, privileged, bandit host entry
│
├── backend/
│   ├── main.py             — FastAPI app, ConnectionManager, lifespan, endpoints
│   ├── ros_interface.py    — rospy node in background thread
│   ├── safety.py           — always-on LiDAR watchdog, two-tier state machine
│   ├── executor.py         — sequential block executor, safety-aware movement loop
│   ├── launcher.py         — subprocess manager for ROS services
│   └── requirements.txt    — fastapi, uvicorn[standard]
│
├── frontend/
│   ├── index.html          — single-page UI (Tailwind + Blockly from CDN)
│   └── js/
│       ├── blocks.js       — 6 custom Blockly block definitions + workspaceToCommands()
│       └── app.js          — WebSocket client, safety UI, execute/abort, launch panel
│
├── start.sh                — entry point: sources ROS env, auto-detects robot, starts uvicorn
└── ARCHITECTURE.md         — this file
```

---

## 12. Running the Application

### Prerequisites

- VS Code with Dev Containers extension
- Dev container built (includes all dependencies)
- Lab computer connected to lab WiFi

### Start

```bash
# Inside the dev container terminal:
bash /tiago_interface/start.sh
```

The script auto-detects whether the robot is reachable:
- **Robot reachable:** sets `ROS_MASTER_URI` and `ROS_IP`, rospy connects
- **Robot not reachable:** starts in UI-only mode, rospy retries every 5 s

### Access

Open in any browser on the lab network:
```
http://<lab-computer-ip>:8000
```
The IP is printed to the terminal on startup.

### Operator Workflow

1. Open the interface in a browser
2. Verify safety bar is green (CLEAR) — if not, check robot connection
3. Click **○ ROSBridge** → wait for green → logs confirm connection
4. Click **○ Video Server** → camera feed appears
5. Drag blocks from the toolbox into the workspace
6. Click **▶ Execute**
7. Watch execution log and safety bar
8. Use **⬛ EMERGENCY STOP** at any time to halt the robot

### Rebuild Container

After changes to `Dockerfile`:

1. `Ctrl+Shift+P` → **Dev Containers: Rebuild Container**
2. Wait for rebuild to complete
3. Run `bash start.sh`

---

## 13. Configuration

Constants that may need updating for different robots or environments:

### `backend/ros_interface.py`
```python
CMD_VEL_TOPIC = "/mobile_base_controller/cmd_vel"
SCAN_TOPIC    = "/scan"
```

### `backend/safety.py`
```python
WARN_DIST = 1.0   # metres — obstacle triggers WARNING below this
STOP_DIST = 0.5   # metres — obstacle triggers DANGER/stop below this
```

### `backend/executor.py`
```python
MAX_LINEAR  = 0.5   # m/s   — hard cap on forward/backward speed
MAX_ANGULAR = 1.0   # rad/s — hard cap on turn speed
```

### `frontend/js/app.js`
```javascript
const CAMERA_TOPIC = "/xtion/rgb/image_raw";       // update to real camera topic
const CAMERA_URL   = `http://bandit:8080/stream…`; // update if web_video_server port differs
```

### `start.sh`
```bash
export ROS_MASTER_URI=http://bandit:11311   # update if robot hostname/IP changes
```

> **Planned (future version):** All of the above will be configurable from the web interface without editing files.

---

## 14. Known Limitations & Future Work

### v1 Limitations

| Limitation | Notes |
|---|---|
| No authentication | Any device on the lab network can control the robot |
| Topics hardcoded | Must edit source files to change ROS topics |
| Robot IP hardcoded | Must edit `start.sh` and `app.js` to change robot |
| Single block chain | Only one top-level chain supported; branching not possible |
| No odometry feedback | Duration-based movement only; no closed-loop position control |
| Camera topic unconfirmed | Placeholder `/xtion/rgb/image_raw` — needs lab verification |

### Planned Features

- **Configurable robot settings** — editable IP, ROS master URI, and topic names from the UI (planned for v2)
- **More Blockly blocks** — speak, head movement, arm gestures, conditional blocks
- **Execution history** — save and reload block programs
- **Multi-device coordination** — currently all clients see the same state, only one should execute at a time
- **Odometry-based movement** — move by distance/angle rather than duration

---

## 15. Version History

| Version | Date | Notes |
|---|---|---|
| 1.0.0 | 2026-03-27 | Initial demo — Blockly UI, FastAPI, safety watchdog, launch panel |

---

*Documentation maintained alongside the codebase. Update this file with every release.*
