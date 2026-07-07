"""Shared helpers and fixtures for the sections pytest suites.

Split out of the original ``test_sections.py`` so each authored test file
stays under the 350-line limit. Lives outside the ``test_*.py`` collection
pattern so pytest does not pick it up as a test module. Each split file
imports the fixtures (``db_path``, ``renderer``, ``emitter``, and the
auto-applied ``_reset_injectables``) from this module.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import List, Tuple

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import sections
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_item(db_path: str, item_id: int, title: str = "Test item") -> None:
    conn = connect_test_db(db_path)
    try:
        p = _placeholder(conn)
        conn.execute(
            f"""
            INSERT INTO items (
                id, title, type, status, priority, flow, rework_count, frozen,
                created_at, updated_at, source, project_id, project_sequence
            ) VALUES (
                {p}, {p}, 'issue', 'idea', 'medium', 'accelerated', 0, 0,
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'user', {p}, {p}
            )
            """,
            (item_id, title, SEED_PROJECT_IDS["yoke"], item_id),
        )
        conn.commit()
    finally:
        conn.close()


class _RecordingRenderer:
    """Stub renderer that records invocations and returns a configurable rc."""

    def __init__(self, rc: int = 0) -> None:
        self.calls: List[Tuple[int, str]] = []
        self.rc = rc

    def __call__(self, item_id, *, db_path=None, out=None, err=None):  # type: ignore[no-untyped-def]
        self.calls.append((item_id, db_path or ""))
        return self.rc


class _RecordingEmitter:
    """Stub event emitter that records every call as a dict."""

    def __init__(self) -> None:
        self.calls: List[dict] = []

    def __call__(self, event_name, **kwargs):  # type: ignore[no-untyped-def]
        payload = {"event_name": event_name}
        payload.update(kwargs)
        self.calls.append(payload)
        return payload


def _run_cli(
    fn,  # type: ignore[no-untyped-def]
    args,
    *,
    db_path: str,
) -> Tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    rc = fn(args, db_path=db_path, out=out, err=err)
    return rc, out.getvalue(), err.getvalue()


@pytest.fixture(autouse=True)
def _reset_injectables(monkeypatch):
    """Reset injected renderer/emitter before and after each test."""
    sections.set_renderer(None)
    sections.set_event_emitter(None)
    monkeypatch.setattr(
        sections,
        "sync_body_after_section_mutation",
        lambda item_id, operation: (True, ""),
    )
    yield
    sections.set_renderer(None)
    sections.set_event_emitter(None)


@pytest.fixture
def db_path(tmp_path: Path):
    with init_test_db(tmp_path) as path:
        _seed_item(path, 42)
        yield path


@pytest.fixture
def renderer() -> _RecordingRenderer:
    rec = _RecordingRenderer(rc=0)
    sections.set_renderer(rec)
    return rec


@pytest.fixture
def emitter() -> _RecordingEmitter:
    rec = _RecordingEmitter()
    sections.set_event_emitter(rec)
    return rec
