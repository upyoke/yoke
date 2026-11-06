# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import os

from pathlib import Path

from unittest import mock

import pytest

from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.dash_posture_gate import evaluate

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)

from yoke_core.domain.handlers.lifecycle_transition import handle_transition

from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)

POSTURE = {"verification": {"kind": "ad_hoc", "method_id": "browser-inspection"}}


def _insert_dash(conn, *, item_id: int, status: str) -> None:
    insert_item(
        conn,
        id=item_id,
        workflow_id="dash",
        status=status,
        workflow_posture=json.dumps(POSTURE),
    )
