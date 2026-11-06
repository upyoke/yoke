"""Tests for service_client board and classify commands.

Split from test_service_client.py.
"""

from __future__ import annotations

from runtime.api.service_client_test_support import _run_client as _run_subprocess
from runtime.api.service_client_in_process_test_support import run_client as _run_client


# ---------------------------------------------------------------------------
# classify-status tests
# ---------------------------------------------------------------------------


class TestClassifyStatus:
    """Tests for classify-status board bucket mapping."""

    def test_unpinned_implementing_is_unknown(self):
        result = _run_subprocess(["classify-status", "implementing"])
        assert result.returncode == 0
        assert result.stdout.strip() == "unknown"

    def test_unpinned_done_is_unknown(self):
        result = _run_client(["classify-status", "done"])
        assert result.returncode == 0
        assert result.stdout.strip() == "unknown"

    def test_cancelled_maps_to_done(self):
        result = _run_client(["classify-status", "cancelled"])
        assert result.returncode == 0
        assert result.stdout.strip() == "done"

    def test_frozen_overrides_status(self):
        result = _run_client(["classify-status", "implementing", "--frozen", "1"])
        assert result.returncode == 0
        assert result.stdout.strip() == "frozen"

    def test_active_run_does_not_supply_missing_stage_metadata(self):
        result = _run_client(
            ["classify-status", "implemented", "--has-active-run", "1"]
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "unknown"

    def test_unpinned_reviewing_is_unknown(self):
        result = _run_client(["classify-status", "reviewing-implementation"])
        assert result.returncode == 0
        assert result.stdout.strip() == "unknown"

    def test_unpinned_idea_is_unknown(self):
        result = _run_client(["classify-status", "idea"])
        assert result.returncode == 0
        assert result.stdout.strip() == "unknown"

    def test_unpinned_planned_is_unknown(self):
        result = _run_client(["classify-status", "planned"])
        assert result.returncode == 0
        assert result.stdout.strip() == "unknown"

    def test_unknown_maps_to_unknown(self):
        result = _run_client(["classify-status", "bogus"])
        assert result.returncode == 0
        assert result.stdout.strip() == "unknown"

    def test_unknown_flag_rejected(self):
        result = _run_subprocess(["classify-status", "idea", "--unknown"])
        assert result.returncode == 2
        assert "Unknown argument: --unknown" in result.stderr


class TestBacklogCli:
    def test_backlog_cli_routes_rebuild_board(self, monkeypatch):
        import yoke_core.api.service_client as service_client
        import yoke_cli.main as yoke_cli

        calls: list[list[str]] = []
        monkeypatch.setattr(
            yoke_cli,
            "main",
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
