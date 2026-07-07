"""Process-anchor recording inside the shared registration sequence.

``_register_from_hook`` is the one place hooks durably bind
``session_id -> nearest harness ancestor pid``; these tests pin that the
anchor write happens with the payload's transcript path, fires even when
DB registration fails (shell self-identification must survive a briefly
unreachable control plane), and never breaks registration when the
anchor write itself crashes. Sibling ensure-register/flush/runner wiring
coverage lives in :mod:`test_hook_runner_register_ensure`.
"""

from __future__ import annotations

import pytest

import runtime.harness.hook_runner_register as register_module


@pytest.fixture()
def yoke_target(monkeypatch):
    """Pin target resolution + detection so _register_from_hook runs hermetic."""
    monkeypatch.setattr(
        register_module, "resolve_hook_script_dir", lambda: "/hooks",
    )
    monkeypatch.setattr(
        register_module, "resolve_target_root", lambda _d: "/repo",
    )
    monkeypatch.setattr(
        register_module, "is_yoke_target", lambda _r, _d: True,
    )
    monkeypatch.setattr(
        "runtime.harness.hook_helpers.resolve_yoke_db", lambda _d: "",
    )
    for name, value in (
        ("detect_executor", lambda: "claude-code"),
        ("detect_provider", lambda _e: "anthropic"),
        ("detect_model", lambda _e, transcript_path="": "model-x"),
        ("detect_entrypoint", lambda: None),
    ):
        monkeypatch.setattr(f"runtime.harness.hook_helpers.{name}", value)


def _capture_anchors(monkeypatch):
    anchors: list[tuple] = []
    monkeypatch.setattr(
        "yoke_core.domain.session_process_anchors.record_session_anchor",
        lambda sid, transcript_path="": anchors.append((sid, transcript_path)),
    )
    return anchors


class TestRegisterRecordsProcessAnchor:
    def test_anchor_written_with_session_and_transcript(
        self, yoke_target, monkeypatch,
    ):
        monkeypatch.setattr(
            register_module, "register_harness_session", lambda **_k: "",
        )
        anchors = _capture_anchors(monkeypatch)
        err, executor, _p, _m, _e = register_module._register_from_hook(
            '{"transcript_path": "/t/from-payload.jsonl"}', "s-anchored",
        )
        assert err == ""
        assert executor == "claude-code"
        assert anchors == [("s-anchored", "/t/from-payload.jsonl")]

    def test_anchor_written_even_when_registration_fails(
        self, yoke_target, monkeypatch,
    ):
        # Anchor-based shell identity must survive a briefly unreachable
        # control plane — the write is independent of the DB outcome.
        monkeypatch.setattr(
            register_module, "register_harness_session",
            lambda **_k: "db unreachable",
        )
        anchors = _capture_anchors(monkeypatch)
        err, _executor, _p, _m, _e = register_module._register_from_hook(
            '{"transcript_path": "/t/from-payload.jsonl"}', "s-anchored",
        )
        assert err == "db unreachable"
        assert anchors == [("s-anchored", "/t/from-payload.jsonl")]

    def test_explicit_transcript_arg_wins_over_payload(
        self, yoke_target, monkeypatch,
    ):
        monkeypatch.setattr(
            register_module, "register_harness_session", lambda **_k: "",
        )
        anchors = _capture_anchors(monkeypatch)
        register_module._register_from_hook(
            '{"transcript_path": "/t/from-payload.jsonl"}', "s-1",
            transcript_path="/t/explicit.jsonl",
        )
        assert anchors == [("s-1", "/t/explicit.jsonl")]

    def test_anchor_crash_does_not_break_registration(
        self, yoke_target, monkeypatch,
    ):
        monkeypatch.setattr(
            register_module, "register_harness_session", lambda **_k: "",
        )

        def _boom(*_a, **_k):
            raise RuntimeError("anchor write exploded")

        monkeypatch.setattr(
            "yoke_core.domain.session_process_anchors.record_session_anchor",
            _boom,
        )
        err, _executor, _p, _m, _e = register_module._register_from_hook(
            "{}", "s-1",
        )
        assert err == ""

    def test_non_yoke_target_writes_no_anchor(self, monkeypatch):
        monkeypatch.setattr(
            register_module, "resolve_hook_script_dir", lambda: "/hooks",
        )
        monkeypatch.setattr(
            register_module, "resolve_target_root", lambda _d: "",
        )
        anchors = _capture_anchors(monkeypatch)
        result = register_module._register_from_hook("{}", "s-1")
        assert result == ("", "", "", "", None)
        assert anchors == []


class TestRelayOwnedRegistration:
    """https-default machines skip the doomed local registration
    subprocess: the relayed hook chain's server-side ensure-register
    owns the session row, so the Claude/Codex orientation blocks must not
    print the false 'scheduler will not see this session' warning. The skip
    lives in session_lifecycle_client.register_harness_session — the one
    layer both harness orientation paths route through."""

    def test_https_transport_skips_subprocess_and_reports_success(
        self, monkeypatch,
    ):
        from runtime.harness.hook_runner import session_lifecycle_client as slc

        monkeypatch.setattr(slc, "_relay_owns_registration", lambda: True)
        monkeypatch.setattr(
            "runtime.harness.hook_runner.service_client.register_session",
            lambda *a: pytest.fail(
                "https transport must not spawn the local registration "
                "subprocess — the relay owns registration"
            ),
        )
        err = slc.register_harness_session(
            root="/repo", session_id="s-https", executor="claude-code",
            provider="anthropic", model="model-x",
        )
        # Success-shaped: no warning renders in the orientation block.
        assert err == ""

    def test_https_skip_threads_through_register_from_hook(
        self, yoke_target, monkeypatch,
    ):
        from runtime.harness.hook_runner import session_lifecycle_client as slc

        monkeypatch.setattr(slc, "_relay_owns_registration", lambda: True)
        anchors = _capture_anchors(monkeypatch)
        err, executor, _p, model, _e = register_module._register_from_hook(
            '{"transcript_path": "/t/x.jsonl"}', "s-https",
        )
        assert err == ""
        assert executor == "claude-code"
        assert model == "model-x"
        # The process anchor is client-local and still writes on https.
        assert anchors == [("s-https", "/t/x.jsonl")]

    def test_local_transport_still_runs_subprocess(self, monkeypatch):
        from runtime.harness.hook_runner import session_lifecycle_client as slc

        monkeypatch.setattr(slc, "_relay_owns_registration", lambda: False)
        calls = []
        monkeypatch.setattr(
            "runtime.harness.hook_runner.service_client.register_session",
            lambda *a: calls.append(a) or None,
        )
        monkeypatch.setattr(
            slc, "service_client_path", lambda _r: "/sc/service_client.py",
        )
        monkeypatch.setattr(slc, "_project_id_for_root", lambda _r: 1)
        err = slc.register_harness_session(
            root="/repo", session_id="s-local", executor="claude-code",
            provider="anthropic", model="model-x",
        )
        assert err == ""
        assert len(calls) == 1
        assert calls[0][1] == "s-local"

    def test_helper_resolves_false_on_config_read_failure(self, monkeypatch):
        from runtime.harness.hook_runner import session_lifecycle_client as slc

        def _boom():
            raise RuntimeError("config unreadable")

        monkeypatch.setattr(
            "yoke_core.domain.machine_config.active_connection", _boom,
        )
        assert slc._relay_owns_registration() is False

    def test_helper_reads_https_transport_from_active_connection(
        self, monkeypatch,
    ):
        from runtime.harness.hook_runner import session_lifecycle_client as slc

        monkeypatch.setattr(
            "yoke_core.domain.machine_config.active_connection",
            lambda: {"env": "prod", "transport": "https",
                     "api_url": "https://api.example"},
        )
        assert slc._relay_owns_registration() is True
        monkeypatch.setattr(
            "yoke_core.domain.machine_config.active_connection",
            lambda: {"env": "prod-db-admin", "transport": "local-postgres"},
        )
        assert slc._relay_owns_registration() is False


if __name__ == "__main__":  # pragma: no cover - manual run
    raise SystemExit(pytest.main([__file__, "-q"]))
