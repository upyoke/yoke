# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.api_qa_browser_function_test_support import _request as _request

import unittest

from contextlib import contextmanager

from unittest.mock import patch

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.handlers import qa

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement

from runtime.api.fixtures.dispatch_actor import authorize_every_dispatch

from runtime.api.fixtures.pg_testdb import test_database

from yoke_core.domain.work_claim_targets import make_item_target
