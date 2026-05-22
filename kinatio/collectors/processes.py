"""Collector for live process state."""

from __future__ import annotations

import asyncio
from time import monotonic

import psutil

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import ProcessEntry, ProcessesState, utc_now
from kinatio.execution.subprocess import SafeSubprocessRunner


class ProcessesCollector(Collector):
    name = "processes"
    subsystem = "processes"
    interval = 4.0

    def __init__(self) -> None:
        self._previous_cpu_samples: dict[int, tuple[float, float]] = {}

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> ProcessesState:
        del runner
        entries: list[ProcessEntry] = []
        sample_time = monotonic()
        processes = await asyncio.to_thread(list, psutil.process_iter(
            attrs=["pid", "name", "username", "status", "cmdline", "memory_info", "memory_percent", "cpu_times"]
        ))
        current_pids: set[int] = set()
        for process in processes:
            try:
                info = process.info
                pid = info["pid"]
                current_pids.add(pid)
                command = " ".join(info.get("cmdline") or [])
                memory_info = info.get("memory_info")
                cpu_percent = self._cpu_percent_for_process(pid, info.get("cpu_times"), sample_time)
                entries.append(
                    ProcessEntry(
                        pid=pid,
                        name=info.get("name") or "unknown",
                        username=info.get("username"),
                        status=info.get("status"),
                        cpu_percent=cpu_percent,
                        memory_percent=info.get("memory_percent") or 0.0,
                        rss_bytes=getattr(memory_info, "rss", 0),
                        command=command,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        self._previous_cpu_samples = {
            pid: sample for pid, sample in self._previous_cpu_samples.items() if pid in current_pids
        }
        entries.sort(key=lambda entry: (entry.cpu_percent, entry.memory_percent), reverse=True)
        limited = entries[: config.max_process_entries]
        return ProcessesState(
            refreshed_at=utc_now(),
            total_processes=len(entries),
            entries=limited,
        )

    def _cpu_percent_for_process(self, pid: int, cpu_times: object, sample_time: float) -> float:
        total_cpu_time = getattr(cpu_times, "user", 0.0) + getattr(cpu_times, "system", 0.0)
        previous_sample = self._previous_cpu_samples.get(pid)
        self._previous_cpu_samples[pid] = (sample_time, total_cpu_time)
        if previous_sample is None:
            return 0.0
        previous_time, previous_cpu_time = previous_sample
        elapsed = sample_time - previous_time
        if elapsed <= 0:
            return 0.0
        cpu_percent = ((total_cpu_time - previous_cpu_time) / elapsed) * 100.0
        return max(0.0, cpu_percent)
