# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import importlib

import json

import pytest

from runtime.api.fixtures.native_instant_database import BORN_NATIVE_AFTER_HISTORY

from yoke_contracts.schema_authority import SchemaAuthorityRefused

from yoke_contracts.timestamps import format_instant

from yoke_core.domain.migrations import _native_instant_documents as documents

from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS

history = importlib.import_module(
    "yoke_core.domain.migrations.0070_native_domain_instants"
)

STAMP = "2026-10-08T16:30:00.123456Z"
