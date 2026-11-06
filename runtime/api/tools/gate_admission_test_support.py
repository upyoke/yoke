# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import sys

import threading

import time

import uuid

import psycopg

import pytest

from yoke_core.domain import qa_gate_timeout

from yoke_core.tools import gate_admission


def _scratch_lock_base() -> int:
    # Distinct per test so slot scenarios never collide with live gate
    # slots (or each other) on the shared cluster's global lock space.
    return int(uuid.uuid4().int % 1_000_000) + 0x7A000000
