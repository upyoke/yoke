# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import os

from unittest import mock

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_contracts.board.art import ArtConfig

from yoke_contracts.board.config import BoardConfig

from yoke_core.board.renderer import render_board_from_payload

from yoke_core.domain import events as events_module

from yoke_core.domain import yoke_function_dispatch as dispatch_module

from yoke_core.domain.handlers import orchestration

from yoke_core.domain.handlers.__init_register__ import register_all_handlers

from yoke_core.domain.actor_project_visibility import actor_project_ids_with_permission

from yoke_core.domain.actor_permissions import PERM_ITEMS_READ

from yoke_core.domain.actors import seed_human_actor

from yoke_core.domain.api_tokens import mint_token

from yoke_core.domain.yoke_function_registry import reset_registry_for_tests

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.file_test_db import connect_test_db


def _request(payload: dict, *, options: dict | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="board.data.get",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload=payload,
        options=options or {},
    )
