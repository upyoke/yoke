# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from datetime import datetime

from importlib import import_module

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant

WIRE = "2026-10-09T15:00:00.123456Z"

INSTANT = parse_instant(WIRE)

BAD_CLOCKS = ("", 123, "2026-10-09", datetime(2026, 10, 9), "2026-10-09T15:00:00-00:00")


class UntouchedConnection:
    def execute(self, *args, **kwargs):
        raise AssertionError("invalid clock reached SQL")


def unused_clock():
    raise AssertionError("a supplied clock evaluated the default")
