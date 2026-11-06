# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yoke_core.domain import epic

from runtime.api.conftest import insert_epic_task, insert_item

from yoke_contracts.title_policy import title_max_length

TEST_ITEM_ID = 42

TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


@pytest.fixture
def db(test_db):
    """Full Yoke schema on the disposable Postgres authority fixture."""
    return test_db


@pytest.fixture
def db_with_task(db):
    """DB with one epic task already inserted."""
    insert_item(
        db,
        id=TEST_ITEM_ID,
        workflow_id="epic",
        status="planned",
    )
    insert_epic_task(
        db, epic_id=TEST_ITEM_ID, task_num=1, title="First task", status="planning"
    )
    return db
