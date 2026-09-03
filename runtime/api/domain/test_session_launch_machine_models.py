"""A launch's model default belongs to the machine that will run the session."""

from __future__ import annotations

from yoke_core.domain.session_launch_machine_models import (
    EXPLICIT_REQUEST_SOURCE,
    machine_preferred_models,
    resolve_machine_model,
)
from yoke_core.domain.session_launch_requests import create_launch, retry_launch
from yoke_core.domain.session_launch_store import update_launch
from yoke_core.domain.session_launch_types import LaunchRequest

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    launch_connection,
    plan_limit_document,
)


SURFACE = "codex-cli"
NEAR_RESET = "2026-08-22T13:00:00Z"


def _machine(conn, machine_id: str, *, model: str, remaining: float) -> None:
    add_relay(
        conn,
        relay_id=f"relay-{machine_id}",
        machine_id=machine_id,
        surface=SURFACE,
        plan_limits=plan_limit_document(
            SURFACE, remaining_percent=remaining, resets_at=NEAR_RESET
        ),
        preferred_models={SURFACE: model},
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
    _machine(conn, "machine-roomy", model="gpt-5.6-sol", remaining=90.0)
    launch = _create(conn, key="retry-key").launch
    update_launch(conn, launch.launch_id, state="failed", result_code="native_failed")
    conn.execute("DELETE FROM session_relays WHERE machine_id = 'machine-roomy'")
    _machine(conn, "machine-other", model="gpt-5.4", remaining=50.0)

    retried = retry_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(actor_id=1),
        now=NOW,
    )

    assert retried.assigned_machine_id == "machine-other"
    assert retried.resolved_model == "gpt-5.4"


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
        resolve_machine_model(
            conn, requested_model=None, machine_id="machine-a", surface=SURFACE
        ).model
        is None
    )
    assert (
        resolve_machine_model(
            conn, requested_model="pinned", machine_id="machine-a", surface=SURFACE
        ).source
        == EXPLICIT_REQUEST_SOURCE
    )
