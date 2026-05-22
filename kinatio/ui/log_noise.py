"""Helpers for classifying known noisy log entries."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from kinatio.config import DEFAULT_CONFIG
from kinatio.domain.models import LogEntry

DEFAULT_LOG_NOISE_PATTERNS = tuple(DEFAULT_CONFIG.log_noise_patterns)


@dataclass(slots=True, frozen=True)
class FilteredLogEntries:
    """Visible log entries plus the count of suppressed noisy entries."""

    visible_entries: list[LogEntry]
    suppressed_count: int = 0


@lru_cache(maxsize=32)
def _compile_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


def log_entry_is_known_noise(entry: LogEntry, patterns: Sequence[str] | None = None) -> bool:
    """Return whether the entry matches a known non-actionable environment warning."""

    haystack = " ".join(
        part
        for part in [entry.source, entry.unit or "", entry.priority or "", entry.message]
        if part
    )
    compiled_patterns = _compile_patterns(tuple(patterns or DEFAULT_LOG_NOISE_PATTERNS))
    return any(pattern.search(haystack) for pattern in compiled_patterns)


def filter_known_log_noise(
    entries: Sequence[LogEntry],
    *,
    show_known_noise: bool,
    patterns: Sequence[str] | None = None,
) -> FilteredLogEntries:
    """Return entries visible in the current view and how many noisy lines were hidden."""

    visible_entries = list(entries)
    if show_known_noise:
        return FilteredLogEntries(visible_entries=visible_entries)

    filtered_entries: list[LogEntry] = []
    suppressed_count = 0
    for entry in visible_entries:
        if log_entry_is_known_noise(entry, patterns):
            suppressed_count += 1
            continue
        filtered_entries.append(entry)
    return FilteredLogEntries(visible_entries=filtered_entries, suppressed_count=suppressed_count)
