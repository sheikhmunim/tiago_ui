"""
Block sequence executor.
Runs each block in order, checking safety and abort flag every 100 ms during movement.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable, List, Optional

from ros_interface import ROSInterface
from safety import SafetyWatchdog

log = logging.getLogger(__name__)

# Speed limits (m/s and rad/s) — safety caps regardless of block values
MAX_LINEAR  = 0.5   # m/s
MAX_ANGULAR = 1.0   # rad/s


class BlockExecutor:
    def __init__(self, ros: ROSInterface, safety: SafetyWatchdog,
                 broadcast: Callable[[dict], Awaitable[None]]):
        self.ros = ros
        self.safety = safety
        self.broadcast = broadcast
        self._running = False
        self._abort = False

    @property
    def is_running(self) -> bool:
        return self._running

    def abort(self):
        self._abort = True
        self.ros.stop()
        log.info("Executor: abort requested")

    async def execute(self, blocks: List[dict]):
        if self._running:
            raise RuntimeError("Already executing")
        if not self.safety.is_safe:
            raise RuntimeError(f"Safety state is {self.safety.state} — cannot execute")

        self._running = True
        self._abort = False
        total = len(blocks)

        try:
            for i, block in enumerate(blocks):
                if self._abort:
                    await self.broadcast({"type": "execution", "status": "aborted",
                                          "step": i + 1, "total": total, "reason": "user_abort"})
                    break

                if not self.safety.is_safe:
                    await self.broadcast({"type": "execution", "status": "aborted",
                                          "step": i + 1, "total": total, "reason": "safety_stop"})
                    self.ros.stop()
                    break

                await self._broadcast_step("running", block, i + 1, total)

                await self._run_block(block, i + 1, total)

                await self._broadcast_step("step_done", block, i + 1, total)

            else:
                # All blocks completed
                await self.broadcast({"type": "execution", "status": "completed",
                                      "step": total, "total": total})
        except Exception as e:
            log.error(f"Executor error: {e}")
            await self.broadcast({"type": "execution", "status": "error", "message": str(e)})
        finally:
            self._running = False
            self.ros.stop()

    async def _broadcast_step(self, status: str, block: dict, step: int, total: int):
        """Broadcast a running/step_done event for a single block, carrying its
        Blockly id so the frontend can highlight the exact block instance —
        including blocks nested inside if_else branches."""
        await self.broadcast({
            "type": "execution", "status": status,
            "step": step, "total": total,
            "block": block.get("action"), "id": block.get("id"),
        })

    async def _run_block(self, block: dict, step: int, total: int):
        action = block.get("action")
        params = block.get("params", {})

        if action == "move_forward":
            speed = min(float(params.get("speed", 0.3)), MAX_LINEAR)
            await self._timed_move(linear_x=speed, duration=float(params.get("duration", 2.0)))

        elif action == "move_backward":
            speed = min(float(params.get("speed", 0.3)), MAX_LINEAR)
            await self._timed_move(linear_x=-speed, duration=float(params.get("duration", 2.0)))

        elif action == "turn_left":
            speed = min(float(params.get("speed", 0.5)), MAX_ANGULAR)
            await self._timed_move(angular_z=speed, duration=float(params.get("duration", 2.0)))

        elif action == "turn_right":
            speed = min(float(params.get("speed", 0.5)), MAX_ANGULAR)
            await self._timed_move(angular_z=-speed, duration=float(params.get("duration", 2.0)))

        elif action == "stop":
            self.ros.stop()

        elif action == "wait":
            await self._interruptible_sleep(float(params.get("duration", 1.0)))

        elif action == "if_else":
            condition = block.get("condition")
            if self._evaluate_condition(condition):
                await self._execute_blocks(block.get("then", []), step, total)
            else:
                await self._execute_blocks(block.get("else", []), step, total)

        else:
            log.warning(f"Unknown block action: {action}")

    async def _execute_blocks(self, blocks: List[dict], parent_step: int, parent_total: int):
        """Recursively execute a list of blocks (used for nested control structures).
        Broadcasts running/step_done for each nested block under the parent
        if_else's step number, so the currently-executing child block can be
        highlighted the same way a top-level block is."""
        for block in blocks:
            if self._abort or not self.safety.is_safe:
                break
            await self._broadcast_step("running", block, parent_step, parent_total)
            await self._run_block(block, parent_step, parent_total)
            await self._broadcast_step("step_done", block, parent_step, parent_total)

    def _evaluate_condition(self, condition: Optional[dict]) -> bool:
        """Evaluate a lidar_compare condition against the current LiDAR reading."""
        if not condition:
            return False
        op    = condition.get("op", "<")
        value = float(condition.get("value", 1.0))
        dist  = self.safety.min_dist
        if dist is None:
            return False
        if op == "<":
            return dist < value
        if op == ">":
            return dist > value
        return False

    async def _timed_move(self, linear_x: float = 0.0, angular_z: float = 0.0,
                          duration: float = 2.0):
        """Move for `duration` seconds, checking safety and abort every 100 ms."""
        elapsed = 0.0
        interval = 0.1
        self.ros.publish_velocity(linear_x, angular_z)
        while elapsed < duration:
            if self._abort or not self.safety.is_safe:
                break
            await asyncio.sleep(interval)
            elapsed += interval
            # Keep publishing — cmd_vel needs a continuous stream on some controllers
            self.ros.publish_velocity(linear_x, angular_z)
        self.ros.stop()

    async def _interruptible_sleep(self, duration: float):
        elapsed = 0.0
        interval = 0.1
        while elapsed < duration:
            if self._abort or not self.safety.is_safe:
                break
            await asyncio.sleep(interval)
            elapsed += interval
