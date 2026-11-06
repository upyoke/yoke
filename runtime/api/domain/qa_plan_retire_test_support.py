# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from contextlib import contextmanager

from unittest.mock import patch

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import create_smoke_plan

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.qa_plan_management import QaPlanError, _plan_row

from yoke_core.domain.qa_plan_retire import DEPENDENTS_CODE, retire_plan


@contextmanager
def _handler_uses(conn):
    class _Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def close(self):
            return None

    with patch("yoke_core.domain.db_helpers.connect", return_value=_Borrowed()):
        yield
