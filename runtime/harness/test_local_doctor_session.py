"""Only a native Full Access Doctor hook may prepare its embedded authority."""

from dataclasses import replace
from pathlib import Path

import pytest

from yoke_core.domain import (
    db_backend,
    local_universe,
    local_universe_convergence,
    postgres_binaries,
    postgres_cluster,
    universe_source_pause,
)
from yoke_core.hooks import local_doctor_session


@pytest.fixture
def doctor_event():
    return {
        "session_id": "native-session",
        "transcript_path": "/native/rollout.jsonl",
        "turn_id": "native-turn",
        "tool_use_id": "native-tool",
        "tool_name": "Bash",
        "tool_input": {
            "command": (
                'yoke doctor >doctor.stdout 2>doctor.stderr; '
                'rc=$?; printf "%s\\n" "$rc" >doctor.exit; exit "$rc"'
            )
        },
    }


def test_native_full_access_prepares_the_local_authority(
    monkeypatch, doctor_event
):
    starts = []
    lookups = []

    def read_posture(session_id, **keys):
        lookups.append((session_id, keys))
        return {"approval_policy": "never", "sandbox_mode": "danger-full-access"}, ""

    monkeypatch.delenv("YOKE_HOOK_TOTAL_TIMEOUT_MS", raising=False)
    monkeypatch.setattr(local_doctor_session, "_start_owned_cluster", starts.append)
    local_doctor_session.prepare_local_doctor_session(
        "PreToolUse", "codex", doctor_event, read_posture=read_posture,
    )
    assert lookups == [
        ("native-session", {"turn_id": "native-turn", "tool_use_id": "native-tool"})
    ]
    assert starts == [3]


@pytest.mark.parametrize("facts", [None, {"approval_policy": "on-request"}])
def test_unproved_or_restricted_turn_does_not_start_postgres(
    monkeypatch, doctor_event, facts,
):
    starts = []
    monkeypatch.setattr(local_doctor_session, "_start_owned_cluster", starts.append)
    local_doctor_session.prepare_local_doctor_session(
        "PreToolUse", "codex", doctor_event, read_posture=lambda *_a, **_kw: (facts, ""),
    )
    assert starts == []


@pytest.mark.parametrize(
    ("event", "executor", "command"),
    [
        ("PostToolUse", "codex", "yoke doctor"),
        ("PreToolUse", "claude-code", "yoke doctor"),
        ("PreToolUse", "codex", "yoke doctor --help"),
        ("PreToolUse", "codex", "YOKE_ENV=other yoke doctor"),
        ("PreToolUse", "codex", "echo yoke doctor"),
    ],
)
def test_other_contexts_do_not_read_posture(monkeypatch, doctor_event, event, executor, command):
    def unexpected_lookup(*_args, **_kwargs):
        pytest.fail("unrelated hook tried to read Codex permission state")

    doctor_event["tool_input"]["command"] = command
    local_doctor_session.prepare_local_doctor_session(
        event, executor, doctor_event, read_posture=unexpected_lookup,
    )


@pytest.mark.parametrize(
    ("owned", "paused", "initialized", "start_expected"),
    [(True, False, True, True), (False, False, True, False),
     (True, True, True, False), (True, False, False, False)],
)
def test_only_initialized_unpaused_owned_cluster_is_started(
    tmp_path, monkeypatch, owned, paused, initialized, start_expected,
):
    spec = local_universe.cluster_spec(root=tmp_path / "universe")
    spec = replace(spec, bin_dir=Path("/installed/engine/bin"))
    spec.data_dir.mkdir(parents=True)
    if initialized:
        (spec.data_dir / "PG_VERSION").touch()
    monkeypatch.setattr(db_backend, "resolve_pg_dsn", lambda: "cluster")
    monkeypatch.setattr(local_universe_convergence, "serves_own_universe", lambda dsn: owned)
    monkeypatch.setattr(postgres_binaries, "installed_bin_dir", lambda: spec.bin_dir)
    monkeypatch.setattr(local_universe, "cluster_spec", lambda *, bin_dir: spec)

    def require_running(dsn):
        if paused:
            raise universe_source_pause.UniversePausedError("paused")

    monkeypatch.setattr(universe_source_pause, "require_running", require_running)
    starts = []
    monkeypatch.setattr(
        postgres_cluster, "start_failure", lambda spec, *, timeout_s: starts.append((spec, timeout_s)),
    )
    local_doctor_session._start_owned_cluster(3)
    assert starts == ([(spec, 3)] if start_expected else [])
