"""Collector for battery, thermal, fan, and CPU governor telemetry."""

from __future__ import annotations

from pathlib import Path

import psutil

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import AvailabilityInfo, FanSensor, PowerState, ThermalSensor, utc_now
from kinatio.execution.subprocess import SafeSubprocessRunner


class PowerCollector(Collector):
    name = "power"
    subsystem = "power"
    interval = 12.0

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> PowerState:
        del runner, config
        battery = self._collect_battery()
        thermal_sensors = self._collect_thermal_sensors()
        fan_sensors = self._collect_fan_sensors()
        cpu_governors = self._collect_cpu_governors()
        available = bool(battery["battery_present"] or thermal_sensors or fan_sensors or cpu_governors)
        reason = None if available else "No battery, thermal, fan, or CPU governor telemetry was detected on this host."
        return PowerState(
            refreshed_at=utc_now(),
            battery_present=battery["battery_present"],
            battery_percent=battery["battery_percent"],
            power_plugged=battery["power_plugged"],
            seconds_left=battery["seconds_left"],
            thermal_sensors=thermal_sensors,
            fan_sensors=fan_sensors,
            cpu_governors=cpu_governors,
            availability=AvailabilityInfo(available=available, reason=reason),
        )

    def _collect_battery(self) -> dict[str, bool | float | int | None]:
        try:
            battery = psutil.sensors_battery()
        except (AttributeError, NotImplementedError):
            battery = None
        if battery is None:
            return {
                "battery_present": False,
                "battery_percent": None,
                "power_plugged": None,
                "seconds_left": None,
            }
        seconds_left = battery.secsleft
        if seconds_left in {getattr(psutil, "POWER_TIME_UNKNOWN", -1), getattr(psutil, "POWER_TIME_UNLIMITED", -2)}:
            seconds_left = None
        return {
            "battery_present": True,
            "battery_percent": battery.percent,
            "power_plugged": battery.power_plugged,
            "seconds_left": seconds_left,
        }

    def _collect_thermal_sensors(self) -> list[ThermalSensor]:
        try:
            readings = psutil.sensors_temperatures(fahrenheit=False) or {}
        except (AttributeError, NotImplementedError):
            readings = {}
        sensors: list[ThermalSensor] = []
        for source, entries in readings.items():
            for entry in entries:
                sensors.append(
                    ThermalSensor(
                        source=source,
                        label=entry.label or source,
                        current_celsius=entry.current,
                        high_celsius=entry.high,
                        critical_celsius=entry.critical,
                    )
                )
        sensors.sort(key=lambda sensor: (sensor.source, sensor.label))
        return sensors

    def _collect_fan_sensors(self) -> list[FanSensor]:
        try:
            readings = psutil.sensors_fans() or {}
        except (AttributeError, NotImplementedError):
            readings = {}
        sensors: list[FanSensor] = []
        for source, entries in readings.items():
            for entry in entries:
                sensors.append(
                    FanSensor(
                        source=source,
                        label=entry.label or source,
                        rpm=entry.current,
                    )
                )
        sensors.sort(key=lambda sensor: (sensor.source, sensor.label))
        return sensors

    def _collect_cpu_governors(self) -> dict[str, int]:
        governors: dict[str, int] = {}
        cpu_root = Path("/sys/devices/system/cpu")
        for governor_path in sorted(cpu_root.glob("cpu[0-9]*/cpufreq/scaling_governor")):
            try:
                governor = governor_path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if not governor:
                continue
            governors[governor] = governors.get(governor, 0) + 1
        return governors