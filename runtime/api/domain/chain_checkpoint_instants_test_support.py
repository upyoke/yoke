# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from uuid import uuid4

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_contracts.timestamps import (
    InvalidInstant,
    format_instant,
    parse_instant,
    temporal_wire,
)

from yoke_core.domain.actors import seed_human_actor

from yoke_core.domain import sessions_queries_chain as chain

from yoke_core.domain import sessions_render_reclaim as reclaim

from yoke_core.domain.sessions import claim_work

MOMENT = parse_instant("2026-11-01T05:29:59.123456+05:45")


def _session(conn, *, envelope=None):
    session = str(uuid4())
    actor = seed_human_actor(conn)
    conn.execute(
        "INSERT INTO harness_sessions (session_id,executor,provider,model,reasoning_effort,workspace,"
        "actor_id,project_id,offered_at,last_heartbeat,offer_envelope) "
        "VALUES (%s,'codex','openai','gpt-6.1-sol','medium','/tmp',%s,1,%s,%s,%s)",
        (
            session,
            actor,
            MOMENT,
            MOMENT,
            json.dumps(envelope) if envelope is not None else None,
        ),
    )
    return session
