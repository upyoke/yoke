# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.yoke_function_actor_identity_dispatch_test_support import _ok_handler as _ok_handler

import tempfile

import unittest

from contextlib import ExitStack

from pathlib import Path

from unittest.mock import patch

from fastapi.testclient import TestClient

from pydantic import BaseModel

from runtime.api.auth_test_helpers import mint_api_auth_context

from yoke_core.domain import yoke_function_dispatch as dispatch_module

from yoke_core.domain import yoke_function_dispatch_events as events_module

from yoke_core.domain.api_tokens import (
    TOKEN_PREFIX as TOKEN_PREFIX,
    mint_token as mint_token,
    revoke_token as revoke_token,
)

from yoke_contracts.api.function_call import (
    FunctionWarning,
    HandlerOutcome,
)

from yoke_core.domain.yoke_function_registry import (
    register as register,
    reset_registry_for_tests,
)

from runtime.api.fixtures.file_test_db import (
    connect_test_db as connect_test_db,
    init_test_db as init_test_db,
)

from yoke_core.api.main import app

from runtime.api.api_helpers_test_support import _install_overrides

_FIXTURE_ITEM_REF = f"YOK-{42}"


class _Req(BaseModel):
    pass


class _Resp(BaseModel):
    pass


def _stable_kwargs(**overrides):
    base = {
        "stability": "stable",
        "owner_module": "yoke_core.domain.test_module",
        "target_kinds": ["item"],
        "side_effects": [],
        "emitted_event_names": ["FakeEvent"],
        "guardrails": [],
        "adapter_status": "live",
    }
    base.update(overrides)
    return base


def _envelope(function_id: str, **overrides):
    base = {
        "function": function_id,
        "version": "v1",
        "actor": {"actor_id": "op", "session_id": "s-1"},
        "target": {
            "kind": "item",
            "public_ref": _FIXTURE_ITEM_REF,
            "project_id": "yoke",
        },  # resolvable target
        "payload": {},
        "preconditions": {},
        "options": {},
    }
    base.update(overrides)
    return base


def _actor_echo_handler(request):
    return HandlerOutcome(
        result_payload={"actor_id": request.actor.actor_id},
        primary_success=True,
    )


class _ApiSuite(unittest.TestCase):
    def setUp(self) -> None:
        self._stack = ExitStack()
        self._tmp_dir = self._stack.enter_context(tempfile.TemporaryDirectory())
        self._db_path = self._stack.enter_context(
            init_test_db(
                Path(self._tmp_dir),
            )
        )
        self._stack.enter_context(_install_overrides(self._db_path))
        conn = connect_test_db(self._db_path)
        try:
            self._auth = mint_api_auth_context(conn)
        finally:
            conn.close()
        from runtime.api.domain.sections_test_helpers import _seed_item

        _seed_item(self._db_path, 42)
        reset_registry_for_tests()
        # Silence event emission so the API endpoint does not require the
        # full events table during integration tests.
        self._event_patch = patch.object(events_module, "emit_event")
        self._event_patch.start()
        # Suppress the idempotency-ledger lookup so a stale
        # `function_call_ledger` row never replays unrelated request_ids
        # in integration tests.
        self._idem_patch = patch.object(
            dispatch_module,
            "_idempotency_lookup",
            return_value=None,
        )
        self._idem_patch.start()
        # Reuse the package-level app singleton; the test registers its
        # own ids in the cleared registry. Skip lifespan because it would
        # call register_all_handlers() against the already-cleared registry.
        self._client = TestClient(app)

    def tearDown(self) -> None:
        self._client.close()
        self._event_patch.stop()
        self._idem_patch.stop()
        reset_registry_for_tests()
        self._stack.close()

    @property
    def _headers(self) -> dict[str, str]:
        return self._auth.headers
