from types import SimpleNamespace

from pathlib import Path

import pytest

from kinatio.collectors.hardware import HardwareCollector
from kinatio.collectors.processes import ProcessesCollector
from kinatio.collectors.storage import StorageCollector
from kinatio.config import AppConfig
from kinatio.execution.subprocess import CommandResult


class StubRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self.results = results

    async def run(self, command: list[str], **kwargs: object) -> CommandResult:
        del command, kwargs
        return self.results.pop(0)


class FakeProcess:
    def __init__(self, pid: int, *, cpu_user: float, cpu_system: float, name: str = "python") -> None:
        self.info = {
            "pid": pid,
            "name": name,
            "username": "alice",
            "status": "running",
            "cmdline": [name, "worker.py"],
            "memory_info": SimpleNamespace(rss=4096),
            "memory_percent": 1.5,
            "cpu_times": SimpleNamespace(user=cpu_user, system=cpu_system),
        }


@pytest.mark.asyncio
async def test_processes_collector_computes_cpu_from_previous_sample(monkeypatch) -> None:
    collector = ProcessesCollector()
    process = FakeProcess(4242, cpu_user=10.0, cpu_system=1.0)
    sample_times = iter([100.0, 102.0])

    async def immediate_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("kinatio.collectors.processes.asyncio.to_thread", immediate_to_thread)
    monkeypatch.setattr("kinatio.collectors.processes.monotonic", lambda: next(sample_times))
    monkeypatch.setattr("kinatio.collectors.processes.psutil.process_iter", lambda attrs=None: [process])

    first_state = await collector.collect(StubRunner([]), AppConfig(max_process_entries=10))

    process.info["cpu_times"] = SimpleNamespace(user=11.0, system=1.0)
    second_state = await collector.collect(StubRunner([]), AppConfig(max_process_entries=10))

    assert first_state.entries[0].cpu_percent == 0.0
    assert second_state.entries[0].cpu_percent == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_hardware_collector_reads_cpu_metadata_and_averages_per_core(monkeypatch) -> None:
    collector = HardwareCollector()

    async def immediate_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("kinatio.collectors.hardware.asyncio.to_thread", immediate_to_thread)
    monkeypatch.setattr("kinatio.collectors.hardware.platform.machine", lambda: "x86_64")
    monkeypatch.setattr("kinatio.collectors.hardware.psutil.cpu_freq", lambda: SimpleNamespace(current=2450.0, max=4800.0))
    monkeypatch.setattr(
        "kinatio.collectors.hardware.psutil.cpu_percent",
        lambda interval=0.0, percpu=False: [20.0, 40.0] if percpu else 30.0,
    )
    monkeypatch.setattr("kinatio.collectors.hardware.psutil.cpu_count", lambda logical=True: 16 if logical else 8)
    monkeypatch.setattr(
        "kinatio.collectors.hardware.psutil.virtual_memory",
        lambda: SimpleNamespace(total=16 * 1024**3, available=8 * 1024**3, used=8 * 1024**3, percent=50.0),
    )
    monkeypatch.setattr(
        "kinatio.collectors.hardware.psutil.swap_memory",
        lambda: SimpleNamespace(total=4 * 1024**3, used=1 * 1024**3, percent=25.0),
    )
    monkeypatch.setattr(collector, "_read_cpu_model_name", lambda: "Unit Test CPU")

    runner = StubRunner(
        [
            CommandResult(command=["lspci"], stdout="0000:01:00.0 VGA controller\n", stderr="", returncode=0),
            CommandResult(command=["lsusb"], stdout="Bus 001 Device 002 USB hub\n", stderr="", returncode=0),
            CommandResult(
                command=["nvidia-smi"],
                stdout="",
                stderr="Missing dependency: nvidia-smi",
                returncode=127,
                missing_dependency=True,
            ),
        ]
    )

    state = await collector.collect(runner, AppConfig())

    assert state.cpu.model_name == "Unit Test CPU"
    assert state.cpu.architecture == "x86_64"
    assert state.cpu.frequency_current_mhz == 2450.0
    assert state.cpu.frequency_max_mhz == 4800.0
    assert state.cpu.load_percent == pytest.approx(30.0)
    assert [core.percent for core in state.cpu.per_core] == [20.0, 40.0]


@pytest.mark.asyncio
async def test_hardware_collector_enriches_gpu_inventory_from_nvidia_smi(monkeypatch) -> None:
    collector = HardwareCollector()

    async def immediate_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("kinatio.collectors.hardware.asyncio.to_thread", immediate_to_thread)
    monkeypatch.setattr("kinatio.collectors.hardware.platform.machine", lambda: "x86_64")
    monkeypatch.setattr("kinatio.collectors.hardware.psutil.cpu_freq", lambda: None)
    monkeypatch.setattr("kinatio.collectors.hardware.psutil.cpu_percent", lambda interval=0.0, percpu=False: [12.0, 18.0])
    monkeypatch.setattr("kinatio.collectors.hardware.psutil.cpu_count", lambda logical=True: 8 if logical else 4)
    monkeypatch.setattr(
        "kinatio.collectors.hardware.psutil.virtual_memory",
        lambda: SimpleNamespace(total=8 * 1024**3, available=4 * 1024**3, used=4 * 1024**3, percent=50.0),
    )
    monkeypatch.setattr(
        "kinatio.collectors.hardware.psutil.swap_memory",
        lambda: SimpleNamespace(total=2 * 1024**3, used=0, percent=0.0),
    )
    monkeypatch.setattr(collector, "_read_cpu_model_name", lambda: "Unit Test CPU")
    monkeypatch.setattr(collector, "_collect_drm_gpu_telemetry", lambda: [])
    monkeypatch.setattr(
        "kinatio.collectors.hardware.psutil.Process",
        lambda pid: SimpleNamespace(name=lambda: "python", cmdline=lambda: ["python", "train.py", "--epochs", "3"]),
    )

    runner = StubRunner(
        [
            CommandResult(
                command=["lspci"],
                stdout="0000:01:00.0 VGA compatible controller: NVIDIA Corporation GA104 [GeForce RTX 3070]\n",
                stderr="",
                returncode=0,
            ),
            CommandResult(command=["lsusb"], stdout="", stderr="", returncode=0),
            CommandResult(
                command=["nvidia-smi"],
                stdout="NVIDIA GeForce RTX 3070, 0000:01:00.0, 550.54, 8192, 2048, 35, 61\n",
                stderr="",
                returncode=0,
            ),
            CommandResult(
                command=["nvidia-smi"],
                stdout="0000:01:00.0, 4242, python, 1024\n",
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await collector.collect(runner, AppConfig())

    assert len(state.gpus) == 1
    assert state.gpus[0].vendor == "NVIDIA"
    assert state.gpus[0].driver == "550.54"
    assert state.gpus[0].memory_total_bytes == 8192 * 1024 * 1024
    assert state.gpus[0].memory_used_bytes == 2048 * 1024 * 1024
    assert state.gpus[0].utilization_percent == pytest.approx(35.0)
    assert state.gpus[0].temperature_celsius == pytest.approx(61.0)
    assert state.gpus[0].workload_source == "nvidia-smi"
    assert len(state.gpus[0].workloads) == 1
    assert state.gpus[0].workloads[0].pid == 4242
    assert state.gpus[0].workloads[0].process_name == "python"
    assert state.gpus[0].workloads[0].command == "python train.py --epochs 3"
    assert state.gpus[0].workloads[0].gpu_memory_bytes == 1024 * 1024 * 1024


@pytest.mark.asyncio
async def test_hardware_collector_uses_drm_gpu_fallback_when_vendor_tools_are_missing(monkeypatch, tmp_path: Path) -> None:
    collector = HardwareCollector()

    async def immediate_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("kinatio.collectors.hardware.asyncio.to_thread", immediate_to_thread)
    monkeypatch.setattr("kinatio.collectors.hardware.platform.machine", lambda: "x86_64")
    monkeypatch.setattr("kinatio.collectors.hardware.psutil.cpu_freq", lambda: None)
    monkeypatch.setattr("kinatio.collectors.hardware.psutil.cpu_percent", lambda interval=0.0, percpu=False: [5.0, 10.0])
    monkeypatch.setattr("kinatio.collectors.hardware.psutil.cpu_count", lambda logical=True: 8 if logical else 4)
    monkeypatch.setattr(
        "kinatio.collectors.hardware.psutil.virtual_memory",
        lambda: SimpleNamespace(total=8 * 1024**3, available=4 * 1024**3, used=4 * 1024**3, percent=50.0),
    )
    monkeypatch.setattr(
        "kinatio.collectors.hardware.psutil.swap_memory",
        lambda: SimpleNamespace(total=2 * 1024**3, used=0, percent=0.0),
    )
    monkeypatch.setattr(collector, "_read_cpu_model_name", lambda: "Unit Test CPU")

    collector._drm_root = tmp_path / "drm"
    card_root = collector._drm_root / "card0"
    device_root = card_root / "device"
    hwmon_root = device_root / "hwmon" / "hwmon0"
    hwmon_root.mkdir(parents=True)
    (device_root / "vendor").write_text("0x1002\n", encoding="utf-8")
    (device_root / "uevent").write_text("PCI_SLOT_NAME=0000:03:00.0\n", encoding="utf-8")
    (device_root / "mem_info_vram_total").write_text(str(6 * 1024**3), encoding="utf-8")
    (device_root / "mem_info_vram_used").write_text(str(2 * 1024**3), encoding="utf-8")
    (device_root / "gpu_busy_percent").write_text("41\n", encoding="utf-8")
    (hwmon_root / "temp1_input").write_text("57000\n", encoding="utf-8")
    driver_target = tmp_path / "drivers" / "amdgpu"
    driver_target.mkdir(parents=True)
    (device_root / "driver").symlink_to(driver_target)

    runner = StubRunner(
        [
            CommandResult(
                command=["lspci"],
                stdout="0000:03:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Navi 22\n",
                stderr="",
                returncode=0,
            ),
            CommandResult(command=["lsusb"], stdout="", stderr="", returncode=0),
            CommandResult(
                command=["nvidia-smi"],
                stdout="",
                stderr="Missing dependency: nvidia-smi",
                returncode=127,
                missing_dependency=True,
            ),
        ]
    )

    state = await collector.collect(runner, AppConfig())

    assert len(state.gpus) == 1
    assert state.gpus[0].vendor == "AMD"
    assert state.gpus[0].driver == "amdgpu"
    assert state.gpus[0].memory_total_bytes == 6 * 1024**3
    assert state.gpus[0].memory_used_bytes == 2 * 1024**3
    assert state.gpus[0].utilization_percent == pytest.approx(41.0)
    assert state.gpus[0].temperature_celsius == pytest.approx(57.0)


@pytest.mark.asyncio
async def test_hardware_collector_deduplicates_one_gpu_across_pci_drm_and_nvidia_formats(monkeypatch, tmp_path: Path) -> None:
    collector = HardwareCollector()

    async def immediate_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("kinatio.collectors.hardware.asyncio.to_thread", immediate_to_thread)
    monkeypatch.setattr("kinatio.collectors.hardware.platform.machine", lambda: "x86_64")
    monkeypatch.setattr("kinatio.collectors.hardware.psutil.cpu_freq", lambda: None)
    monkeypatch.setattr("kinatio.collectors.hardware.psutil.cpu_percent", lambda interval=0.0, percpu=False: [5.0, 10.0])
    monkeypatch.setattr("kinatio.collectors.hardware.psutil.cpu_count", lambda logical=True: 8 if logical else 4)
    monkeypatch.setattr(
        "kinatio.collectors.hardware.psutil.virtual_memory",
        lambda: SimpleNamespace(total=8 * 1024**3, available=4 * 1024**3, used=4 * 1024**3, percent=50.0),
    )
    monkeypatch.setattr(
        "kinatio.collectors.hardware.psutil.swap_memory",
        lambda: SimpleNamespace(total=2 * 1024**3, used=0, percent=0.0),
    )
    monkeypatch.setattr(collector, "_read_cpu_model_name", lambda: "Unit Test CPU")
    monkeypatch.setattr(
        "kinatio.collectors.hardware.psutil.Process",
        lambda pid: SimpleNamespace(name=lambda: "python", cmdline=lambda: ["python", "render.py"]),
    )

    collector._drm_root = tmp_path / "drm"
    card_root = collector._drm_root / "card1"
    connector_root = collector._drm_root / "card1-DP-1"
    connector_root.mkdir(parents=True)
    device_root = card_root / "device"
    hwmon_root = device_root / "hwmon" / "hwmon0"
    hwmon_root.mkdir(parents=True)
    (device_root / "vendor").write_text("0x10de\n", encoding="utf-8")
    (device_root / "uevent").write_text("PCI_SLOT_NAME=0000:2B:00.0\n", encoding="utf-8")
    (hwmon_root / "temp1_input").write_text("38000\n", encoding="utf-8")
    driver_target = tmp_path / "drivers" / "nvidia"
    driver_target.mkdir(parents=True)
    (device_root / "driver").symlink_to(driver_target)

    runner = StubRunner(
        [
            CommandResult(
                command=["lspci"],
                stdout="2b:00.0 VGA compatible controller: NVIDIA Corporation TU116 [GeForce GTX 1660 SUPER] (rev a1)\n",
                stderr="",
                returncode=0,
            ),
            CommandResult(command=["lsusb"], stdout="", stderr="", returncode=0),
            CommandResult(
                command=["nvidia-smi"],
                stdout="NVIDIA GeForce GTX 1660 SUPER, 00000000:2B:00.0, 595.71.05, 6144, 1255, 6, 38\n",
                stderr="",
                returncode=0,
            ),
            CommandResult(
                command=["nvidia-smi"],
                stdout="00000000:2B:00.0, 4242, python, 512\n",
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await collector.collect(runner, AppConfig())

    assert len(state.gpus) == 1
    assert state.gpus[0].name == "NVIDIA GeForce GTX 1660 SUPER"
    assert state.gpus[0].vendor == "NVIDIA"
    assert state.gpus[0].bus_id == "0000:2b:00.0"
    assert state.gpus[0].driver == "595.71.05"
    assert state.gpus[0].temperature_celsius == pytest.approx(38.0)
    assert state.gpus[0].workload_source == "nvidia-smi"
    assert len(state.gpus[0].workloads) == 1
    assert state.gpus[0].workloads[0].command == "python render.py"


@pytest.mark.asyncio
async def test_storage_collector_extracts_disk_temperature_from_smart(monkeypatch) -> None:
    collector = StorageCollector()
    monkeypatch.setattr(collector, "_collect_mounts", lambda: [])
    monkeypatch.setattr(collector, "_collect_io", lambda: {})

    runner = StubRunner(
        [
            CommandResult(
                command=["lsblk"],
                stdout='{"blockdevices": [{"name": "nvme0n1", "model": "Fast Disk", "serial": "XYZ", "size": 1024, "tran": "nvme"}]}',
                stderr="",
                returncode=0,
            ),
            CommandResult(
                command=["smartctl"],
                stdout='{"smart_status": {"passed": true}, "nvme_smart_health_information_log": {"temperature": 46}}',
                stderr="",
                returncode=0,
            ),
        ]
    )

    state = await collector.collect(runner, AppConfig())

    assert len(state.disks) == 1
    assert state.disks[0].smart_health == "passed"
    assert state.disks[0].temperature_celsius == pytest.approx(46.0)
