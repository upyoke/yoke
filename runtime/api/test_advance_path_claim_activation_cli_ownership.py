# ruff: noqa: F811
"""Work-claim ownership checks for advance_path_claim_activation CLI."""

from __future__ import annotations

from yoke_core.domain import advance_path_claim_activation as activation_mod
from yoke_core.domain.advance_path_claim_activation import ActivationResult
from runtime.api.advance_path_claim_activation_cli_test_support import (
    clear_session_env,
    fake_db,  # noqa: F401,F811 - re-exported fixture
    seed_item,
    seed_work_claim,
    stub_run,
)


class TestWorkClaimOwnership:
    def test_refuses_when_other_session_holds_work_claim(
        self, fake_db, monkeypatch, capsys
    ):
        clear_session_env(monkeypatch)
        seed_item(fake_db, 1594, owner=42, source=None)
        seed_work_claim(fake_db, item_id=1594, session_id="other-live")
        stub = stub_run(
            monkeypatch,
            result=ActivationResult(item_id=1594, actor_id=42, outcomes=[]),
        )
        rc = activation_mod.main(
            ["--item", "YOK-1594", "--session-id", "mine"]
        )
        captured = capsys.readouterr()
        assert rc == 1
        assert "BLOCKED: work claim for item 1594" in captured.err
        assert "other-live" in captured.err
        assert "avoid stranded path claims" in captured.err
        stub.assert_not_called()

    def test_proceeds_when_caller_owns_work_claim(
        self, fake_db, monkeypatch, capsys
    ):
        clear_session_env(monkeypatch)
        seed_item(fake_db, 1700, owner=42, source=None)
        seed_work_claim(fake_db, item_id=1700, session_id="mine")
        stub_run(
            monkeypatch,
            result=ActivationResult(item_id=1700, actor_id=42, outcomes=[]),
        )
        rc = activation_mod.main(["--item", "YOK-1700", "--session-id", "mine"])
        assert rc == 0

    def test_proceeds_when_no_work_claim_yet(
        self, fake_db, monkeypatch, capsys
    ):
        clear_session_env(monkeypatch)
        seed_item(fake_db, 1701, owner=42, source=None)
        stub_run(
            monkeypatch,
            result=ActivationResult(item_id=1701, actor_id=42, outcomes=[]),
        )
        rc = activation_mod.main(["--item", "YOK-1701", "--session-id", "mine"])
        assert rc == 0

    def test_skips_check_when_session_id_empty(
        self, fake_db, monkeypatch, capsys
    ):
        clear_session_env(monkeypatch)
        seed_item(fake_db, 1702, owner=42, source=None)
        seed_work_claim(fake_db, item_id=1702, session_id="other")
        stub_run(
            monkeypatch,
            result=ActivationResult(item_id=1702, actor_id=42, outcomes=[]),
        )
        rc = activation_mod.main(["--item", "YOK-1702"])
        assert rc == 0

    def test_ignores_released_work_claims(
        self, fake_db, monkeypatch, capsys
    ):
        clear_session_env(monkeypatch)
        seed_item(fake_db, 1703, owner=42, source=None)
        seed_work_claim(
            fake_db, item_id=1703, session_id="prior", released=True,
        )
        stub_run(
            monkeypatch,
            result=ActivationResult(item_id=1703, actor_id=42, outcomes=[]),
        )
        rc = activation_mod.main(["--item", "YOK-1703", "--session-id", "mine"])
        assert rc == 0

    def test_uses_env_session_id_when_flag_absent(
        self, fake_db, monkeypatch, capsys
    ):
        clear_session_env(monkeypatch)
        monkeypatch.setenv("CLAUDE_SESSION_ID", "env-session")
        seed_item(fake_db, 1704, owner=42, source=None)
        seed_work_claim(fake_db, item_id=1704, session_id="other")
        stub = stub_run(
            monkeypatch,
            result=ActivationResult(item_id=1704, actor_id=42, outcomes=[]),
        )
        rc = activation_mod.main(["--item", "YOK-1704"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "other" in captured.err
        stub.assert_not_called()
