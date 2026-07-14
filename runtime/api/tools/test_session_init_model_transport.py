"""Transport-authority gate for ``session_init._resolve_model``.

On an https connection the ``harness_sessions`` row lives on the connected
server, so the local read would target the wrong authority (finding no row
and degrading to ``detect_model`` after a misleading local read). The gate
skips the local read entirely on https and returns the ``detect_model``
best-effort value; ``yoke sessions offer`` re-resolves the canonical model
server-side. On a local transport the local read is honored as before.
"""

from __future__ import annotations

from unittest import mock

from yoke_core.tools import session_init


class TestRelayOwnsSessionAuthority:
    def test_true_on_https_transport(self, monkeypatch):
        from yoke_core.domain import machine_config

        monkeypatch.setattr(
            machine_config, "active_connection",
            lambda *a, **k: {"transport": "https"},
        )
        assert session_init._relay_owns_session_authority() is True

    def test_false_on_local_transport(self, monkeypatch):
        from yoke_core.domain import machine_config

        monkeypatch.setattr(
            machine_config, "active_connection",
            lambda *a, **k: {"transport": "local-postgres"},
        )
        assert session_init._relay_owns_session_authority() is False

    def test_false_when_config_read_raises(self, monkeypatch):
        from yoke_core.domain import machine_config

        def _boom(*a, **k):
            raise RuntimeError("no config")

        monkeypatch.setattr(machine_config, "active_connection", _boom)
        assert session_init._relay_owns_session_authority() is False


class TestResolveModelTransportGate:
    def test_https_skips_local_read_and_uses_detect_model(self, monkeypatch):
        monkeypatch.setattr(
            session_init, "_relay_owns_session_authority", lambda: True,
        )

        def _forbidden_connect(*a, **k):
            raise AssertionError("https must not open a local DB connection")

        monkeypatch.setattr(session_init, "connect", _forbidden_connect)
        with mock.patch.object(
            session_init, "detect_model", return_value="detected-https",
        ) as detect:
            resolved = session_init._resolve_model("sess-any", "claude-code")
        assert resolved == "detected-https"
        detect.assert_called_once_with("claude-code")

    def test_local_transport_attempts_local_read(self, monkeypatch):
        monkeypatch.setattr(
            session_init, "_relay_owns_session_authority", lambda: False,
        )
        opened = {"n": 0}

        def _raising_connect(_path):
            # The gate is False, so the local read IS attempted; simulate an
            # unavailable DB so resolution falls through to detect_model.
            opened["n"] += 1
            raise RuntimeError("db unavailable")

        monkeypatch.setattr(session_init, "resolve_db_path", lambda: "/x")
        monkeypatch.setattr(session_init, "connect", _raising_connect)
        with mock.patch.object(
            session_init, "detect_model", return_value="detected-local",
        ):
            resolved = session_init._resolve_model("sess-any", "claude-code")
        assert opened["n"] == 1
        assert resolved == "detected-local"
