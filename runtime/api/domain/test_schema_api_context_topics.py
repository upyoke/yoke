"""packet additions for the agent-context generator.

Project topic, qa-gate preview, dependency wrappers, and stale-term /
role-topic doctrine. Tests for older AC-1..AC-22 surface live in
``test_schema_api_context.py``; this sibling stays small so neither
file presses the file-line cap.
"""

from __future__ import annotations

import subprocess

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain import schema_api_context_seed as seed


def _qa_help(subcommand: str) -> str:
    result = subprocess.run(
        ["python3", "-m", "yoke_core.domain.qa", subcommand, "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return (result.stdout or "") + (result.stderr or "")


def test_project_topic_renders_command_definitions_recipes() -> None:
    body = sac.render_topic_packet("project")
    # Every supported scope appears so agents pick the right command.
    for scope in ("quick", "full", "e2e", "smoke"):
        assert scope in body, f"project topic missing scope keyword: {scope}"
    assert (
        "yoke project-structure command-definitions get "
        "--project <project> --scope quick"
    ) in body
    assert (
        "yoke project-structure command-definitions list --project <project>"
    ) in body
    assert "project_structure.command_definitions.get" in body
    assert "project_structure.command_definitions.list" in body
    assert "raw command_definitions module" in body


def test_project_topic_renders_deploy_defaults_recipe() -> None:
    body = sac.render_topic_packet("project")
    assert ("yoke project-structure deploy-defaults get --project <project>") in body
    assert "project_structure.deploy_defaults.get" in body
    assert "raw deploy_defaults module" in body


def test_project_topic_warns_no_command_definitions_table() -> None:
    """The packet must teach that there is no top-level command_definitions
    table — agents who raw-query that name hit `no such table`."""

    body = sac.render_topic_packet("project")
    assert "no top-level command_definitions" in body, (
        "project topic must warn that there is no command_definitions table"
    )


def test_project_topic_warns_settings_are_not_on_projects() -> None:
    body = sac.render_topic_packet("project")
    assert "yoke projects get --project <slug>" in body
    assert "projects.settings" in body
    assert "project_capabilities.settings" in body
    assert "environment settings surfaces" in body


def test_qa_topic_includes_gate_preview_with_both_target_forms() -> None:
    body = sac.render_topic_packet("qa")
    assert "qa_gates" not in body
    assert "check-reviewed-implementation-gate" not in body
    assert "yoke qa gate-summary" in body
    # Both supported target forms are surfaced.
    assert "--item" in body
    assert "--epic-id" in body
    assert "--task-num" in body
    # AC-5 anchor: the recipe must instruct routing through advance.
    assert "/yoke advance" in body


def test_qa_topic_includes_requirement_list_recipe_matching_cli() -> None:
    """AC-16: the packet teaches the registered QA requirement-list wrapper.

    The legacy domain CLI still has a different flag spelling; packets must
    prefer the product wrapper and avoid teaching task-num filtering on the
    list command.
    """

    body = sac.render_topic_packet("qa")
    requirement_help = _qa_help("requirement-list")
    assert "--item-id" in requirement_help
    assert "--epic-id" in requirement_help
    assert "--task-num" not in requirement_help
    assert "yoke qa requirement list --item PREFIX-N" in body
    assert "--epic-id E" in body
    assert "--epic-id" in body
    assert "qa requirement list --task-num" not in body


def test_qa_topic_includes_run_get_recipe_matching_cli() -> None:
    """Packets teach the registered one-run getter and keep list separate."""

    body = sac.render_topic_packet("qa")
    run_list_help = _qa_help("run-list")
    run_get_help = _qa_help("run-get")
    assert "--requirement-id" in run_list_help
    assert "--requirement-id" not in run_get_help
    assert "positional arguments" in run_get_help
    assert "yoke qa run list --requirement-id <id>" in body
    assert "yoke qa run get --run-id <id>" in body
    assert "Registered read qa.run.get" in body
    assert "qa {run-list,run-get} --requirement-id" not in body


def test_core_topic_includes_dependency_wrappers() -> None:
    """AC-13: dependency wrappers route through `shepherd dependency-*`."""

    body = sac.render_topic_packet("core")
    assert "shepherd dependency-list" in body
    assert "dependent_item/blocking_item store public YOK-N text refs" in body
    assert "not numeric items.id values" in body
    assert "Dependency add/update/remove are authoring-time surfaces" in body
    assert "registered command adapters land" in body
    assert "yoke shepherd dependency-add" not in body
    assert "yoke shepherd dependency-update" not in body
    assert "yoke shepherd dependency-remove" not in body


def test_core_topic_pins_itemless_deploy_to_product_checkout() -> None:
    body = sac.render_topic_packet("core")
    fetch = 'git -C "$source_checkout" fetch origin "$target_branch"'
    detach = 'git -C "$source_checkout" checkout --detach FETCH_HEAD'
    watched = 'watch_deploy --product-src "$source_checkout" -- {run-id}'
    assert fetch in body
    assert detach in body
    assert "rev-parse --short" not in body
    assert "$source_checkout/packages/yoke-core/src" in body
    assert watched in body
    assert "canonical 12-character registry tag" in body
    assert "YOKE_GITHUB_ACTIONS_RELAY_ENV=<hosted-control-plane-env>" in body
    assert "YOKE_GITHUB_ACTIONS_LOCAL_AUTHORITY=1" in body
    assert "never leave authority selection implicit" in body
    assert (
        body.index(fetch) < body.index(detach) < body.index(watched)
    )


def test_every_role_packet_teaches_worktree_source_pythonpath() -> None:
    body = sac.render_topic_packet("core")
    for token in (
        "Verify Python imports/tests against linked worktree source",
        "packages/yoke-contracts/src",
        "packages/yoke-cli/src",
        "packages/yoke-core/src",
        "packages/yoke-harness/src",
        "yoke_core.__file__",
        "python3 -m yoke_core.tools.watch_pytest",
        "python3 -m yoke_cli.main agents render",
        "externally-managed Python",
    ):
        assert token in body

    for role in seed.ROLE_TOPICS:
        role_body = sac.render_role_packet(role)
        assert "Verify Python imports/tests against linked worktree source" in role_body
        assert "yoke_core.__file__" in role_body


def test_main_packet_includes_learning_log_and_deployment_runs() -> None:
    main_body = sac.render_role_packet("main_agent")

    assert "ouroboros_entries" in main_body
    assert "deployment_runs" in main_body
    assert "There is no `item_id` column on this table" in main_body


_NEW_STALE_TERMS_2026_05 = (
    "command_definitions WHERE",
    "qa_kind='review'",
    "--qa-kind review",
    ".agents/skills/yoke/scripts/python3 -m yoke_core.cli.db_router qa",
    "blocker_item_id",
)


def test_new_stale_terms_in_seed() -> None:
    """AC-6 / AC-14: the stale-term additions are present in the
    seed regression list."""

    for term in _NEW_STALE_TERMS_2026_05:
        assert term in seed.STALE_TERMS, f"STALE_TERMS missing YOK-1611 entry: {term!r}"


def test_engineer_and_tester_receive_project_and_qa_topics() -> None:
    """AC-9: Engineer and Tester get every topic; Architect / Simulator /
    Boss intentionally omit `qa` and `project` (they plan, trace, or
    review without invoking the gate or command_definitions directly)."""

    assert seed.ROLE_TOPICS["engineer_agent"] == ("core", "claims", "qa", "project")
    assert seed.ROLE_TOPICS["tester_agent"] == ("core", "claims", "qa", "project")
    for role in ("architect_agent", "simulator_agent", "boss_agent"):
        assert seed.ROLE_TOPICS[role] == ("core", "claims"), (
            f"role={role} should NOT carry qa or project topics — see "
            "schema_api_context_seed.py docstring for rationale"
        )


def test_main_agent_role_present_with_core_claims_auth_qa_and_deploy_hint() -> None:
    """main_agent is the LLM-facing top-level packet for conduct / polish /
    advance main sessions that orchestrate engineer + tester loops.

    Carries ``core`` + ``claims`` + ``auth`` + ``qa``. ``qa`` is included
    because main sessions routinely inspect tester-review state
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
    ), "main_agent carries core + claims + auth + qa"
    body = sac.render_role_packet("main_agent")
    assert body.strip(), "main_agent packet body must be non-empty"
    assert sac._TOPIC_HEADERS["core"] in body
    assert sac._TOPIC_HEADERS["claims"] in body
    assert sac._TOPIC_HEADERS["auth"] in body
    assert sac._TOPIC_HEADERS["qa"] in body
    assert sac._TOPIC_HEADERS["project"] not in body
    assert "deployment_runs" in body
    assert "deployment_run_items" in body


def test_qa_topic_includes_gate_summary_recipe_matching_cli() -> None:
    """/ AC-10: the qa packet must surface the
    ``qa gate-summary`` command and its supported targets so main-session
    agents do not regress to raw ``qa_requirements`` SQL during the
    final reviewed-implementation / implemented gate check. Recipe text
    must agree with the live CLI surface."""

    body = sac.render_topic_packet("qa")
    assert "qa gate-summary" in body
    # Target vocabulary surfaced verbatim from the CLI.
    assert "reviewed-implementation" in body
    assert "implemented" in body

    summary_help = _qa_help("gate-summary")
    assert "--item-id" in summary_help
    assert "--target" in summary_help
    assert "reviewed-implementation" in summary_help
    assert "implemented" in summary_help
    # The recipe and the live CLI agree on the supported targets.
    for target in ("reviewed-implementation", "implemented"):
        assert target in body
        assert target in summary_help


def test_qa_topic_events_recipe_matches_supported_filter_shape() -> None:
    """/ AC-9: the events recipe must teach the supported
    filter shape. The canonical agent recipe is the registered
    ``yoke events query`` form carrying ``--item``; the db_router
    long form survives only as a labelled operator-debug fallback."""

    body = sac.render_topic_packet("qa")
    # The packet must surface --item on the canonical events read —
    # it routes through normalize_event_item_id (YOK-N + bare-int).
    assert "events query --item" in body
    # The retired unbounded db_router recipe is not taught as the
    # primary shape.
    assert "events list --item YOK-N\n" not in body
    # The packet teaches the bounded form (with --limit) so agents do
    # not paste an unbounded dump command.
    assert "--limit" in body


def test_role_keys_use_layer_explicit_agent_suffix() -> None:
    """/ AC-12: every role key in ROLE_TOPICS ends in
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
