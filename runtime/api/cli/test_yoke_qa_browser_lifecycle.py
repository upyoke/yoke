"""Tests for ``yoke qa browser`` setup/status lifecycle commands."""

from __future__ import annotations

import io
import json
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from yoke_cli.commands.qa_browser_lifecycle import (
    _ensure_node_prerequisites,
    qa_browser_setup,
    qa_browser_status,
)
from yoke_cli.commands.tool_shaped import resolve_tool_shaped


class TestTokenRouting:
    def test_setup_token_resolves(self):
        resolved = resolve_tool_shaped(["qa", "browser", "setup", "--dry-run"])
        assert resolved is not None
        adapter, rest = resolved
        assert adapter is qa_browser_setup
        assert rest == ["--dry-run"]

    def test_status_token_resolves(self):
        resolved = resolve_tool_shaped(["qa", "browser", "status", "--json"])
        assert resolved is not None
        adapter, rest = resolved
        assert adapter is qa_browser_status
        assert rest == ["--json"]


class TestStatusAdapter:
    def test_status_json_reports_browser_runtime_readiness(self, tmp_path):
        runtime_dir = tmp_path / "browser-runtime"
        runtime_dir.joinpath("node_modules", "playwright").mkdir(parents=True)
        runtime_dir.joinpath(".source-hash").write_text("abc\n", encoding="utf-8")

        def fake_run(command, **_kwargs):
            if command[:2] == ["node", "--version"]:
                return subprocess.CompletedProcess(command, 0, "v20.0.0\n", "")
            if command[:2] == ["npm", "--version"]:
                return subprocess.CompletedProcess(command, 0, "10.0.0\n", "")
            return subprocess.CompletedProcess(command, 0, "ready", "")

        with patch(
            "yoke_harness.browser_runtime_home.runtime_dir",
            return_value=runtime_dir,
        ), patch(
            "yoke_harness.browser_runtime_home.source_hash",
            return_value="abc",
        ), patch(
            "yoke_harness.browser_client.daemon_status",
            return_value={"status": "not_running"},
        ), patch(
            "yoke_cli.commands.qa_browser_lifecycle.subprocess.run",
            side_effect=fake_run,
        ):
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                rc = qa_browser_status(["--json"])

        assert rc == 0
        payload = json.loads(out.getvalue())
        assert payload["runtime_dir"] == str(runtime_dir)
        assert payload["materialized"] is True
        assert payload["node"]["version"] == "v20.0.0"
        assert payload["npm"]["version"] == "10.0.0"
        assert payload["npm_dependencies"]["status"] == "ready"
        assert payload["chromium"]["status"] == "ready"
        assert payload["daemon"] == {"status": "not_running"}
        assert payload["repairs"] == []

    def test_status_human_surfaces_readiness_facts_without_json(self, tmp_path):
        runtime_dir = tmp_path / "browser-runtime"
        runtime_dir.joinpath("node_modules", "playwright").mkdir(parents=True)
        runtime_dir.joinpath(".source-hash").write_text("abc\n", encoding="utf-8")

        def fake_run(command, **_kwargs):
            if command[:2] == ["node", "--version"]:
                return subprocess.CompletedProcess(command, 0, "v20.0.0\n", "")
            if command[:2] == ["npm", "--version"]:
                return subprocess.CompletedProcess(command, 0, "10.0.0\n", "")
            return subprocess.CompletedProcess(command, 0, "ready", "")

        with patch(
            "yoke_harness.browser_runtime_home.runtime_dir",
            return_value=runtime_dir,
        ), patch(
            "yoke_harness.browser_runtime_home.source_hash",
            return_value="abc",
        ), patch(
            "yoke_harness.browser_client.daemon_status",
            return_value={"status": "not_running"},
        ), patch(
            "yoke_cli.commands.qa_browser_lifecycle.subprocess.run",
            side_effect=fake_run,
        ):
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                rc = qa_browser_status([])

        assert rc == 0
        text = out.getvalue()
        # Readiness facts are visible without --json.
        assert str(runtime_dir) in text
        assert "node:" in text and "v20.0.0" in text
        assert "npm:" in text and "10.0.0" in text
        assert "npm dependencies: ready" in text
        assert "chromium:         ready" in text
        assert "daemon:           not_running" in text
        # No repairs needed → repair guidance is omitted.
        assert "repairs:" not in text

    def test_status_human_surfaces_repair_guidance_when_missing(self, tmp_path):
        runtime_dir = tmp_path / "browser-runtime"

        def missing(command, **_kwargs):
            raise OSError(f"{command[0]} missing")

        with patch(
            "yoke_harness.browser_runtime_home.runtime_dir",
            return_value=runtime_dir,
        ), patch(
            "yoke_harness.browser_runtime_home.source_hash",
            return_value="abc",
        ), patch(
            "yoke_harness.browser_client.daemon_status",
            return_value={"status": "not_running"},
        ), patch(
            "yoke_cli.commands.qa_browser_lifecycle.subprocess.run",
            side_effect=missing,
        ):
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                rc = qa_browser_status([])

        assert rc == 0
        text = out.getvalue()
        assert "node:             missing" in text
        assert "npm dependencies: missing" in text
        assert "repairs:" in text
        assert "yoke qa browser setup" in text

    def test_status_json_names_repair_when_runtime_is_missing(self, tmp_path):
        runtime_dir = tmp_path / "browser-runtime"

        def missing(command, **_kwargs):
            raise OSError(f"{command[0]} missing")

        with patch(
            "yoke_harness.browser_runtime_home.runtime_dir",
            return_value=runtime_dir,
        ), patch(
            "yoke_harness.browser_runtime_home.source_hash",
            return_value="abc",
        ), patch(
            "yoke_harness.browser_client.daemon_status",
            return_value={"status": "not_running"},
        ), patch(
            "yoke_cli.commands.qa_browser_lifecycle.subprocess.run",
            side_effect=missing,
        ):
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                rc = qa_browser_status(["--json"])

        assert rc == 0
        payload = json.loads(out.getvalue())
        assert payload["node"]["status"] == "missing"
        assert payload["npm_dependencies"]["status"] == "missing"
        assert any("yoke qa browser setup" in hint for hint in payload["repairs"])


class TestSetupAdapter:
    def test_node_prerequisite_check_noops_when_ready(self):
        def ready(command, **_kwargs):
            value = "v20.0.0\n" if command[0] == "node" else "10.0.0\n"
            return subprocess.CompletedProcess(command, 0, value, "")

        with patch(
            "yoke_cli.commands.qa_browser_lifecycle.subprocess.run",
            side_effect=ready,
        ):
            assert _ensure_node_prerequisites() == []

    def test_node_prerequisite_check_repairs_with_homebrew_on_macos(self):
        versions = iter([
            subprocess.CompletedProcess(["node", "--version"], 1, "", ""),
            subprocess.CompletedProcess(["npm", "--version"], 1, "", ""),
            subprocess.CompletedProcess(["node", "--version"], 0, "v20.0.0\n", ""),
            subprocess.CompletedProcess(["npm", "--version"], 0, "10.0.0\n", ""),
        ])
        commands: list[list[str]] = []

        def fake_run(command, **_kwargs):
            commands.append(list(command))
            if command == ["/opt/homebrew/bin/brew", "install", "node"]:
                return subprocess.CompletedProcess(command, 0, "", "")
            return next(versions)

        with patch(
            "yoke_cli.commands.qa_browser_lifecycle.sys.platform",
            "darwin",
        ), patch(
            "yoke_cli.commands.qa_browser_lifecycle.shutil.which",
            return_value="/opt/homebrew/bin/brew",
        ), patch(
            "yoke_cli.commands.qa_browser_lifecycle.subprocess.run",
            side_effect=fake_run,
        ):
            actions = _ensure_node_prerequisites()

        assert actions == [{"action": "install-node", "manager": "homebrew"}]
        assert ["/opt/homebrew/bin/brew", "install", "node"] in commands

    def test_node_prerequisite_check_names_manual_repair_off_macos(self):
        def missing(command, **_kwargs):
            return subprocess.CompletedProcess(command, 1, "", "")

        with patch(
            "yoke_cli.commands.qa_browser_lifecycle.sys.platform",
            "linux",
        ), patch(
            "yoke_cli.commands.qa_browser_lifecycle.subprocess.run",
            side_effect=missing,
        ):
            try:
                _ensure_node_prerequisites()
            except RuntimeError as exc:
                assert "Install them with your system package manager" in str(exc)
            else:
                raise AssertionError("expected manual prerequisite failure")

    def test_setup_dry_run_materializes_without_starting_daemon(self):
        with patch(
            "yoke_harness.browser_runtime_home.ensure_materialized",
            return_value=Path("/tmp/browser-runtime"),
        ) as materialize, patch(
            "yoke_cli.commands.qa_browser_lifecycle._browser_readiness",
            return_value={"daemon": {"status": "not_running"}},
        ), patch(
            "yoke_harness.browser_client.daemon_start",
        ) as daemon_start:
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                rc = qa_browser_setup(["--dry-run", "--json"])

        assert rc == 0
        materialize.assert_called_once_with()
        daemon_start.assert_not_called()
        payload = json.loads(out.getvalue())
        assert payload["ok"] is True
        assert payload["dry_run"] is True
        assert payload["runtime_dir"] == "/tmp/browser-runtime"
        assert payload["readiness"]["daemon"]["status"] == "not_running"

    def test_setup_dry_run_text_reports_daemon_status(self):
        with patch(
            "yoke_harness.browser_runtime_home.ensure_materialized",
            return_value=Path("/tmp/browser-runtime"),
        ), patch(
            "yoke_cli.commands.qa_browser_lifecycle._browser_readiness",
            return_value={"daemon": {"status": "not_running"}},
        ), patch("yoke_harness.browser_client.daemon_start") as daemon_start:
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                rc = qa_browser_setup(["--dry-run"])

        assert rc == 0
        daemon_start.assert_not_called()
        assert out.getvalue().strip() == "not_running"

    def test_setup_start_passes_daemon_options(self):
        with patch(
            "yoke_harness.browser_runtime_home.ensure_materialized",
            return_value=Path("/tmp/browser-runtime"),
        ), patch(
            "yoke_cli.commands.qa_browser_lifecycle._ensure_node_prerequisites",
            return_value=[{"action": "install-node", "manager": "homebrew"}],
        ), patch(
            "yoke_harness.browser_client.daemon_start",
            return_value={"status": "started", "pid": 123},
        ) as daemon_start:
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                rc = qa_browser_setup([
                    "--port", "9876", "--headed", "--idle-timeout", "60",
                    "--json",
                ])

        assert rc == 0
        daemon_start.assert_called_once_with(
            port=9876, headed=True, idle_timeout=60_000,
        )
        payload = json.loads(out.getvalue())
        assert payload["prerequisite_actions"] == [
            {"action": "install-node", "manager": "homebrew"}
        ]
        assert payload["daemon"]["status"] == "started"
