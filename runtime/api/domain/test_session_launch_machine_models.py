"""Launch selection defaults belong to the machine that runs the session."""

from __future__ import annotations

from yoke_contracts.machine_config.preferred_session_models import EXPLICIT_SOURCE
from yoke_core.domain.session_launch_machine_models import (
    machine_preferred_models,
    machine_preferred_reasoning_efforts,
    resolve_machine_selection,
)
from yoke_core.domain.session_launch_requests import create_launch, retry_launch
from yoke_core.domain.session_launch_store import update_launch
from yoke_core.domain.session_launch_types import LaunchRequest
from yoke_core.domain.session_relay_launch_lease import claim_next_launch
from yoke_core.domain.session_relay_types import RelayHeartbeat

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    launch_connection,
    plan_limit_document,
)


SURFACE = "codex-cli"
NEAR_RESET = "2026-08-22T13:00:00Z"
CLAUDE_MACHINE_ID = "33333333-3333-4333-8333-333333333333"


def _machine(
    conn,
    machine_id: str,
    *,
    model: str,
    remaining: float,
    effort: str | None = None,
) -> None:
    add_relay(
        conn,
        relay_id=f"relay-{machine_id}",
        machine_id=machine_id,
        surface=SURFACE,
        plan_limits=plan_limit_document(
            SURFACE, remaining_percent=remaining, resets_at=NEAR_RESET
        ),
        preferred_models={SURFACE: model},
        preferred_reasoning_efforts={SURFACE: effort} if effort else None,
    )


def _create(conn, *, key: str, model: str | None = None):
    return create_launch(
        conn,
        auth=authorization(actor_id=1),
        request=LaunchRequest(
            project_id=10,
            executor_surface=SURFACE,
            instructions="Report the current evidence.",
            idempotency_key=key,
            model=model,
        ),
        now=NOW,
    )


def test_unnamed_model_resolves_against_the_chosen_machine() -> None:
    conn = launch_connection()
    _machine(conn, "machine-roomy", model="gpt-5.6-sol", remaining=90.0)
    _machine(conn, "machine-tight", model="gpt-5.4", remaining=10.0)

    launch = _create(conn, key="machine-model").launch

    assert launch.assigned_machine_id == "machine-roomy"
    assert launch.requested_model is None
    assert launch.resolved_model == "gpt-5.6-sol"


def test_an_explicit_model_is_never_replaced_by_a_machine_default() -> None:
    conn = launch_connection()
    _machine(conn, "machine-roomy", model="gpt-5.6-sol", remaining=90.0)

    launch = _create(conn, key="explicit-model", model="gpt-5.4").launch

    assert launch.requested_model == "gpt-5.4"
    assert launch.resolved_model == "gpt-5.4"


def test_each_unnamed_knob_resolves_from_the_chosen_machine() -> None:
    conn = launch_connection()
    add_relay(
        conn,
        relay_id="relay-claude",
        machine_id=CLAUDE_MACHINE_ID,
        surface="claude-cli",
        version="2.1.259",
        preferred_models={"claude-cli": "claude-opus-4-8[1m]"},
        preferred_reasoning_efforts={"claude-cli": "max"},
    )

    launch = create_launch(
        conn,
        auth=authorization(actor_id=1),
        request=LaunchRequest(
            project_id=10,
            executor_surface="claude-cli",
            instructions="Report the current evidence.",
            idempotency_key="machine-selection",
        ),
        now=NOW,
    ).launch

    assert launch.requested_model is None
    assert launch.requested_reasoning_effort is None
    assert launch.requested_context_window_tokens is None
    assert launch.resolved_model == "claude-opus-4-8"
    assert launch.resolved_reasoning_effort == "max"
    assert launch.resolved_context_window_tokens == 1_000_000
    jobs = claim_next_launch(
        conn,
        RelayHeartbeat(
            relay_id="relay-claude",
            actor_id=1,
            machine_id=CLAUDE_MACHINE_ID,
            hostname="claude-host",
            relay_version="source",
            surface_versions={"claude-cli": "2.1.259"},
            project_ids=(10,),
        ),
        now=NOW,
    )
    assert jobs[0].requested_model == "claude-opus-4-8"
    assert jobs[0].requested_reasoning_effort == "max"
    assert jobs[0].requested_context_window_tokens == 1_000_000


def test_a_machine_naming_no_default_leaves_the_vendor_default() -> None:
    conn = launch_connection()
    add_relay(conn, relay_id="relay-a", machine_id="machine-a", surface=SURFACE)

    launch = _create(conn, key="vendor-default").launch

    assert launch.resolved_model is None


def test_a_replay_of_the_same_request_is_still_the_same_request() -> None:
    conn = launch_connection()
    _machine(conn, "machine-roomy", model="gpt-5.6-sol", remaining=90.0)
    _machine(conn, "machine-tight", model="gpt-5.4", remaining=10.0)
    first = _create(conn, key="replay-key")
    # The roomy machine burns down between the create and its retry, so the
    # replay would place elsewhere and resolve a different default.
    conn.execute(
        "UPDATE session_relays SET surface_plan_limits = ? WHERE machine_id = ?",
        (
            __import__("json").dumps(
                plan_limit_document(
                    SURFACE, remaining_percent=1.0, resets_at=NEAR_RESET
                )
            ),
            "machine-roomy",
        ),
    )
    conn.commit()

    replay = _create(conn, key="replay-key")

    assert replay.deduplicated is True
    assert replay.launch.launch_id == first.launch.launch_id
    assert replay.launch.resolved_model == "gpt-5.6-sol"


def test_a_retried_launch_re_resolves_on_the_machine_it_lands_on() -> None:
    conn = launch_connection()
    _machine(
        conn,
        "machine-roomy",
        model="gpt-5.6-sol",
        effort="xhigh",
        remaining=90.0,
    )
    launch = _create(conn, key="retry-key").launch
    update_launch(conn, launch.launch_id, state="failed", result_code="native_failed")
    conn.execute("DELETE FROM session_relays WHERE machine_id = 'machine-roomy'")
    _machine(
        conn,
        "machine-other",
        model="gpt-5.4",
        effort="high",
        remaining=50.0,
    )

    retried = retry_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(actor_id=1),
        now=NOW,
    )

    assert retried.assigned_machine_id == "machine-other"
    assert retried.resolved_model == "gpt-5.4"
    assert retried.resolved_reasoning_effort == "high"


def test_advertised_models_drop_blank_and_non_string_entries() -> None:
    conn = launch_connection()
    add_relay(
        conn,
        relay_id="relay-a",
        machine_id="machine-a",
        surface=SURFACE,
        preferred_models={SURFACE: "  ", "claude-cli": "claude-opus-5"},
    )

    models = machine_preferred_models(conn, machine_id="machine-a")

    assert models == {"claude-cli": "claude-opus-5"}
    assert (
        resolve_machine_selection(
            conn,
            requested_model=None,
            requested_reasoning_effort=None,
            requested_context_window_tokens=None,
            machine_id="machine-a",
            surface=SURFACE,
        ).model
        is None
    )
    assert (
        resolve_machine_selection(
            conn,
            requested_model="pinned",
            requested_reasoning_effort=None,
            requested_context_window_tokens=None,
            machine_id="machine-a",
            surface=SURFACE,
        ).sources["model"]
        == EXPLICIT_SOURCE
    )
    assert machine_preferred_reasoning_efforts(conn, machine_id="machine-a") == {}
