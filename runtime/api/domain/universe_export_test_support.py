# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import contextlib

import os

import re

import subprocess

import tarfile

from types import SimpleNamespace

from datetime import datetime, timezone

from pathlib import Path

import pytest

from yoke_contracts.machine_config import runtime as machine_runtime

from yoke_contracts.timestamps import parse_instant, format_instant

from yoke_core.domain import universe_archive

from yoke_core.domain import universe_export as ux

from yoke_core.domain import universe_snapshot_archive as snapshots

from yoke_core.domain.source_freeze_intent import file_sha256


@contextlib.contextmanager
def _schema_loaded_universe():
    """Yield ``(conn, dsn)`` for a fresh schema-loaded disposable database.

    The fixture schema seeds the default org identity card, so the
    database looks like a bootstrapped universe to the export probe.
    """
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import db_backend

    with pg_testdb.test_database() as conn:
        yield conn, os.environ[db_backend.PG_DSN_ENV]
