"""Collector for hardware topology and memory metrics."""

from __future__ import annotations

import asyncio
import platform
import re
from dataclasses import dataclass
from pathlib import Path

import psutil

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import CPUCoreInfo, CPUInfo, DeviceInfo, GPUInfo, GPUWorkloadInfo, HardwareState, MemoryInfo, utc_now
from kinatio.execution.subprocess import SafeSubprocessRunner


@dataclass(slots=True)
class _GPUWorkloadSample:
    bus_id: str | None
    workload: GPUWorkloadInfo


class HardwareCollector(Collector):
    name = "hardware"
    subsystem = "hardware"
    interval = 10.0

    _PCI_BUS_ID_PATTERN = re.compile(
        r"^(?:(?P<domain>[0-9a-f]{4}|[0-9a-f]{8}):)?(?P<bus>[0-9a-f]{2}):(?P<device>[0-9a-f]{2})\.(?P<function>[0-7])$",
        re.IGNORECASE,
    )
    _GPU_PCI_KEYWORDS = ("vga compatible controller", "3d controller", "display controller")
    _GPU_VENDOR_LABELS = {
        "0x10de": "NVIDIA",
        "0x1002": "AMD",
        "0x1022": "AMD",
        "0x8086": "Intel",
    }

    def __init__(self) -> None:
        self._cpuinfo_path = Path("/proc/cpuinfo")
        self._drm_root = Path("/sys/class/drm")

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> HardwareState:
        del config
        cpu_freq = psutil.cpu_freq()
        per_core = await asyncio.to_thread(psutil.cpu_percent, 0.1, True)
        cpu_total = (sum(per_core) / len(per_core)) if per_core else 0.0
        virtual_memory = psutil.virtual_memory()
        swap_memory = psutil.swap_memory()
        cpu_model_name = await asyncio.to_thread(self._read_cpu_model_name)
        cpu_architecture = platform.machine() or None

        pci_devices = await self._collect_devices(runner, ["lspci"])
        usb_devices = await self._collect_devices(runner, ["lsusb"])
        gpus = await self._collect_gpus(runner, pci_devices)

        return HardwareState(
            refreshed_at=utc_now(),
            cpu=CPUInfo(
                logical_cores=psutil.cpu_count() or 0,
                physical_cores=psutil.cpu_count(logical=False),
                model_name=cpu_model_name,
                architecture=cpu_architecture,
                frequency_current_mhz=cpu_freq.current if cpu_freq else None,
                frequency_max_mhz=cpu_freq.max if cpu_freq and cpu_freq.max > 0 else None,
                load_percent=cpu_total,
                per_core=[CPUCoreInfo(index=index, percent=value) for index, value in enumerate(per_core)],
            ),
            memory=MemoryInfo(
                total_bytes=virtual_memory.total,
                available_bytes=virtual_memory.available,
                used_bytes=virtual_memory.used,
                percent=virtual_memory.percent,
                swap_total_bytes=swap_memory.total,
                swap_used_bytes=swap_memory.used,
                swap_percent=swap_memory.percent,
            ),
            gpus=gpus,
            pci_devices=pci_devices,
            usb_devices=usb_devices,
        )

    def _read_cpu_model_name(self) -> str | None:
        try:
            for line in self._cpuinfo_path.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition(":")
                if key.strip().casefold() == "model name":
                    model_name = value.strip()
                    if model_name:
                        return model_name
        except OSError:
            return None
        return None

    async def _collect_devices(
        self,
        runner: SafeSubprocessRunner,
        command: list[str],
    ) -> list[DeviceInfo]:
        result = await runner.run(command, timeout=5.0, allow_missing=True)
        if result.missing_dependency:
            return []
        devices: list[DeviceInfo] = []
        for line in result.stdout.splitlines()[:100]:
            text = line.strip()
            if not text:
                continue
            identifier, _, description = text.partition(" ")
            devices.append(
                DeviceInfo(
                    category=command[0],
                    identifier=identifier,
                    description=description.strip(),
                )
            )
        return devices

    async def _collect_gpus(
        self,
        runner: SafeSubprocessRunner,
        pci_devices: list[DeviceInfo],
    ) -> list[GPUInfo]:
        gpu_map: dict[str, GPUInfo] = {}
        for device in pci_devices:
            if not self._is_gpu_pci_device(device.description):
                continue
            bus_id = self._normalize_bus_id(device.identifier) or device.identifier
            gpu_map[self._gpu_identity_key(bus_id, device.description)] = GPUInfo(
                name=device.description or "PCI graphics adapter",
                vendor=self._gpu_vendor_from_text(device.description),
                bus_id=bus_id,
                backend="pci",
            )

        nvidia_gpus = await self._collect_nvidia_gpu_telemetry(runner)
        for gpu in nvidia_gpus:
            self._merge_gpu(gpu_map, gpu)

        if nvidia_gpus:
            workload_samples = await self._collect_nvidia_gpu_workloads(runner)
            self._set_gpu_workload_source(gpu_map, source="nvidia-smi")
            self._merge_gpu_workloads(gpu_map, workload_samples)

        for gpu in await asyncio.to_thread(self._collect_drm_gpu_telemetry):
            self._merge_gpu(gpu_map, gpu)

        return sorted(
            gpu_map.values(),
            key=lambda gpu: ((gpu.bus_id or "").casefold(), gpu.name.casefold()),
        )

    def _is_gpu_pci_device(self, description: str) -> bool:
        lowered = description.casefold()
        return any(keyword in lowered for keyword in self._GPU_PCI_KEYWORDS)

    def _gpu_identity_key(self, bus_id: str | None, name: str) -> str:
        return (bus_id or name).casefold()

    def _merge_gpu(self, gpu_map: dict[str, GPUInfo], candidate: GPUInfo) -> None:
        key = self._gpu_identity_key(self._normalize_bus_id(candidate.bus_id), candidate.name)
        existing = gpu_map.get(key)
        if existing is None:
            gpu_map[key] = candidate
            return

        existing_rank = self._gpu_backend_rank(existing.backend)
        candidate_rank = self._gpu_backend_rank(candidate.backend)

        if candidate.name and (
            not existing.name
            or (self._is_generic_gpu_name(existing.name) and not self._is_generic_gpu_name(candidate.name))
            or (candidate_rank > existing_rank and not self._is_generic_gpu_name(candidate.name))
        ):
            existing.name = candidate.name
        for field in (
            "vendor",
            "bus_id",
            "driver",
            "backend",
            "memory_total_bytes",
            "memory_used_bytes",
            "utilization_percent",
            "temperature_celsius",
            "workload_source",
        ):
            value = getattr(candidate, field)
            if value is not None:
                current_value = getattr(existing, field)
                if current_value is None:
                    setattr(existing, field, value)
                    continue
                if field == "driver" and self._looks_like_driver_version(value) and not self._looks_like_driver_version(current_value):
                    setattr(existing, field, value)
                    continue
                if candidate_rank > existing_rank:
                    setattr(existing, field, value)
        if candidate.backend is not None and (existing.backend is None or candidate_rank > existing_rank):
            existing.backend = candidate.backend
        if candidate.workloads:
            self._merge_workload_list(existing, candidate.workloads)

    def _set_gpu_workload_source(self, gpu_map: dict[str, GPUInfo], *, source: str) -> None:
        for gpu in gpu_map.values():
            if gpu.vendor == "NVIDIA" or gpu.backend == "nvidia-smi":
                gpu.workload_source = source

    def _merge_gpu_workloads(self, gpu_map: dict[str, GPUInfo], samples: list[_GPUWorkloadSample]) -> None:
        for sample in samples:
            normalized_bus_id = self._normalize_bus_id(sample.bus_id)
            target = None
            if normalized_bus_id is not None:
                target = gpu_map.get(self._gpu_identity_key(normalized_bus_id, sample.workload.process_name))
                if target is None:
                    for gpu in gpu_map.values():
                        if self._normalize_bus_id(gpu.bus_id) == normalized_bus_id:
                            target = gpu
                            break
            if target is None:
                continue
            self._merge_workload_list(target, [sample.workload])

    def _merge_workload_list(self, gpu: GPUInfo, workloads: list[GPUWorkloadInfo]) -> None:
        seen = {
            (
                workload.pid,
                workload.process_name.casefold(),
                workload.kind or "",
                workload.gpu_memory_bytes,
            )
            for workload in gpu.workloads
        }
        for workload in workloads:
            key = (
                workload.pid,
                workload.process_name.casefold(),
                workload.kind or "",
                workload.gpu_memory_bytes,
            )
            if key in seen:
                continue
            gpu.workloads.append(workload)
            seen.add(key)

    async def _collect_nvidia_gpu_telemetry(self, runner: SafeSubprocessRunner) -> list[GPUInfo]:
        result = await runner.run(
            [
                "nvidia-smi",
                "--query-gpu=name,pci.bus_id,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            timeout=8.0,
            allow_missing=True,
        )
        if result.missing_dependency or result.returncode != 0:
            return []

        gpus: list[GPUInfo] = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 7:
                continue
            name, bus_id, driver, memory_total, memory_used, utilization, temperature = parts
            gpus.append(
                GPUInfo(
                    name=name or "NVIDIA GPU",
                    vendor="NVIDIA",
                    bus_id=self._normalize_bus_id(bus_id) or bus_id or None,
                    driver=driver or None,
                    backend="nvidia-smi",
                    memory_total_bytes=self._mib_to_bytes(memory_total),
                    memory_used_bytes=self._mib_to_bytes(memory_used),
                    utilization_percent=self._float_or_none(utilization),
                    temperature_celsius=self._float_or_none(temperature),
                )
            )
        return gpus

    async def _collect_nvidia_gpu_workloads(self, runner: SafeSubprocessRunner) -> list[_GPUWorkloadSample]:
        result = await runner.run(
            [
                "nvidia-smi",
                "--query-compute-apps=gpu_bus_id,pid,process_name,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            timeout=8.0,
            allow_missing=True,
        )
        if result.missing_dependency or result.returncode != 0:
            return []

        samples: list[_GPUWorkloadSample] = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 4:
                continue
            bus_id, pid_text, process_name, used_memory = parts
            pid = self._int_or_none(pid_text)
            resolved_name, resolved_command = self._resolve_process_identity(pid, fallback_name=process_name)
            samples.append(
                _GPUWorkloadSample(
                    bus_id=self._normalize_bus_id(bus_id) or bus_id or None,
                    workload=GPUWorkloadInfo(
                        pid=pid,
                        process_name=resolved_name,
                        command=resolved_command,
                        gpu_memory_bytes=self._mib_to_bytes(used_memory),
                        kind="compute",
                    ),
                )
            )
        return samples

    def _collect_drm_gpu_telemetry(self) -> list[GPUInfo]:
        if not self._drm_root.exists():
            return []

        gpus: list[GPUInfo] = []
        for card in sorted(self._drm_root.iterdir()):
            if not card.name.startswith("card") or not card.name[4:].isdigit():
                continue
            device_root = card / "device"
            if not device_root.exists():
                continue
            bus_id = self._read_pci_slot_name(device_root)
            vendor_id = self._read_text(device_root / "vendor")
            driver_name = None
            driver_link = device_root / "driver"
            if driver_link.exists():
                try:
                    driver_name = driver_link.resolve().name
                except OSError:
                    driver_name = driver_link.name
            gpus.append(
                GPUInfo(
                    name=f"{self._vendor_label(vendor_id) or 'GPU'} {card.name}",
                    vendor=self._vendor_label(vendor_id),
                    bus_id=bus_id,
                    driver=driver_name,
                    backend="drm",
                    memory_total_bytes=self._int_from_file(device_root / "mem_info_vram_total"),
                    memory_used_bytes=self._int_from_file(device_root / "mem_info_vram_used"),
                    utilization_percent=self._float_from_file(device_root / "gpu_busy_percent"),
                    temperature_celsius=self._read_hwmon_temperature(device_root),
                )
            )
        return gpus

    def _read_pci_slot_name(self, device_root: Path) -> str | None:
        uevent_text = self._read_text(device_root / "uevent")
        if not uevent_text:
            return None
        for line in uevent_text.splitlines():
            if line.startswith("PCI_SLOT_NAME="):
                return self._normalize_bus_id(line.partition("=")[2].strip())
        return None

    def _read_hwmon_temperature(self, device_root: Path) -> float | None:
        candidates: list[float] = []
        for temp_path in sorted(device_root.glob("hwmon/hwmon*/temp*_input")):
            value = self._float_from_file(temp_path)
            if value is None:
                continue
            if value > 1000:
                value /= 1000.0
            candidates.append(value)
        return max(candidates) if candidates else None

    def _read_text(self, path: Path) -> str | None:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value or None

    def _int_from_file(self, path: Path) -> int | None:
        value = self._read_text(path)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _float_from_file(self, path: Path) -> float | None:
        value = self._read_text(path)
        return self._float_or_none(value)

    def _normalize_bus_id(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        match = self._PCI_BUS_ID_PATTERN.fullmatch(normalized)
        if match is None:
            return normalized
        domain_text = match.group("domain") or "0000"
        domain_value = int(domain_text, 16) & 0xFFFF
        return (
            f"{domain_value:04x}:{match.group('bus').lower()}:"
            f"{match.group('device').lower()}.{match.group('function')}"
        )

    def _gpu_backend_rank(self, backend: str | None) -> int:
        ranks = {
            "pci": 0,
            "drm": 1,
            "nvidia-smi": 2,
        }
        return ranks.get((backend or "").casefold(), 0)

    def _is_generic_gpu_name(self, name: str | None) -> bool:
        if not name:
            return True
        normalized = name.strip().casefold()
        if normalized in {"gpu", "pci graphics adapter"}:
            return True
        return bool(re.fullmatch(r"(?:gpu|nvidia|amd|intel) card\d+", normalized))

    def _looks_like_driver_version(self, value: object) -> bool:
        if not isinstance(value, str):
            return False
        return bool(re.fullmatch(r"\d+(?:\.\d+)+", value.strip()))

    def _gpu_vendor_from_text(self, description: str) -> str | None:
        lowered = description.casefold()
        if "nvidia" in lowered:
            return "NVIDIA"
        if "advanced micro devices" in lowered or "amd" in lowered or "ati" in lowered:
            return "AMD"
        if "intel" in lowered:
            return "Intel"
        return None

    def _vendor_label(self, vendor_id: str | None) -> str | None:
        if vendor_id is None:
            return None
        return self._GPU_VENDOR_LABELS.get(vendor_id.casefold())

    def _mib_to_bytes(self, value: str | None) -> int | None:
        numeric = self._float_or_none(value)
        if numeric is None:
            return None
        return int(numeric * 1024 * 1024)

    def _float_or_none(self, value: str | None) -> float | None:
        if value is None:
            return None
        text = value.strip()
        if not text or text.casefold() in {"n/a", "not supported", "unknown"}:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _int_or_none(self, value: str | None) -> int | None:
        numeric = self._float_or_none(value)
        if numeric is None:
            return None
        return int(numeric)

    def _resolve_process_identity(self, pid: int | None, *, fallback_name: str) -> tuple[str, str | None]:
        if pid is None:
            return fallback_name or "unknown", None
        try:
            process = psutil.Process(pid)
            command = " ".join(process.cmdline()).strip() or None
            process_name = process.name() or fallback_name or "unknown"
            return process_name, command
        except (psutil.Error, OSError):
            return fallback_name or "unknown", None
