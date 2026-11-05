# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

from yoke_core.domain.actors import seed_human_actor

from yoke_core.domain.deployment_qa_source_obligation import latest_completion_run

from yoke_core.domain.gate_satisfier_facts import FactVerdict

from yoke_core.domain.gate_satisfier_item_facts import (
    ITEM_DEPLOYMENT_RUN_SUCCEEDED,
    load_item_facts,
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path
