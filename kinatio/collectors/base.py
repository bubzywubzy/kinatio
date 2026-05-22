"""Collector contracts."""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable
from typing import Any

from kinatio.config import AppConfig
from kinatio.domain.models import AvailabilityInfo, LogEntry
from kinatio.execution.subprocess import SafeSubprocessRunner


class Collector(ABC):
    """Base interface for periodic or streaming collectors."""

    name: str
    subsystem: str
    interval: float
    dependencies: tuple[str, ...] = ()
    streaming: bool = False

    def check_availability(self) -> AvailabilityInfo:
        for dependency in self.dependencies:
            if shutil.which(dependency) is None:
                return AvailabilityInfo(
                    available=False,
                    reason=f"Missing dependency: {dependency}",
                    dependency=dependency,
                )
        return AvailabilityInfo(available=True)

    @abstractmethod
    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> Any:
        raise NotImplementedError

    def stream(
        self,
        runner: SafeSubprocessRunner,
        config: AppConfig,
    ) -> AsyncIterator[LogEntry] | Awaitable[AsyncIterator[LogEntry]]:
        raise NotImplementedError(f"{self.name} does not support streaming")
