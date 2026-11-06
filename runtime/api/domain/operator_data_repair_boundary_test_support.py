# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from unittest.mock import MagicMock, patch

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.handlers.operator_data_repair import handle_repair

from yoke_core.domain.operator_data_repair import (
    RepairPlan,
    review_digest,
    validate_plan,
)

from yoke_core.domain.operator_data_repair_sql import RepairRefusal, validate_sql


class _Unclosed:
    """Keep the shared test connection open across the handler's close()."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        pass
