# Camera Feed Debug Log — 2026-08-20

## Symptom

Camera feed doesn't show in the frontend UI (stays on "Camera not connected").

## Current data flow (as of Round 2 — see below)

```
Robot camera (xtion) → ROS topic /xtion/rgb/image_raw/compressed → rosbridge (on robot, ws://bandit:9090)
  → backend/ros_interface.py subscribes → backend/main.py broadcasts over app's own /ws
  → frontend/js/app.js sets <img id="camera-img"> src to a base64 data: URI per frame
```

`web_video_server` is no longer part of the picture (removed in Round 2). The sections below are
the original investigation log, kept for the reasoning trail; see "Round 2" further down for the
current fix.

## Investigation

### Data flow (as originally designed — now replaced)

```
Robot camera (xtion) → ROS topic /xtion/rgb/image_raw → web_video_server (MJPEG) → <img> tag in browser
```

- `frontend/js/app.js` set `<img id="camera-img">`'s `src` to a `CAMERA_URL` once the
  `web_video_server` service status came back "running" over the app's own WebSocket.
- `backend/launcher.py` defines how each service is started. Compare the two entries (as they
  were at the time):
  ```python
  SERVICES = {
      "rosbridge":        "sshpass -p pal ssh ... pal@10.234.6.53 \"... rosservice call /pal_startup_startup_extras/start '{app: rosbridge}'\"",
      "web_video_server": "rosrun web_video_server web_video_server",
  }
  ```
  `rosbridge` is SSH'd onto the robot and started **there**. `web_video_server` had no SSH
  wrapper — it started as a **local subprocess inside the dev container**.

### What I checked, and what I found

1. **`bandit` hostname resolution** — works fine. `getent hosts bandit` → `10.234.6.53`. Not the
   problem anywhere.
2. **`bandit:9090` (rosbridge)** — reachable, real service. This is legit because `launcher.py`
   actually starts rosbridge on the robot via SSH.
3. **`bandit:8080` (old `CAMERA_URL` target)** — reachable, but **not web_video_server**. It's a
   PAL Wt-based web app (confirmed via the HTML response: `Wt-form`, `WtTestCookie`, etc. —
   classic Wt C++ toolkit boilerplate). `/stream?...` 404s there. Makes sense: nothing ever
   starts web_video_server on the robot; `launcher.py` starts it locally instead.
4. **Local port 8080** — free in the container. Ran `rosrun web_video_server web_video_server`
   directly: it does bind and serve locally, and `curl http://localhost:8080/stream?...` returns
   `200 OK`.
5. **ROS topic `/xtion/rgb/image_raw`** — exists, correct type (`sensor_msgs/Image`), has a
   registered publisher (`/xtion/xtion_nodelet_manager`) and web_video_server successfully
   registers as a subscriber. BUT: `rostopic hz /xtion/rgb/image_raw` (and
   `/xtion/rgb/camera_info`, `/xtion/depth/image_raw`) all showed **"no new messages"** for 6+
   seconds — topic registration works, but zero image bytes actually flow.
6. **Root cause of #5** — the publisher node advertises itself to the ROS graph as
   `http://tiago-219c:45045/` (the robot's *internal* hostname), not `bandit`. This container's
   `/etc/hosts` only had `bandit`, no `tiago-219c` entry (`getent hosts tiago-219c` → nothing).
   ROS topic *registration* goes through the master (`bandit:11311`), so `rostopic list/info`
   look fine — but the actual TCPROS data connection is direct subscriber→publisher and needs to
   resolve `tiago-219c`, which failed silently.
   - Confirmed `tiago-219c` and `bandit` are literally the same machine: a raw TCP connect to
     `10.234.6.53:45045` (the exact port `tiago-219c` advertises) succeeded.
   - This would block **any** ROS image consumer in this container, not just web_video_server.

### Conclusion: two separate bugs, not one

| # | Bug | Effect |
|---|---|---|
| 1 | `app.js` hardcoded `http://bandit:8080`, but `web_video_server` actually runs locally in the container | Frontend requests the stream from the wrong machine (hits PAL's unrelated Wt app on the robot instead) |
| 2 | Container can't resolve `tiago-219c` (robot's internal ROS hostname) | Even a correctly-addressed web_video_server would receive zero image bytes — this is why my live test showed `200 OK` but `0 bytes downloaded` over 3s |

Bug #2 was the actual blocker — fixing #1 alone would've connected but shown a stream with no frames.

## Fixes applied (round 1 — superseded, see "Round 2" below)

Chose "Option B": keep `web_video_server` running locally in the dev container (simpler,
no SSH-based remote launch needed), and point the frontend at wherever it's actually running.

**1. `.devcontainer/devcontainer.json`** — added a second `--add-host` entry so the container can
resolve the robot's internal ROS hostname (same IP as `bandit`, confirmed above):
```diff
     "--network=host",
-    "--add-host=bandit:10.234.6.53"
+    "--add-host=bandit:10.234.6.53",
+    "--add-host=tiago-219c:10.234.6.53"
```

**2. `frontend/js/app.js`** (~line 14-15) — point `CAMERA_URL` at the page's own host instead of
the robot, since `web_video_server` runs locally, not on the robot:
```diff
-const CAMERA_URL    = `http://bandit:8080/stream?topic=${CAMERA_TOPIC}&type=mjpeg`;
+const CAMERA_URL    = `http://${location.hostname}:8080/stream?topic=${CAMERA_TOPIC}&type=mjpeg`;
```

This fixed bug #1 and, after a container rebuild, bug #2 as well — `rostopic hz
/xtion/rgb/image_raw` confirmed real data flowing (~7.5 Hz raw, ~30 Hz compressed) once
`tiago-219c` resolved. But it left `web_video_server` as a second HTTP server the launcher has
to manage, and that turned out to be a recurring source of pain (see Round 2).

## Round 2 — dropped web_video_server, stream over rosbridge instead

**Why**: `web_video_server` runs as a local subprocess (`launcher.py`) and needs port 8080. In
practice this kept causing `bind: Address already in use` failures — stale/orphaned processes
from previous runs (e.g. a force-killed backend leaves its `web_video_server` child running,
reparented to init) would silently squat on the port, and every subsequent "Video Server" launch
attempt aborted with `boost::wrapexcept<boost::system::system_error>`. It's a whole extra service
with its own failure mode, for something the app already has a working channel for.

**Key realization**: `rosbridge` is SSH'd onto the robot and runs **there** (see
`launcher.py`'s `SERVICES["rosbridge"]`). That means a rosbridge subscription to the camera
topic is a *local* ROS subscription on the robot — no cross-machine TCPROS connection, no
`tiago-219c` hostname resolution needed at all. `web_video_server` was the one service that
*wasn't* colocated with the ROS graph; removing it removes the problem at its root instead of
working around it.

**Verified before implementing**: subscribed directly to `/xtion/rgb/image_raw/compressed`
through `ws://bandit:9090` (rosbridge) in a standalone script — confirmed real JPEG frames
(`\xff\xd8` magic bytes) arriving at ~5 Hz (throttled).

**Changes**:

1. **`backend/ros_interface.py`** — subscribe to `/xtion/rgb/image_raw/compressed`
   (`sensor_msgs/CompressedImage`, `throttle_rate: 200`ms) alongside the existing `/scan` and
   `/detected_objects` subscriptions on the same rosbridge websocket. New `add_camera_callback`
   hook mirrors the existing scan/detection callback pattern.
2. **`backend/main.py`** — forwards each frame to all connected UI clients over the app's own
   `/ws` as `{"type": "camera_frame", "data": "<base64 jpeg>"}`.
3. **`frontend/js/app.js`** — removed `CAMERA_URL`/`CAMERA_TOPIC` and the `web_video_server`
   image-src wiring entirely. On a `camera_frame` message:
   `cameraImg.src = "data:image/jpeg;base64," + data.data`. Camera view also clears on `/ws`
   disconnect (frames just stop arriving otherwise, leaving a stale last frame on screen).
4. **`backend/launcher.py`**, **`frontend/index.html`** — removed `web_video_server` from
   `SERVICES` and deleted the now-dead "Video Server" button (nothing launches it anymore).

**Verified after implementing**: connected a raw client to the app's real `/ws` endpoint (same
path the browser uses) and confirmed `camera_frame` messages arrive with valid decoded JPEG
bytes. `GET /status` now reports `"services": {}` once rosbridge is already up — nothing left to
manually launch for the camera to work.

**Net effect**: the `tiago-219c` host-mapping fix from Round 1 is no longer load-bearing for the
camera (nothing in the new path does a direct TCPROS connection from inside the container), but
it's left in `devcontainer.json` since other tooling (e.g. `rostopic hz` from a terminal in the
container) still benefits from being able to resolve the robot's internal hostname.

## Open items / things to watch (not yet fixed, lower priority)

- **No readiness check**: `launcher.py` marks a service "running" as soon as the subprocess
  spawns (`proc.returncode is None`), not once it's actually functional. Not camera-relevant
  anymore, but still applies to `rosbridge`.
- Frame rate is throttled to ~5 fps (`CAMERA_THROTTLE_MS` in `ros_interface.py`) to keep
  base64-over-JSON bandwidth reasonable. Bump if smoother video is needed and bandwidth allows.
- `.devcontainer/Dockerfile` still installs the `ros-noetic-web-video-server` apt package even
  though nothing uses it now — left in place since it's inert, but could be dropped on a future
  Dockerfile cleanup pass.
