"""Durable canonical-form reachability regression.

Backstop for the rendered ``main_agent`` packet plus the three denial
bodies an agent reads on a failing path-claim operation. The packet
renders once at module scope; storage-backed gate checks use disposable
Postgres fixtures.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain.path_claim_bash_guard_narrative import (
    worktree_unresolved_narrative,
)
from yoke_core.domain.path_claim_register import compose_overlap_denial
from yoke_core.domain.path_claim_required_gate import evaluate
from yoke_core.domain.path_claim_target_resolver import ClaimContext
from yoke_core.domain.yok_n_parser import parse_item_id

_RENDERED_BODY: str = sac.render_role_packet("main_agent")
_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def body() -> str:
    return _RENDERED_BODY


# Canonical columns that must render adjacent to their owning table.
_REQUIRED_TABLE_COLUMNS = {
    "harness_sessions": ("session_id", "executor", "execution_lane",
        "offer_envelope", "current_item_id", "actor_id", "last_heartbeat",
        "ended_at"),
    "path_claims": ("id", "state", "mode", "actor_id", "session_id",
        "item_id", "integration_target", "activated_at", "released_at"),
    "path_targets": ("id", "project_id", "kind", "path_string", "generation",
        "materialization_state", "planned_by_item_id", "planned_by_claim_id"),
    "path_claim_targets": ("id", "claim_id", "target_id", "declared_at"),
    "path_claim_amendments": ("id", "claim_id", "amended_at",
        "amendment_kind", "payload", "reason"),
    "item_sections": ("item_id", "section_name", "content", "ordering",
        "source"),
}


@pytest.mark.parametrize(
    "table, columns", list(_REQUIRED_TABLE_COLUMNS.items())
)
def test_columns_render_adjacent_to_owning_table(
    body: str, table: str, columns: tuple[str, ...]
) -> None:
    for column in columns:
        pat = re.compile(
            rf"`{re.escape(table)}`.*?\b{re.escape(column)}\b", re.DOTALL
        )
        assert pat.search(body), (
            f"{table}.{column} must render adjacent to its owning table."
        )


_CLI_ANCHORS_REQUIRED = (
    # Canonical ``yoke <subcommand>`` agent shapes (current):
    "yoke claims work acquire --item YOK-", "yoke claims work release --item YOK-",
    "yoke claims path register", "yoke claims path widen",
    "yoke lifecycle transition", "yoke events query",
    "yoke items structured-field replace", "yoke items progress-log append",
    "yoke ouroboros field-note append",
    # Source-dev/admin fallbacks the packet explicitly labels.
    "yoke claims path list --item YOK-N",
    "yoke db-claim amend YOK-N", "--state none",
    "backlog-cli", "lifecycle.transition",
    'yoke db read "SELECT 1"',
    "source-dev/operator-debug `db_router query` fallback",
)


@pytest.mark.parametrize("anchor", _CLI_ANCHORS_REQUIRED)
def test_cli_anchor_present(body: str, anchor: str) -> None:
    assert anchor in body, f"CLI cheat sheet must teach anchor {anchor!r}."


_FUNCTION_CALL_ANCHORS = (
    "FunctionCallRequest", "FunctionCallResponse",
    "yoke_contracts.api.function_call",
    "yoke_core.domain.yoke_function_dispatch",
    "session_id", "preconditions", "options",
)


def test_function_call_stanza_names_canonical_models(body: str) -> None:
    for anchor in _FUNCTION_CALL_ANCHORS:
        assert anchor in body, (
            f"function-call surface stanza must name {anchor!r}."
        )


_JSON_NESTED_COLUMNS_REQUIRED = (
    "items.browser_qa_metadata", "items.db_mutation_profile",
    "items.db_compatibility_attestation", "harness_sessions.offer_envelope",
    "qa_requirements.capability_requirements",
    "qa_requirements.success_policy", "epic_tasks.dependencies",
)


@pytest.mark.parametrize("column", _JSON_NESTED_COLUMNS_REQUIRED)
def test_json_nested_schema_renders(body: str, column: str) -> None:
    assert column in body, (
        f"JSON-nested-field schema for {column} must render in the packet."
    )


def test_parse_item_id_accepts_int_internal_id_and_rejects_unscoped_strings() -> None:
    assert parse_item_id(123) == 123
    with pytest.raises(ValueError):
        parse_item_id("123")
    with pytest.raises(ValueError):
        parse_item_id("YOK-123")


def test_worktree_unresolved_denial_embeds_preflight_command() -> None:
    """WORKTREE_UNRESOLVED → preflight (never widen)."""

    ctx = ClaimContext(
        claim_id=42, item_id=123, integration_target="main", state="active",
        covered_paths=("AGENTS.md",), worktree_path=None,
    )
    narrative = worktree_unresolved_narrative(
        tool_kind="Edit", target_path="AGENTS.md", ctx=ctx,
    )
    assert ("python3 -m yoke_core.domain.worktree_preflight --item YOK-123"
            in narrative)
    assert "items.worktree" in narrative
    assert "path-claim-widen" not in narrative
    assert "path-claims widen" not in narrative


def test_path_claim_register_overlap_denial_embeds_coordination_decision(
) -> None:
    body_text = compose_overlap_denial(
        item_id=123, integration_target="main", candidate_target_ids=[],
        base_message="candidate overlaps another active claim", conn=None,
    )
    assert "BLOCKED: path-claim register overlap on item YOK-123" in body_text
    assert ("yoke claims path coordination-decision-build "
            "--item YOK-123 --conflicting-claim ") in body_text
    assert "--paths" in body_text


def test_claim_required_gate_embeds_register_command() -> None:
    from runtime.api.fixtures.pg_testdb import (
        connect_test_database,
        create_test_database,
        drop_test_database,
    )
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

    db_name = create_test_database()
    conn = connect_test_database(db_name)
    try:
        apply_fixture_ddl(
            conn,
            "CREATE TABLE path_claims (id INTEGER PRIMARY KEY, "
            "item_id INTEGER, state TEXT, mode TEXT, "
            "exception_reason TEXT);"
            "CREATE TABLE path_claim_targets ("
            "claim_id INTEGER, target_id INTEGER);",
        )
        result = evaluate(conn, 123)
    finally:
        conn.close()
        drop_test_database(db_name)
    assert result["verdict"] == "block"
    reason = str(result["reason"])
    assert ("python3 -m yoke_core.api.service_client path-claim-register "
            "--item YOK-123 --integration-target main "
            "--paths <comma-separated paths>") in reason


# Pure confabulations + the obsoleted ``--claim-state`` form. Must be
# fully absent from the rendered packet.
_FULLY_BANNED = ("pt.path", "items.item_id", "work_claims.state",
                 "events.source_id", "yoke_db_path", "--claim-state")


@pytest.mark.parametrize("term", _FULLY_BANNED)
def test_no_confabulated_terms_in_packet(body: str, term: str) -> None:
    assert term not in body, (
        f"rendered teaching surface contains banned confabulation {term!r}."
    )


def test_no_bare_claim_list_in_packet(body: str) -> None:
    bare = re.findall(r"(?<!path-)claim-list", body)
    assert bare == [], (
        f"packet teaches bare 'claim-list': {bare}. Use path-claim-list."
    )


def test_get_db_path_only_appears_as_negative_teaching(body: str) -> None:
    """``get_db_path`` may only appear inside negative teaching."""
    remaining = body
    allowed_negative_contexts = (
        'never `python -c "from yoke_core.domain.worktree '
        'import get_db_path"`',
        "Never import a guessed `get_db_path` helper; "
        "no such importable name exists.",
    )
    for context in allowed_negative_contexts:
        assert context in body
        remaining = remaining.replace(context, "")
    assert "get_db_path" not in remaining


def test_no_bare_doctor_invocation_in_packet(body: str) -> None:
    bare = re.findall(
        r"python3 -m runtime\.api\.engines\.doctor\b"
        r"(?!\s+(?:--full|--quick|--only))",
        body,
    )
    assert bare == [], f"packet contains bare doctor invocation(s): {bare}."


def test_authored_qa_docs_teach_canonical_yoke_surfaces() -> None:
    paths = (
        _REPO / ".yoke" / "docs" / "commands.md",
        _REPO / ".yoke" / "docs" / "browser-scenario-schema.md",
        _REPO / "docs" / "browser-substrate" / "scenario-orchestration.md",
        _REPO / ".yoke" / "docs" / "db-reference" / "qa-and-sessions.md",
        _REPO / ".agents" / "skills" / "yoke" / "advance" / "browser-qa.md",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "yoke qa run complete" in text
    assert "--requirement-id" in text
    assert "yoke qa screenshot-evidence satisfy" in text
    assert "qa run-complete" not in text
    assert "satisfy-screenshot-evidence" not in text


def test_authored_claim_docs_teach_canonical_widen_surface() -> None:
    paths = (
        _REPO / "docs" / "path-claims.md",
        _REPO / ".agents" / "skills" / "yoke" / "refine" / "SKILL.md",
        _REPO / ".agents" / "skills" / "yoke" / "advance"
        / "preflight-checks.md",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "yoke claims path widen" in text
    assert "--claim-id" in text
    assert "--add-paths" in text
    assert "--reason" in text
    assert "--item YOK-N" in text
    assert "path-claims widen --claim-id" not in text
    assert "path-claims widen <claim-id>" not in text
    assert "claims path widen <id>" not in text


def test_authored_claim_docs_teach_canonical_conflicts_surface(body: str) -> None:
    paths = (
        _REPO / "docs" / "path-claims.md",
    )
    text = body + "\n" + "\n".join(
        path.read_text(encoding="utf-8") for path in paths
    )

    assert "yoke path-claims conflicts list" in text
    assert "yoke claims path conflicts list" not in text


def test_db_claim_docs_teach_required_apply_strategy_and_role_enum() -> None:
    paths = (
        _REPO / ".yoke" / "docs" / "db-reference" / "items-and-epics.md",
        _REPO / ".agents" / "skills" / "yoke" / "idea"
        / "body-and-sync-functions.md",
        _REPO / ".agents" / "skills" / "yoke" / "refine"
        / "update-protocol.md",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "migration_strategy" in text
    assert "mutation_intent=\"apply\"" in text
    assert "role` is only `reader` or `writer`" in text
