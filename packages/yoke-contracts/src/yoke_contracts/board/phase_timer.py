"""Tiny phase timing helper for board rebuild diagnostics."""

from __future__ import annotations

import time
from contextlib import contextmanager, nullcontext
from typing import Iterator


class PhaseRecorder:
    """Accumulate named wall-clock phase timings in milliseconds."""

    def __init__(self) -> None:
        self._phases: dict[str, int] = {}

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.add(name, int((time.perf_counter() - start) * 1000))

    def add(self, name: str, elapsed_ms: int) -> None:
        self._phases[name] = self._phases.get(name, 0) + max(0, int(elapsed_ms))

    def snapshot(self) -> dict[str, int]:
        return dict(self._phases)


def measure_phase(recorder: PhaseRecorder | None, name: str):
    if recorder is None:
        return nullcontext()
    return recorder.measure(name)


__all__ = ["PhaseRecorder", "measure_phase"]
