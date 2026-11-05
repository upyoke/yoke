# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io as io

import sys as sys

from contextlib import (
    redirect_stdout as redirect_stdout,
    redirect_stderr as redirect_stderr,
)

from types import SimpleNamespace as SimpleNamespace

import pytest

from runtime.api.fixtures.dispatch_actor import authorize_every_dispatch

_FIXTURE_ITEM_REF = f"YOK-{42}"


@pytest.fixture(autouse=True)
def _authorize_dispatch():
    """Handlers and item resolution are stubbed; authorization is not under test."""
    with authorize_every_dispatch():
        yield


def _silence_claim(monkeypatch):
    from yoke_core.domain import yok_n_parser
    from yoke_core.domain import yoke_function_dispatch as dispatch_module

    item_ids = {"YOK-1": 1, "YOK-3": 3, "YOK-9": 9, _FIXTURE_ITEM_REF: 42}

    def _resolve_target(request):
        if request.target.public_ref is not None:
            key = item_ids[request.target.public_ref]
            if request.target.kind == "epic_task":
                request.target.epic_id = key
            else:
                request.target.item_id = key
            request.target.project_id = None
        return None

    monkeypatch.setattr(
        dispatch_module,
        "verify_claim",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        dispatch_module,
        "resolve_request_item_refs",
        lambda request, _model: _resolve_target(request),
    )
    monkeypatch.setattr(
        yok_n_parser,
        "parse_item_argument",
        lambda ref, **_kwargs: item_ids[str(ref)],
    )
