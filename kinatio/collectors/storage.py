"""Collector for storage, mounts, inodes, and SMART status."""

from __future__ import annotations

import json
import os

import psutil

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import DiskDevice, StorageMount, StorageState, utc_now
from kinatio.execution.subprocess import SafeSubprocessRunner


class StorageCollector(Collector):
    name = "storage"
    subsystem = "storage"
    interval = 15.0

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> StorageState:
        del config
        mounts = self._collect_mounts()
        disks = await self._collect_disks(runner)
        io_counters = self._collect_io()
        return StorageState(refreshed_at=utc_now(), mounts=mounts, disks=disks, io_counters=io_counters)

    def _collect_mounts(self) -> list[StorageMount]:
        mounts: list[StorageMount] = []
        for partition in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                stat = os.statvfs(partition.mountpoint)
            except OSError:
                continue
            inode_total = stat.f_files or 0
            inode_free = stat.f_ffree or 0
            inode_used_percent = None
            if inode_total:
                inode_used_percent = ((inode_total - inode_free) / inode_total) * 100
            mounts.append(
                StorageMount(
                    device=partition.device,
                    mount_point=partition.mountpoint,
                    filesystem=partition.fstype,
                    total_bytes=usage.total,
                    used_bytes=usage.used,
                    free_bytes=usage.free,
                    inode_used_percent=inode_used_percent,
                    options=partition.opts,
                )
            )
        return mounts

    async def _collect_disks(self, runner: SafeSubprocessRunner) -> list[DiskDevice]:
        lsblk = await runner.run(["lsblk", "-b", "-J", "-o", "NAME,MODEL,SERIAL,SIZE,TRAN"], timeout=8.0, allow_missing=True)
        disks: list[DiskDevice] = []
        if lsblk.missing_dependency or lsblk.returncode != 0:
            return disks
        payload = json.loads(lsblk.stdout or "{}")
        for device in payload.get("blockdevices", []):
            smart_available = False
            smart_health = None
            device_name = device.get("name")
            if device_name:
                smart_result = await runner.run(
                    ["smartctl", "-j", "-H", "-A", f"/dev/{device_name}"],
                    timeout=8.0,
                    allow_missing=True,
                )
                if not smart_result.missing_dependency and smart_result.returncode == 0:
                    smart_payload = json.loads(smart_result.stdout or "{}")
                    smart_available = True
                    passed = smart_payload.get("smart_status", {}).get("passed")
                    if passed is not None:
                        smart_health = "passed" if passed else "failed"
                    temperature_celsius = self._extract_smart_temperature(smart_payload)
                else:
                    temperature_celsius = None
            else:
                temperature_celsius = None
            size_text = device.get("size")
            size_bytes = None
            if isinstance(size_text, str) and size_text.isdigit():
                size_bytes = int(size_text)
            elif isinstance(size_text, int):
                size_bytes = size_text
            disks.append(
                DiskDevice(
                    name=device_name or "unknown",
                    model=device.get("model"),
                    serial=device.get("serial"),
                    size_bytes=size_bytes,
                    transport=device.get("tran"),
                    smart_available=smart_available,
                    smart_health=smart_health,
                    temperature_celsius=temperature_celsius,
                )
            )
        return disks

    def _extract_smart_temperature(self, payload: dict[str, object]) -> float | None:
        direct_candidates = (
            self._numeric_value(payload.get("temperature"), "current"),
            self._numeric_value(payload.get("nvme_smart_health_information_log"), "temperature"),
            self._numeric_value(payload.get("scsi_temperature"), "current"),
        )
        for candidate in direct_candidates:
            if candidate is not None:
                return candidate

        ata_attributes = payload.get("ata_smart_attributes")
        if isinstance(ata_attributes, dict):
            table = ata_attributes.get("table")
            if isinstance(table, list):
                for entry in table:
                    if not isinstance(entry, dict):
                        continue
                    name = str(entry.get("name", "")).casefold()
                    if "temp" not in name:
                        continue
                    raw = entry.get("raw")
                    if isinstance(raw, dict):
                        value = raw.get("value")
                        if isinstance(value, (int, float)):
                            return float(value)
                        if isinstance(value, str):
                            try:
                                return float(value)
                            except ValueError:
                                continue
        return None

    def _numeric_value(self, payload: object, key: str) -> float | None:
        if not isinstance(payload, dict):
            return None
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    def _collect_io(self) -> dict[str, dict[str, int | float]]:
        counters = psutil.disk_io_counters(perdisk=True) or {}
        normalized: dict[str, dict[str, int | float]] = {}
        for name, value in counters.items():
            normalized[name] = {
                "read_count": value.read_count,
                "write_count": value.write_count,
                "read_bytes": value.read_bytes,
                "write_bytes": value.write_bytes,
                "busy_time": getattr(value, "busy_time", 0),
            }
        return normalized
