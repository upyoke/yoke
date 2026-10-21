"""packet additions for the agent-context generator.

Project topic, qa-gate preview, dependency wrappers, and stale-term /
role-topic doctrine. Tests for the older packet surface live in
``test_schema_api_context.py``; this sibling stays small so neither
file presses the file-line cap.
"""

from __future__ import annotations

import subprocess
import sys

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain.schema_api_context_render import PACKET_DETAIL_FULL


def _qa_help(subcommand: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "yoke_core.domain.qa", subcommand, "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return (result.stdout or "") + (result.stderr or "")


def test_qa_topic_includes_requirement_list_recipe_matching_cli() -> None:
    """The packet teaches the registered QA requirement-list wrapper.

    The legacy domain CLI still has a different flag spelling; packets must
    prefer the product wrapper and avoid teaching task-num filtering on the
    list command.
    """

    requirement_help = _qa_help("requirement-list")
    assert "--item-id" in requirement_help
    assert "--epic-id" in requirement_help
    assert "--task-num" not in requirement_help


def test_qa_topic_includes_run_get_recipe_matching_cli() -> None:
    """Packets teach the registered one-run getter and keep list separate."""

    run_list_help = _qa_help("run-list")
    run_get_help = _qa_help("run-get")
    assert "--requirement-id" in run_list_help
    assert "--requirement-id" not in run_get_help
    assert "positional arguments" in run_get_help


def test_taught_items_get_fields_match_handler_allowlist() -> None:
    from yoke_contracts.items_projection import ALLOWED_GET_FIELDS
    from yoke_core.domain.schema_api_context_commands_core import CORE_COMMANDS

    entry = next(row for row in CORE_COMMANDS if row["purpose"] == "Read item fields")
    taught_segment = (
        entry["notes"].split("Valid fields: ", 1)[1].split(". For body-section", 1)[0]
    )
    taught_fields = {
        field.strip() for field in taught_segment.split(",") if field.strip()
    }

    assert taught_fields == set(ALLOWED_GET_FIELDS)


def test_execution_agents_receive_project_and_qa_topics() -> None:
    """Engineer, Tester, and QA Walker get execution topics; Architect / Simulator /
    Boss intentionally omit `qa` and `project` (they plan, trace, or
    review without invoking project execution surfaces directly)."""

    assert seed.ROLE_TOPICS["engineer_agent"] == ("core", "claims", "qa", "project")
    assert seed.ROLE_TOPICS["tester_agent"] == ("core", "claims", "qa", "project")
    assert seed.ROLE_TOPICS["qa_walker_agent"] == (
        "core",
        "claims",
        "qa",
        "project",
    )
    for role in ("architect_agent", "simulator_agent", "boss_agent"):
        assert seed.ROLE_TOPICS[role] == ("core", "claims"), (
            f"role={role} should NOT carry qa or project topics — see "
            "schema_api_context_seed.py docstring for rationale"
        )


def test_main_agent_role_includes_packs_and_deployment_run_hint() -> None:
    """main_agent is the LLM-facing top-level packet for conduct / polish /
    advance main sessions that orchestrate engineer + tester loops.

    Carries ``core`` + ``claims`` + ``auth`` + ``qa`` + ``packs``. ``qa`` is
    included because main sessions routinely inspect tester-review state
    (``qa_requirements`` / ``qa_runs`` joined on
    ``qa_kind='implementation_review'``) ahead of re-dispatch; without it
    the main session confabulates plausible ``epic_*``-shaped names that
    do not exist. ``auth`` is included because main sessions resolve org/
    project grants and permission decisions (the two-scope
    ``actor_org_roles`` / ``actor_project_roles`` model) and otherwise
    confabulate the retired ``system`` / ``system.admin`` names. A compact
    deployment-run hint is included because main sessions inspect
    deployment_runs while coordinating merge/deploy closeout.
    """

    assert "main_agent" in seed.ROLE_TOPICS, (
        "ROLE_TOPICS must include the main_agent role"
    )
    assert seed.ROLE_TOPICS["main_agent"] == (
        "core",
        "claims",
        "auth",
        "qa",
        "packs",
    ), "main_agent carries core + claims + auth + qa + packs"
    body = sac.render_role_packet("main_agent", detail=PACKET_DETAIL_FULL)
    assert body.strip(), "main_agent packet body must be non-empty"
    assert sac._TOPIC_HEADERS["core"] in body
    assert sac._TOPIC_HEADERS["claims"] in body
    assert sac._TOPIC_HEADERS["qa"] in body
    assert sac._TOPIC_HEADERS["project"] not in body
    assert "deployment_runs" not in body
    depth = sac.render_topic_packet("project", detail=PACKET_DETAIL_FULL)
    assert "deployment_runs" in depth
    assert "deployment_run_items" in depth


def test_qa_topic_includes_gate_summary_recipe_matching_cli() -> None:
    """The qa packet must surface the
    ``qa gate-summary`` command and its supported targets so main-session
    agents do not regress to raw ``qa_requirements`` SQL during the
    final reviewed-implementation / implemented gate check. Recipe text
    must agree with the live CLI surface."""

    summary_help = _qa_help("gate-summary")
    assert "--item-id" in summary_help
    assert "--target" in summary_help
    assert "reviewed-implementation" in summary_help
    assert "implemented" in summary_help


def test_events_table_packet_teaches_text_item_id() -> None:
    """events.item_id is TEXT (bare-numeric text); packet must not
    teach an unquoted integer comparison that Postgres rejects."""

    from yoke_core.domain.schema_api_context_tables import CANONICAL_TABLES

    assert ("item_id", "TEXT") in CANONICAL_TABLES["events"]["columns"]


def test_role_keys_use_layer_explicit_agent_suffix() -> None:
    """Every role key in ROLE_TOPICS ends in
    ``_agent`` so the LLM-facing packet layer is unambiguous and cannot
    be confused with the harness manifest substrate contract
    (``harness_contract``) or with the bare per-role identifiers used
    elsewhere in Yoke."""

    for role in seed.ROLE_TOPICS:
        assert role.endswith("_agent"), (
            f"role key {role!r} is not layer-explicit; expected an "
            "``*_agent`` suffix per YOK-1618"
        )
    # The harness_contract substrate name is reserved for the manifest
    # contract documented in docs/harness-bootstrap.md; it must NEVER be
    # exposed as a schema_api_context role.
    assert "harness_contract" not in seed.ROLE_TOPICS
    assert "harness_contract" not in seed.TOPICS
