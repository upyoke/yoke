# ruff: noqa: E402, F401, F811
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import os

from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _item_field,
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported pytest fixture
)

from runtime.api.qa_catalog_test_support import CATALOG_CASES

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.handlers.items_create import handle_item_create

from yoke_core.domain.item_entry_surface import (
    ITEM_ENTRY_SURFACE_ENV,
    MISSING_ENTRY_SURFACE_MESSAGE,
)

_FUNCTION_ID = "items.create"


def _request(payload, *, session_id="items-create-test", actor_id=None):
    return FunctionCallRequest(
        function=_FUNCTION_ID,
        actor=ActorContext(session_id=session_id, actor_id=actor_id),
        target=TargetRef(kind="global"),
        payload={"project": "yoke", **payload},
    )
