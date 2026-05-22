"""JSON-backed state cache."""

from __future__ import annotations

import json
import os
import tempfile
from json import JSONDecodeError
from pathlib import Path
from time import time_ns

from pydantic import ValidationError

from kinatio.domain.models import SystemState


class JSONStateCache:
    """Persist normalized snapshots for restore."""

    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path

    def load(self) -> SystemState | None:
        if not self.cache_path.exists():
            return None
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return SystemState.model_validate(data)
        except (JSONDecodeError, ValidationError, OSError):
            self._quarantine_corrupt_cache()
            return None

    def save(self, state: SystemState) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = state.model_dump_json(indent=2)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.cache_path.parent,
                prefix=f".{self.cache_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            temp_path.chmod(0o600)
            temp_path.replace(self.cache_path)
            self.cache_path.chmod(0o600)
        except OSError:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _quarantine_corrupt_cache(self) -> None:
        if not self.cache_path.exists():
            return
        corrupt_path = self.cache_path.with_name(f"{self.cache_path.name}.corrupt.{time_ns()}")
        try:
            self.cache_path.replace(corrupt_path)
        except OSError:
            pass
