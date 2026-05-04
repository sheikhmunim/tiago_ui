"""
ROS interface via rosbridge WebSocket using pure asyncio websockets.
No Twisted, no threading issues — integrates cleanly with FastAPI.
"""
import asyncio
import json
import logging

log = logging.getLogger(__name__)

ROSBRIDGE_URL    = "ws://bandit:9090"
CMD_VEL_TOPIC    = "/mobile_base_controller/cmd_vel"
SCAN_TOPIC       = "/scan"
DETECTIONS_TOPIC = "/detected_objects"  # published by tiago_vision C++ node


class ROSInterface:
    def __init__(self):
        self._scan_callbacks       = []
        self._detection_callbacks  = []
        self._initialized = False
        self._ws = None

    def start(self):
        # Called from FastAPI lifespan — schedule the connection loop
        asyncio.create_task(self._connect_loop())

    @property
    def is_ready(self) -> bool:
        return self._initialized

    def add_scan_callback(self, cb):
        self._scan_callbacks.append(cb)

    def add_detection_callback(self, cb):
        self._detection_callbacks.append(cb)

    def publish_velocity(self, linear_x: float = 0.0, angular_z: float = 0.0):
        if not self._initialized or self._ws is None:
            return
        asyncio.create_task(self._send({
            "op": "publish",
            "topic": CMD_VEL_TOPIC,
            "msg": {
                "linear":  {"x": float(linear_x), "y": 0.0, "z": 0.0},
                "angular": {"x": 0.0, "y": 0.0, "z": float(angular_z)},
            }
        }))

    def stop(self):
        self.publish_velocity(0.0, 0.0)

    async def _send(self, data: dict):
        try:
            if self._ws:
                await self._ws.send(json.dumps(data))
        except Exception as e:
            log.error(f"send error: {e}")

    async def _connect_loop(self):
        import websockets
        while True:
            try:
                log.info(f"Connecting to rosbridge at {ROSBRIDGE_URL}…")
                async with websockets.connect(ROSBRIDGE_URL) as ws:
                    self._ws = ws
                    # Subscribe to scan
                    await ws.send(json.dumps({
                        "op": "subscribe",
                        "topic": SCAN_TOPIC,
                        "type": "sensor_msgs/LaserScan"
                    }))
                    await ws.send(json.dumps({
                        "op": "subscribe",
                        "topic": DETECTIONS_TOPIC,
                        "type": "tiago_vision/DetectedObjectArray"
                    }))
                    self._initialized = True
                    log.info(f"rosbridge connected — cmd_vel: {CMD_VEL_TOPIC}, "
                             f"scan: {SCAN_TOPIC}, detections: {DETECTIONS_TOPIC}")

                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("op") == "publish" and msg.get("topic") == SCAN_TOPIC:
                            for cb in self._scan_callbacks:
                                try:
                                    cb(msg["msg"])
                                except Exception as e:
                                    log.error(f"scan callback error: {e}")

                        elif msg.get("op") == "publish" and msg.get("topic") == DETECTIONS_TOPIC:
                            for cb in self._detection_callbacks:
                                try:
                                    cb(msg["msg"])
                                except Exception as e:
                                    log.error(f"detection callback error: {e}")

            except Exception as e:
                log.warning(f"rosbridge disconnected ({e}), retrying in 5 s…")
            finally:
                self._initialized = False
                self._ws = None

            await asyncio.sleep(5)
