"""
FastAPI application entry point.
- Serves the frontend static files
- WebSocket /ws  : real-time safety state, execution progress, launch logs
- POST /execute  : run a block sequence
- POST /abort    : emergency stop
- GET  /status   : system status snapshot
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from executor import BlockExecutor
from launcher import ServiceLauncher
from ros_interface import ROSInterface
from safety import SafetyWatchdog

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self._connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws) if hasattr(self._connections, 'discard') \
            else (self._connections.remove(ws) if ws in self._connections else None)

    async def broadcast(self, data: Dict[str, Any]):
        dead = []
        for ws in self._connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# ---------------------------------------------------------------------------
# Globals (created once, shared via lifespan)
# ---------------------------------------------------------------------------

manager = ConnectionManager()
ros = ROSInterface()
safety = SafetyWatchdog(ros)
executor = BlockExecutor(ros, safety, manager.broadcast)
launcher = ServiceLauncher(manager.broadcast)


def _on_camera_frame(msg: Dict[str, Any]):
    # msg["data"] is already base64-encoded JPEG bytes (rosbridge JSON convention)
    asyncio.create_task(manager.broadcast({
        "type": "camera_frame",
        "data": msg.get("data", ""),
    }))


ros.add_camera_callback(_on_camera_frame)


# Radar HUD: cache the latest scan (downsampled) for the safety_broadcast_loop
# to push at 5 Hz — separate from safety.py's own full-resolution, full-rate
# subscription, so the browser-facing radar can't affect stop-distance timing.
MAX_SCAN_POINTS = 180
_latest_scan: Optional[Dict[str, Any]] = None


def _on_scan_frame(msg: Dict[str, Any]):
    global _latest_scan
    ranges = msg.get("ranges", [])
    step = max(1, len(ranges) // MAX_SCAN_POINTS)
    _latest_scan = {
        "angle_min":       msg.get("angle_min", 0.0),
        "angle_increment": msg.get("angle_increment", 0.0) * step,
        "range_min":       msg.get("range_min", 0.0),
        "range_max":       msg.get("range_max", 0.0),
        "ranges":          ranges[::step],
    }


ros.add_scan_callback(_on_scan_frame)


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def safety_broadcast_loop():
    """Push safety state and a downsampled LIDAR scan (for the radar HUD) to
    all clients at 5 Hz."""
    while True:
        await manager.broadcast({
            "type": "safety",
            "state": safety.state,
            "min_dist": safety.min_dist,
            "ros_ready": ros.is_ready,
        })
        if _latest_scan is not None:
            await manager.broadcast({"type": "scan", **_latest_scan})
        await asyncio.sleep(0.2)


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    ros.start()
    asyncio.create_task(safety_broadcast_loop())
    log.info("ROS interface started — safety watchdog active")
    yield
    ros.stop()


app = FastAPI(title="Tiago Web Interface", lifespan=lifespan)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    # Push current status immediately on connect
    await ws.send_json({
        "type": "safety",
        "state": safety.state,
        "min_dist": safety.min_dist,
        "ros_ready": ros.is_ready,
    })
    await ws.send_json({"type": "service_status", "services": launcher.status()})

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "abort":
                executor.abort()

            elif msg_type == "launch":
                service = data.get("service", "")
                asyncio.create_task(launcher.launch(service))

            elif msg_type == "stop_service":
                service = data.get("service", "")
                asyncio.create_task(launcher.stop(service))

    except WebSocketDisconnect:
        manager.disconnect(ws)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.post("/execute")
async def execute(payload: dict):
    blocks = payload.get("blocks", [])
    if not blocks:
        raise HTTPException(400, "No blocks provided")
    if executor.is_running:
        raise HTTPException(409, "Already executing a sequence")
    if not safety.is_safe:
        raise HTTPException(403, f"Cannot execute — safety state: {safety.state}")

    asyncio.create_task(executor.execute(blocks))
    return {"status": "started", "total": len(blocks)}


@app.post("/abort")
async def abort():
    executor.abort()
    ros.stop()
    return {"status": "aborted"}


@app.get("/status")
async def status():
    return {
        "ros_ready": ros.is_ready,
        "safety": {"state": safety.state, "min_dist": safety.min_dist},
        "executor_running": executor.is_running,
        "services": launcher.status(),
    }


# ---------------------------------------------------------------------------
# Serve frontend (must be last — catches all remaining routes)
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
