"""Projectless steering retains home scope while creating project workers."""

import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from runtime.api.domain import test_session_registration_scope as registration
from yoke_contracts.timestamps import utc_now
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.machine_registry import register_machine
from yoke_core.domain.session_launch_origin import derived_launch_origin
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_registration import prepare_launch_registration
from yoke_core.domain.session_launch_registered_session_binding import (
    require_exact_launch_session,
    require_registered_session_facts,
)
from yoke_core.domain.session_relay_launch_lease import claim_next_launch
from yoke_core.domain.session_relay_types import RelayHeartbeat
from yoke_harness.session_relay_runtime import execution_context
from yoke_cli.config import machine_config
from runtime.api.domain.test_session_launch_handler_deadlines import _NoCloseConnection
from yoke_core.domain.session_launch_authorization import launch_authorization
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from yoke_core.domain.steering_claims import acquire

world = registration.world


@pytest.fixture
def home(world, tmp_path):
    session, machine = str(uuid4()), str(uuid4())
    registration.register(
        world, sid=session, workspace=str(tmp_path / "home"), machine_id=machine
    )
    acquire(world.conn, session_id=session, project_id=1)
    auth = launch_authorization(
        world.conn, actor_id=world.owner, project_id=1, session_id=session
    )
    assert auth.can_operate_project
    return SimpleNamespace(w=world, session=session, machine=machine, auth=auth)


@pytest.mark.parametrize(
    "surface", ["claude-desktop", "codex-desktop", "cursor-desktop"]
)
def test_missing_capability_explicit_deferral(home, surface):
    conn = home.w.conn
    before = conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0]
    with pytest.raises(SessionLaunchError) as caught:
        create_launch(
            conn,
            auth=home.auth,
            request=LaunchRequest(
                project_id=1,
                executor_surface=surface,
                instructions="Inspect the project and report evidence.",
                idempotency_key=str(uuid4()),
            ),
            now=utc_now(),
        )
    assert caught.value.code == "unsupported_surface"
    assert "create" in str(caught.value)
    assert (
        "launch from a supported harness or open a session in the project folder"
        in str(caught.value)
    )
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == before


def test_machine_scope_session_refuses_project_launch_binding_by_name(home):
    facts = require_registered_session_facts(home.w.conn, home.session)
    assert facts["project_id"] is None
    launch = SimpleNamespace(
        project_id=1,
        selected_surface=facts["surface"],
        assigned_machine_id=None,
        native_session_id=home.session,
    )
    with pytest.raises(SessionLaunchError) as caught:
        require_exact_launch_session(launch, home.session, facts)
    assert caught.value.code == "project_mismatch"
    assert "started outside any project" in str(caught.value)
    assert "yoke project register CHECKOUT --project-id 1" in str(caught.value)


@pytest.fixture(params=["claude-cli", "codex-cli", "cursor-cli"])
def launched(home, request, tmp_path, monkeypatch):
    """Real server lifecycle; native startup is a controlled provider boundary."""
    conn, surface = home.w.conn, request.param
    now = utc_now()
    version = capability_for_surface(surface).minimum_version
    project = tmp_path / "project"
    project.mkdir()
    slug = conn.execute("SELECT slug FROM projects WHERE id=1").fetchone()[0]
    register_machine(
        conn,
        machine_id=home.machine,
        name="Launch host",
        actor_id=home.w.owner,
        now=now,
    )
    relay = str(uuid4())
    conn.execute(
        "INSERT INTO session_relays (relay_id,actor_id,machine_id,hostname,"
        "surface_versions,project_checkouts,first_seen_at,last_seen_at,"
        "connected_until,state) VALUES (%s,%s,%s,'launch-host',%s,%s,%s,%s,%s,'active')",
        (
            relay,
            home.w.owner,
            home.machine,
            json.dumps({surface: version}),
            json.dumps([1]),
            now,
            now,
            now + timedelta(minutes=10),
        ),
    )
    conn.commit()
    monkeypatch.setattr(handlers, "_open", lambda: _NoCloseConnection(conn))
    before = registration.stored(home.w, home.session)
    result = handlers.handle_launch_create(
        FunctionCallRequest(
            function="session_control.launch.create",
            actor=ActorContext(actor_id=str(home.w.owner), session_id=home.session),
            target=TargetRef(kind="global"),
            payload=dict(
                project=slug,
                executor_surface=surface,
                instructions="Inspect the project and report evidence.",
                machine_id=home.machine,
                compose_mandate=False,
                idempotency_key=str(uuid4()),
            ),
        )
    )
    assert result.primary_success, result.error
    launch = get_launch(conn, result.result_payload["launch"]["launch_id"])
    heartbeat = RelayHeartbeat(
        relay,
        home.w.owner,
        home.machine,
        "launch-host",
        "1.0.0",
        {surface: version},
        [1],
    )
    jobs = claim_next_launch(conn, heartbeat, now=now)
    assert len(jobs) == 1
    job = jobs[0]
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **kw: [machine_config.ConfiguredProject(project, 1, {})],
    )
    context = execution_context(job.to_dict())
    worker = str(uuid4())

    def start_worker():
        registration.register(
            home.w,
            sid=worker,
            project_id=1,
            machine_scope=False,
            workspace=str(context.checkout),
            executor=surface,
            provider="anthropic" if surface == "claude-cli" else "openai",
            executor_version=version,
            machine_id=home.machine,
            launch_id=launch.launch_id,
        )
        return prepare_launch_registration(
            conn,
            launch_id=launch.launch_id,
            attestation=job.launch_attestation,
            session_id=worker,
            now=utc_now(),
        )

    # Cursor's real adapter additionally resolves the worker its provider creates.
    # No vendor program or interactive session is launched by this port.
    if surface == "cursor-cli":
        from dataclasses import replace
        from yoke_harness.session_relay_cursor import (
            CursorNativeResult,
            build_cursor_adapter,
        )

        class NativePort:
            def new_session(self, native):
                assert native.checkout == project
                assert native.launch_id == launch.launch_id
                assert native.launch_attestation == job.launch_attestation
                assert native.native_instruction == job.native_instruction
                start_worker()
                return CursorNativeResult("native_created", worker)

            def resume_chat(self, native):
                pytest.fail("a create must never resume a session")

        def resolve(workspace):
            assert workspace == str(project)
            bound = get_launch(conn, launch.launch_id)
            return dict(
                status="registration_bound", session_id=bound.registered_session_id
            )

        outcome = build_cursor_adapter(subprocess_port=NativePort())(
            replace(context, launch_registration_resolver=resolve)
        )
        assert outcome.result_code == "native_created"
        assert outcome.native_session_id == worker
    else:
        start_worker()
    return SimpleNamespace(
        home=home,
        before=before,
        launch=launch,
        job=job,
        context=context,
        worker=worker,
        project=project,
    )


def test_projectless_seat_holder_launches_background_worker(launched):
    h = launched.home
    assert (
        derived_launch_origin(h.w.conn, session_id=h.session, project_id=1)
        == "steering"
    )
    assert launched.before["project_id"] is None
    assert launched.before["org_id"] == h.w.org
    assert launched.launch.project_id == launched.job.project_id == 1
    assert launched.launch.assigned_machine_id == h.machine
    assert launched.context.checkout == launched.project
    assert launched.context.project_id == 1
    assert launched.context.job_kind == "launch"


def test_launch_binding_matches_worker_project(launched):
    conn = launched.home.w.conn
    bound = get_launch(conn, launched.launch.launch_id)
    worker = registration.stored(launched.home.w, launched.worker)
    assert bound.registered_session_id == bound.native_session_id == launched.worker
    assert worker["project_id"] == bound.project_id == 1
    assert worker["org_id"] is None
    assert worker["actor_id"] == launched.home.w.owner
    assert worker["machine_id"] == launched.home.machine
    assert worker["workspace"] == str(launched.project)
    recipients = conn.execute(
        "SELECT session_id,project_id,org_id FROM session_message_recipients "
        "WHERE message_id=%s",
        (bound.message_id,),
    ).fetchall()
    assert [(r[0], r[1], r[2]) for r in recipients] == [(launched.worker, 1, None)]


def test_home_scope_unchanged_after_launch(launched):
    after = registration.stored(launched.home.w, launched.home.session)
    for key in ("project_id", "org_id", "actor_id", "workspace", "machine_id"):
        assert after[key] == launched.before[key]
    assert after["project_id"] is None
    assert after["org_id"] == launched.home.w.org


def test_no_interactive_presentation(launched):
    assert launched.launch.presentation_preference in (None, "local")
    assert launched.job.presentation in (None, "local")
    assert launched.context.presentation in (None, "local")
    if launched.context.surface == "claude-cli":
        from yoke_harness.session_relay_claude_native import native_invocation

        invocation = native_invocation(
            launched.context,
            executable="/unused/claude",
            instruction=launched.context.native_instruction,
        )
        assert "-p" in invocation.argv
        assert "--output-format" in invocation.argv
        assert invocation.cwd == launched.project
    elif launched.context.surface == "codex-cli":
        from yoke_harness.session_relay_codex_invocation import codex_base_command

        command = codex_base_command("/unused/codex", launched.context)
        assert command[1:3] == ["exec", "--json"]
        assert "app-server" not in command
