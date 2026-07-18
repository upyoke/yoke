"""Shared seeds and request builders for the strategy handler tests.

Consumed by ``test_strategy_docs.py`` (reads + the replace claim gate),
``test_strategy_docs_guards_render.py`` (replace guard codes, render,
registration shape), ``test_strategy_docs_ingest.py``, and
``test_strategy_docs_seed.py`` so each test module stays under the
authored-file line cap without duplicating fixture plumbing. Project 1
("yoke" in the schema seed) is the default corpus; project 2 carries
a same-slug row for isolation coverage.
"""

from __future__ import annotations

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.events import EmitResult
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.work_processes import PROCESS_STRATEGIZE, conflict_group_for


SESSION_WITH_CLAIM = "session-strategy-claim"
SESSION_WITHOUT_CLAIM = "session-no-claim"

SEED_UPDATED_AT = "2026-06-10T00:00:00Z"

SEED_SLUGS = ("MISSION", "VISION", "MASTER-PLAN", "LANDSCAPE", "PAD", "WISPS")

SEED_CONTENT = {
    slug: f"# {slug}\n\nseeded body for {slug}.\nLine two.\n"
    for slug in SEED_SLUGS
}

# Baseline test-fixture project rows (project_seed_test_helpers.seed_project_identities).
PROJECT_ID = 1
PROJECT_SLUG = "yoke"
OTHER_PROJECT_ID = 2
OTHER_PROJECT_SLUG = "externalwebapp"


def seed_docs(conn, project_id: int = PROJECT_ID) -> None:
    for slug in SEED_SLUGS:
        conn.execute(
            f"INSERT INTO {sd.STRATEGY_DOCS_TABLE} "
            "(project_id, slug, content, updated_at) VALUES (%s, %s, %s, %s)",
            (project_id, slug, SEED_CONTENT[slug], SEED_UPDATED_AT),
        )
    conn.commit()


def seed_session(conn, session_id: str) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model, "
        "project_id, workspace, offered_at, last_heartbeat) "
        "VALUES (%s, 'claude-code', 'anthropic', 'm', 1, '/tmp', %s, %s)",
        (session_id, now, now),
    )
    conn.commit()


def seed_process_claim(
    conn, session_id: str, *, process_key: str = PROCESS_STRATEGIZE,
    project_slug: str = PROJECT_SLUG, released: bool = False,
) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, process_key, "
        "conflict_group, claim_type, claimed_at, last_heartbeat, released_at) "
        "VALUES (%s, 'process', %s, %s, 'exclusive', %s, %s, %s)",
        (
            session_id,
            process_key,
            conflict_group_for(process_key, project_slug),
            now,
            now,
            now if released else None,
        ),
    )
    conn.commit()


def build_request(
    function: str,
    payload: dict,
    *,
    session_id: str = SESSION_WITHOUT_CLAIM,
    target_kind: str = "global",
    actor_id: "str | None" = None,
    project: "str | None" = str(PROJECT_ID),
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id=session_id, actor_id=actor_id),
        target=TargetRef(kind=target_kind, project_id=project),
        payload=payload,
    )


def edit_rendered_body(root, slug: str, new_body: str) -> None:
    """Replace a rendered file's body, keeping its header line intact."""
    from yoke_core.domain.strategy_docs_paths import strategy_view_path

    path = strategy_view_path(root, slug)
    first_line, _, _ = path.read_text(encoding="utf-8").partition("\n")
    path.write_text(first_line + "\n" + new_body, encoding="utf-8")


def ingest_files_payload(checkout, slugs, **extra: object) -> dict:
    """Build the client-read files payload the ingest CLI ships."""
    from yoke_core.domain.strategy_docs_ingest import read_ingest_files

    payload = {
        "files": read_ingest_files(checkout, slugs),
        "target_root": str(checkout),
    }
    payload.update(extra)
    return payload


def ok_emit(event_id: str = "evt-strategy-1") -> EmitResult:
    return EmitResult(ok=True, event_id=event_id, reason="", envelope=None)


__all__ = [
    "OTHER_PROJECT_ID",
    "OTHER_PROJECT_SLUG",
    "PROJECT_ID",
    "PROJECT_SLUG",
    "SEED_CONTENT",
    "SEED_SLUGS",
    "SEED_UPDATED_AT",
    "SESSION_WITHOUT_CLAIM",
    "SESSION_WITH_CLAIM",
    "build_request",
    "edit_rendered_body",
    "ingest_files_payload",
    "ok_emit",
    "seed_docs",
    "seed_process_claim",
    "seed_session",
]
