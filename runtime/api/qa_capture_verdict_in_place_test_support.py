# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import unittest

from unittest.mock import patch

from yoke_core.domain.handlers import qa_run

from yoke_core.domain.qa_merging_identity import recorded_head_sha

from runtime.api.fixtures.pg_testdb import test_database

from runtime.api.qa_agent_reviewed_capture_test_support import (
    browser_evidence_gate as _gate,
    capture as _capture,
    request as _request,
    seed_case as _seed_case,
)


def _record_agent_verdict(conn, requirement_id: int, payload: dict):
    """Drive the real handler, which resolves its own connection.

    ``test_database`` repoints the DSN at this same database, so the handler
    opening and closing its own connection is the production shape rather
    than a patched stand-in.
    """
    conn.commit()
    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        return qa_run.handle_qa_run_record_verdict(
            _request("qa.run.record_verdict", requirement_id, payload)
        )
