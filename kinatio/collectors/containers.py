"""Collector for container runtime inventory."""

from __future__ import annotations

import shutil

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import AvailabilityInfo, ContainerEntry, ContainersState, utc_now
from kinatio.execution.subprocess import SafeSubprocessRunner


class ContainersCollector(Collector):
    name = "containers"
    subsystem = "containers"
    interval = 20.0

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> ContainersState:
        runtime = self._detect_runtime(config.container_runtime_precedence)
        if runtime is None:
            return ContainersState(
                refreshed_at=utc_now(),
                availability=AvailabilityInfo(available=False, reason="No supported container runtime was detected."),
            )

        ps_command, images_command = self._runtime_commands(runtime)
        ps_result = await runner.run(ps_command, timeout=10.0, allow_missing=True)
        if ps_result.missing_dependency:
            return ContainersState(
                refreshed_at=utc_now(),
                runtime=runtime,
                availability=AvailabilityInfo(available=False, reason=f"{runtime} is not available on this host."),
            )
        if ps_result.returncode != 0:
            return ContainersState(
                refreshed_at=utc_now(),
                runtime=runtime,
                availability=AvailabilityInfo(
                    available=False,
                    reason=(ps_result.stderr or ps_result.stdout or f"{runtime} inventory failed").strip()[:200],
                ),
            )

        containers: list[ContainerEntry] = []
        running_count = 0
        total_count = 0
        for line in ps_result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split("\t")
            if len(parts) < 5:
                continue
            total_count += 1
            state = parts[3].strip().lower()
            if state == "running":
                running_count += 1
            if len(containers) < config.max_container_entries:
                containers.append(
                    ContainerEntry(
                        container_id=parts[0],
                        name=parts[1],
                        image=parts[2],
                        state=parts[3],
                        status=parts[4],
                        ports=parts[5].strip() if len(parts) > 5 and parts[5].strip() else None,
                    )
                )

        image_result = await runner.run(images_command, timeout=10.0, allow_missing=True)
        image_count = 0
        if not image_result.missing_dependency and image_result.returncode == 0:
            image_count = sum(1 for line in image_result.stdout.splitlines() if line.strip())

        return ContainersState(
            refreshed_at=utc_now(),
            runtime=runtime,
            running_count=running_count,
            total_count=total_count,
            image_count=image_count,
            containers=containers,
        )

    def _detect_runtime(self, precedence: list[str]) -> str | None:
        for runtime in precedence:
            if shutil.which(runtime):
                return runtime
        return None

    def _runtime_commands(self, runtime: str) -> tuple[list[str], list[str]]:
        return (
            [runtime, "ps", "-a", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Status}}\t{{.Ports}}"],
            [runtime, "images", "--format", "{{.Repository}}:{{.Tag}}"],
        )