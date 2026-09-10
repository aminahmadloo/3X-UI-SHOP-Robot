from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass


@dataclass
class SystemHealthReport:
    cpu: str
    memory: str
    disk: str
    docker: str

    def render(self) -> str:
        return (
            "📊 ToonelVPN System Report\n\n"
            f"🖥 CPU: {self.cpu}\n"
            f"🧠 RAM: {self.memory}\n"
            f"💾 Disk: {self.disk}\n"
            f"🐳 Docker: {self.docker}"
        )


async def collect_system_health() -> SystemHealthReport:
    async def run(cmd: str) -> str:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        return out.decode(errors="ignore").strip()

    cpu = await run("uptime")
    memory = await run("free -h | awk '/Mem:/ {print $3\"/\"$2}'")
    disk = await run("df -h / | awk 'NR==2 {print $3\"/\"$2}'")
    docker = "available" if shutil.which("docker") else "not available"

    return SystemHealthReport(cpu, memory, disk, docker)
