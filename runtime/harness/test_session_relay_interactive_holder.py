"""Every wake leaves a live interactive conversation with its holder."""

from __future__ import annotations

import json

import pytest

from yoke_harness import session_launch_handles, session_relay_runtime as runtime
from yoke_harness.session_launch_containment import supervision_record_path
from yoke_harness.session_relay_native_turn_custody import deferral_for_running_native

SESSION = "11111111-1111-4111-8111-111111111111"
NATIVE = "22222222-2222-4222-8222-222222222222"
START = "Mon Aug 24 08:00:00 2026"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr("yoke_cli.config.machine_config.yoke_home", lambda: tmp_path)
    handles = tmp_path / "handles"
    handles.mkdir()
    monkeypatch.setattr(session_launch_handles, "native_handle_directory", lambda: handles)
    monkeypatch.setattr("os.getpgid", lambda _pid: 7001)
    monkeypatch.setattr(
        "yoke_harness.session_relay_native_turn_custody.process_start_time",
        lambda _pid: START,
    )
    monkeypatch.setattr(
        "yoke_harness.session_relay_interactive_holder.process_start_time",
        lambda _pid: START,
    )
    runtime.reset_relay_adapters_for_tests()
    yield
    runtime.reset_relay_adapters_for_tests()


def anchor(tmp_path, **changes):
    directory = tmp_path / "session-anchors"
    directory.mkdir(exist_ok=True)
    record = {"session_id": SESSION, "anchor_pid": 4001, "anchor_start_time": START}
    record.update(changes)
    (directory / "4001.json").write_text(json.dumps(record))


def context(tmp_path, surface, **changes):
    job = {
        "job_kind": "wake", "job_id": "wake-job", "lease_id": "wake-lease",
        "surface": surface, "target_workspace": str(tmp_path),
        "target_session_id": SESSION, "native_instruction": "deliver message",
        "target_liveness": "ended", "wake_mode": "waiting",
    }
    job.update(changes)
    return runtime.execution_context(job)


@pytest.mark.parametrize("surface", ["claude-cli", "codex-cli", "cursor-cli"])
class TestInteractiveHolder:
    def test_live_interactive_anchor_defers_without_custody(self, tmp_path, surface):
        anchor(tmp_path)
        result = deferral_for_running_native(context(tmp_path, surface))
        assert result is not None
        assert result.result_code == "native_turn_running"
        assert result.evidence == {
            "result_code": "native_turn_running", "running_native_pid": 4001,
            "running_native_start_time": START, "running_native_source": "process_anchor",
        }

    @pytest.mark.parametrize("observed", [None, "different start time"])
    def test_dead_or_reused_pid_proceeds(self, tmp_path, surface, observed):
        anchor(tmp_path)
        assert deferral_for_running_native(
            context(tmp_path, surface), start_time_of=lambda _pid: observed,
        ) is None

    @pytest.mark.parametrize("kind", ["resume", "launch", "handle"])
    def test_relay_owned_group_is_excluded(self, tmp_path, surface, kind):
        anchor(tmp_path)
        # The supervisor pid differs from the native anchor pid. Its completed
        # turn must not be reclassified as an interactive holder by that anchor.
        record = {
            "pid": 5001, "process_start_time": START, "process_group_id": 7001,
            "supervision_kind": kind, "target_session_id": "other-session",
        }
        path = (session_launch_handles.native_handle_directory() / "launch.json"
                if kind == "handle" else supervision_record_path("launch"))
        path.write_text(json.dumps(record))
        assert deferral_for_running_native(context(tmp_path, surface)) is None

    def test_contended_anchor_names_the_target(self, tmp_path, surface):
        anchor(tmp_path, session_id="", shared_by_multiple_sessions=True,
               contending_session_ids=[SESSION, "other-session"])
        assert deferral_for_running_native(context(tmp_path, surface)) is not None

    def test_native_identity_after_fold_also_matches(self, tmp_path, surface):
        anchor(tmp_path, session_id=NATIVE)
        result = deferral_for_running_native(context(
            tmp_path, surface, target_native_thread_id=NATIVE,
        ))
        assert result is not None
        assert result.evidence["running_native_source"] == "process_anchor"

    def test_unrelated_anchor_proceeds(self, tmp_path, surface):
        anchor(tmp_path, session_id=NATIVE)
        assert deferral_for_running_native(context(tmp_path, surface)) is None

    def test_explicit_wake_never_reaches_resume_adapter(self, tmp_path, surface):
        anchor(tmp_path)
        runtime.register_relay_adapter(
            surface, lambda _context: pytest.fail("interactive session resumed"),
        )
        job = context(tmp_path, surface).__dict__
        result = runtime.run_registered_job({**job, "target_workspace": str(tmp_path)})
        assert result.result_code == "native_turn_running"
        assert result.evidence["running_native_source"] == "process_anchor"

    def test_launch_is_not_a_wake(self, tmp_path, surface):
        anchor(tmp_path)
        assert deferral_for_running_native(context(
            tmp_path, surface, job_kind="launch",
        )) is None
