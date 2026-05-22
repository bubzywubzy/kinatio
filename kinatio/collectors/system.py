"""Collector for kernel and OS state."""

from __future__ import annotations

import os
import platform
import socket
from pathlib import Path

import psutil

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import OSState, utc_now
from kinatio.execution.subprocess import SafeSubprocessRunner


class OSStateCollector(Collector):
    name = "os-state"
    subsystem = "os_state"
    interval = 10.0

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> OSState:
        del runner
        sysctl_values: dict[str, str] = {}
        for key in config.sysctl_keys:
            sysctl_path = Path("/proc/sys") / key.replace(".", "/")
            if sysctl_path.exists():
                try:
                    sysctl_values[key] = sysctl_path.read_text(encoding="utf-8").strip()
                except OSError:
                    sysctl_values[key] = "unreadable"
            else:
                sysctl_values[key] = "missing"
        return OSState(
            refreshed_at=utc_now(),
            hostname=socket.gethostname(),
            fqdn=socket.getfqdn(),
            kernel_release=platform.release(),
            kernel_version=platform.version(),
            uptime_seconds=max(0.0, utc_now().timestamp() - psutil.boot_time()),
            load_average=os.getloadavg(),
            sysctl_values=sysctl_values,
        )
