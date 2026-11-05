# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package

from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)

from yoke_core.domain.migration_serving_version import declared_minimum

ENTRY_NAME = "0017_session_turn_posture"


def _entry():
    directory = history_dir(migration_history_package)
    record = next(
        candidate
        for candidate in ordered_entries(directory)
        if candidate.name == ENTRY_NAME
    )
    return load_migration_module(record.path, record.name)


entry = _entry()
