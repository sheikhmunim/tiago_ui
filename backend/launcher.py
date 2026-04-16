"""
Launches and monitors ROS services (rosbridge, web_video_server) as subprocesses.
Streams stdout/stderr back via a broadcast callback.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable, Dict

log = logging.getLogger(__name__)

SERVICES: Dict[str, str] = {
    "rosbridge": "sshpass -p pal ssh -o StrictHostKeyChecking=no pal@10.234.6.53 \"source /opt/ros/noetic/setup.bash && source /opt/pal/gallium/setup.bash && rosservice call /pal_startup_startup_extras/start '{app: rosbridge}'\"",
    "web_video_server": "rosrun web_video_server web_video_server",
}


class ServiceLauncher:
    def __init__(self, broadcast: Callable[[dict], Awaitable[None]]):
        self.broadcast = broadcast
        self._processes: Dict[str, asyncio.subprocess.Process] = {}

    def status(self) -> Dict[str, bool]:
        return {
            name: (proc.returncode is None)
            for name, proc in self._processes.items()
        }

    async def launch(self, service: str):
        if service not in SERVICES:
            await self.broadcast({"type": "launch_log", "service": service,
                                  "line": f"Unknown service: {service}", "level": "error"})
            return

        if service in self._processes and self._processes[service].returncode is None:
            await self.broadcast({"type": "launch_log", "service": service,
                                  "line": f"{service} is already running", "level": "info"})
            return

        cmd = SERVICES[service]
        await self.broadcast({"type": "launch_log", "service": service,
                               "line": f"Starting: {cmd}", "level": "info"})

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            self._processes[service] = proc
            await self._emit_status()
            asyncio.create_task(self._stream_output(service, proc))
        except Exception as e:
            await self.broadcast({"type": "launch_log", "service": service,
                                  "line": f"Failed to start: {e}", "level": "error"})

    async def stop(self, service: str):
        proc = self._processes.get(service)
        if proc and proc.returncode is None:
            proc.terminate()
            await self.broadcast({"type": "launch_log", "service": service,
                                  "line": f"Stopping {service}…", "level": "info"})
            await self._emit_status()

    async def _stream_output(self, service: str, proc: asyncio.subprocess.Process):
        try:
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                if line:
                    await self.broadcast({"type": "launch_log", "service": service,
                                          "line": line, "level": "info"})
        except Exception as e:
            log.error(f"Log stream error for {service}: {e}")
        finally:
            await proc.wait()
            await self.broadcast({"type": "launch_log", "service": service,
                                  "line": f"{service} exited (code {proc.returncode})",
                                  "level": "warn"})
            await self._emit_status()

    async def _emit_status(self):
        await self.broadcast({"type": "service_status", "services": self.status()})
