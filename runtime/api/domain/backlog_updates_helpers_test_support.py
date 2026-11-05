# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from yoke_core.domain.backlog_updates_helpers import (
    _profile_declares_mutation,
    _run_db_mutation_gate,
)

from yoke_core.domain.schema_init_apply import execute_schema_script

from runtime.api.fixtures import pg_testdb

from runtime.api.fixtures.backlog import (
    insert_item,
)

_EXTRA_DDL = """
CREATE TABLE IF NOT EXISTS project_capabilities (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    type TEXT NOT NULL,

    settings TEXT DEFAULT '{}',
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE(project_id, type)
);

CREATE TABLE IF NOT EXISTS migration_audit (
    id INTEGER PRIMARY KEY,
    migration_name TEXT NOT NULL,
    status TEXT,
    state TEXT,
    model_name TEXT,
    project_id INTEGER
);
"""
