"""
Always-on two-tier safety watchdog.
  WARNING : obstacle < WARN_DIST (1.0 m) — visual alert, audio cue
  DANGER  : obstacle < STOP_DIST (0.5 m) — immediate zero-velocity, block execution

State is updated from the rospy thread; broadcast happens from the asyncio loop.
"""
from __future__ import annotations

import math
import logging
from typing import Optional
from ros_interface import ROSInterface

log = logging.getLogger(__name__)

WARN_DIST = 1.0   # metres
STOP_DIST = 0.5   # metres


class SafetyWatchdog:
    def __init__(self, ros: ROSInterface):
        self.ros = ros
        self.state: str = "DISCONNECTED"   # DISCONNECTED | CLEAR | WARNING | DANGER
        self.min_dist: Optional[float] = None
        self._prev_state: str = "DISCONNECTED"
        ros.add_scan_callback(self._on_scan)

    @property
    def is_safe(self) -> bool:
        return self.state in ("CLEAR", "WARNING")

    def _on_scan(self, msg):
        # roslibpy delivers dicts; support both dict and rospy message objects
        ranges   = msg["ranges"]   if isinstance(msg, dict) else msg.ranges
        rng_min  = msg["range_min"] if isinstance(msg, dict) else msg.range_min
        rng_max  = msg["range_max"] if isinstance(msg, dict) else msg.range_max

        # Filter invalid readings (null values come through as None over rosbridge JSON)
        valid = [
            r for r in ranges
            if r is not None and math.isfinite(r) and rng_min < r < rng_max
        ]
        if not valid:
            self.state = "DISCONNECTED"
            self.min_dist = None
            return

        min_d = min(valid)
        self.min_dist = round(min_d, 3)

        if min_d <= STOP_DIST:
            new_state = "DANGER"
            # Hard stop from scan callback thread — always safe with rospy
            self.ros.stop()
        elif min_d <= WARN_DIST:
            new_state = "WARNING"
        else:
            new_state = "CLEAR"

        self.state = new_state
