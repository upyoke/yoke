# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import importlib

import io

import signal

import tempfile

import time

import unittest

from contextlib import redirect_stdout

from pathlib import Path

from typing import Callable, List

from unittest import mock

from yoke_core.tools import api_server

import pytest

pytestmark = pytest.mark.usefixtures("bound_project_context")

DISPATCHER_OVERHEAD_BUDGET_MS = 50.0

DISPATCHER_OVERHEAD_SAMPLES = 100

DISPATCHER_OVERHEAD_WARMUP = 10


def _dispatcher_available() -> bool:
    try:
        importlib.import_module("yoke_core.domain.yoke_function_dispatch")
        importlib.import_module("yoke_core.domain.yoke_function_registry")
        importlib.import_module("yoke_contracts.api.function_call")
    except Exception:
        return False
    return True


def _structured_field_handler_registered() -> bool:
    if not _dispatcher_available():
        return False
    try:
        from yoke_core.domain.handlers import (
            __init_register__ as _init_register,
        )
        from yoke_core.domain.yoke_function_registry import lookup
    except Exception:
        return False
    try:
        _init_register.register_all_handlers()
    except Exception:
        pass  # Already registered — lookup tells us either way.
    return lookup("items.structured_field.replace") is not None


def _percentile_ms(samples: List[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    idx = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * len(ordered) - 1))))
    return ordered[idx]


def _measure_ms(call: Callable[[], object], iterations: int) -> List[float]:
    samples: List[float] = []
    for _ in range(iterations):
        t0 = time.process_time()
        call()
        samples.append((time.process_time() - t0) * 1000.0)
    return samples


class _FakeProc:
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
