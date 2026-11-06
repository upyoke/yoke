# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import shutil

import subprocess

from types import SimpleNamespace

import pytest

from yoke_harness.baseline_probe_failure_causes import (
    PROBE_EXIT_CODES,
    PROBE_FAILURE_CAUSES,
)

from yoke_harness.ssh_mac_baseline_probes import (
    parse_baseline_probes,
    run_baseline_probes,
)

from yoke_harness.standard_baseline_probes import capture_probes_document


def _claude_probe() -> dict:
    document, _ = capture_probes_document("macos", None)
    probes = parse_baseline_probes(document)
    return next(p for p in probes if p.name == "Claude real request")
