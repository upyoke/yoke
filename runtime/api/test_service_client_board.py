"""Tests for service_client board and classify commands.

Split from test_service_client.py.
"""

from __future__ import annotations

from runtime.api.test_service_client import _run_client


# ---------------------------------------------------------------------------
# classify-status tests
# ---------------------------------------------------------------------------


class TestClassifyStatus:
    """Tests for classify-status board bucket mapping."""

    def test_implementing_maps_to_implementing(self):
        result = _run_client(["classify-status", "implementing"])
        assert result.returncode == 0
        assert result.stdout.strip() == "implementing"

    def test_done_maps_to_done(self):
        result = _run_client(["classify-status", "done"])
        assert result.returncode == 0
        assert result.stdout.strip() == "done"

    def test_cancelled_maps_to_done(self):
        result = _run_client(["classify-status", "cancelled"])
        assert result.returncode == 0
        assert result.stdout.strip() == "done"

    def test_frozen_overrides_status(self):
        result = _run_client(["classify-status", "implementing", "--frozen", "1"])
        assert result.returncode == 0
        assert result.stdout.strip() == "frozen"

    def test_implemented_with_active_run_maps_to_release(self):
        result = _run_client(
            ["classify-status", "implemented", "--has-active-run", "1"]
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "release"

    def test_blocked_maps_to_blocked(self):
        result = _run_client(["classify-status", "blocked"])
        assert result.returncode == 0
        assert result.stdout.strip() == "blocked"

    def test_reviewing_implementation_maps_to_reviewing(self):
        result = _run_client(["classify-status", "reviewing-implementation"])
        assert result.returncode == 0
        assert result.stdout.strip() == "reviewing"

    def test_idea_maps_to_idea(self):
        result = _run_client(["classify-status", "idea"])
        assert result.returncode == 0
        assert result.stdout.strip() == "idea"

    def test_planned_maps_to_refined(self):
        result = _run_client(["classify-status", "planned"])
        assert result.returncode == 0
        assert result.stdout.strip() == "refined"

    def test_unknown_maps_to_unknown(self):
        result = _run_client(["classify-status", "bogus"])
        assert result.returncode == 0
        assert result.stdout.strip() == "unknown"


class TestBacklogCli:
    def test_backlog_cli_routes_rebuild_board(self, monkeypatch):
        import yoke_core.api.service_client as service_client
        import yoke_cli.main as yoke_cli

        calls: list[list[str]] = []
        monkeypatch.setattr(
            yoke_cli, "main",
            lambda argv: calls.append(list(argv)) or 0,
        )

        rc = service_client.cmd_backlog_cli(["rebuild-board"])

        assert rc == 0
        assert calls == [["board", "rebuild"]]

    def test_backlog_cli_rejects_ingest_body(self, capsys):
        import yoke_core.api.service_client as service_client

        rc = service_client.cmd_backlog_cli(["ingest-body", "1"])

        captured = capsys.readouterr()
        assert rc == 1
        assert "no longer supported" in captured.err
