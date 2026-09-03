"""Tests for ``yoke qa browser`` setup/status lifecycle commands."""

from __future__ import annotations

import io
import json
import subprocess
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from yoke_cli.browser_node_toolchain import NodeToolchain, NodeToolchainError
from yoke_cli.commands.qa_browser_lifecycle import (
    _ensure_node_toolchain,
    qa_browser_setup,
    qa_browser_status,
)
from yoke_cli.commands.tool_shaped import resolve_tool_shaped


HOST_TOOLCHAIN = NodeToolchain(
    bin_dir=Path("/usr/local/bin"), version="v20.0.0", source="host_path"
)
MANAGED_TOOLCHAIN = NodeToolchain(
    bin_dir=Path("/machine/node/v24.20.0/bin"),
    version="v24.20.0",
    source="managed",
)


def _readiness_patches(runtime_dir: Path, *, toolchain, chromium_probe: str | None):
    """Patch the runtime home, daemon, toolchain, and Chromium probe."""

    def probe(command, **_kwargs):
        if chromium_probe is None:
            raise OSError(f"{command[0]} missing")
        return subprocess.CompletedProcess(command, 0, chromium_probe, "")

    return (
        patch(
            "yoke_harness.browser_runtime_home.runtime_dir", return_value=runtime_dir
        ),
        patch("yoke_harness.browser_runtime_home.source_hash", return_value="abc"),
        patch(
            "yoke_harness.browser_client.daemon_status",
            return_value={"status": "not_running"},
        ),
        patch(
            "yoke_cli.browser_node_toolchain.resolve_node_toolchain",
            return_value=toolchain,
        ),
        patch(
            "yoke_cli.commands.qa_browser_lifecycle.subprocess.run", side_effect=probe
        ),
    )


def _run_status(args: list[str], patches) -> tuple[int, str]:
    with ExitStack() as stack:
        for entry in patches:
            stack.enter_context(entry)
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            return qa_browser_status(args), out.getvalue()


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

        rc, text = _run_status(
            ["--json"],
            _readiness_patches(
                runtime_dir, toolchain=HOST_TOOLCHAIN, chromium_probe="ok"
            ),
        )

        assert rc == 0
        payload = json.loads(text)
        assert payload["runtime_dir"] == str(runtime_dir)
        assert payload["materialized"] is True
        assert payload["node"]["version"] == "v20.0.0"
        assert payload["node"]["source"] == "host_path"
        assert payload["npm_dependencies"]["status"] == "ready"
        assert payload["chromium"]["status"] == "ready"
        assert payload["daemon"] == {"status": "not_running"}
        assert payload["repairs"] == []

    def test_status_json_names_the_provisioned_toolchain(self, tmp_path):
        runtime_dir = tmp_path / "browser-runtime"
        runtime_dir.joinpath("node_modules", "playwright").mkdir(parents=True)
        runtime_dir.joinpath(".source-hash").write_text("abc\n", encoding="utf-8")

        rc, text = _run_status(
            ["--json"],
            _readiness_patches(
                runtime_dir, toolchain=MANAGED_TOOLCHAIN, chromium_probe="ok"
            ),
        )

        assert rc == 0
        payload = json.loads(text)
        assert payload["node"]["source"] == "managed"
        assert payload["node"]["bin_dir"] == str(MANAGED_TOOLCHAIN.bin_dir)

    def test_status_human_surfaces_readiness_facts_without_json(self, tmp_path):
        runtime_dir = tmp_path / "browser-runtime"
        runtime_dir.joinpath("node_modules", "playwright").mkdir(parents=True)
        runtime_dir.joinpath(".source-hash").write_text("abc\n", encoding="utf-8")

        rc, text = _run_status(
            [],
            _readiness_patches(
                runtime_dir, toolchain=HOST_TOOLCHAIN, chromium_probe="ok"
            ),
        )

        assert rc == 0
        # Readiness facts are visible without --json.
        assert str(runtime_dir) in text
        assert "node:" in text and "v20.0.0" in text and "[host_path]" in text
        assert "npm dependencies: ready" in text
        assert "chromium:         ready" in text
        assert "daemon:           not_running" in text
        # No repairs needed → repair guidance is omitted.
        assert "repairs:" not in text

    def test_status_human_surfaces_repair_guidance_when_missing(self, tmp_path):
        rc, text = _run_status(
            [],
            _readiness_patches(
                tmp_path / "browser-runtime", toolchain=None, chromium_probe=None
            ),
        )

        assert rc == 0
        assert "node:             missing" in text
        assert "npm dependencies: missing" in text
        assert "repairs:" in text
        assert "yoke qa browser setup" in text

    def test_status_json_names_repair_when_runtime_is_missing(self, tmp_path):
        rc, text = _run_status(
            ["--json"],
            _readiness_patches(
                tmp_path / "browser-runtime", toolchain=None, chromium_probe=None
            ),
        )

        assert rc == 0
        payload = json.loads(text)
        assert payload["node"]["status"] == "missing"
        assert payload["npm_dependencies"]["status"] == "missing"
        assert any("yoke qa browser setup" in hint for hint in payload["repairs"])


class TestSetupAdapter:
    def test_toolchain_step_reports_no_action_when_a_node_is_already_usable(self):
        with patch(
            "yoke_cli.browser_node_toolchain.resolve_node_toolchain",
            return_value=HOST_TOOLCHAIN,
        ), patch(
            "yoke_cli.browser_node_toolchain.provision_managed_toolchain"
        ) as provision:
            assert _ensure_node_toolchain(emit=lambda _line: None) == []
        provision.assert_not_called()

    def test_toolchain_step_provisions_node_when_the_host_has_none(self):
        with patch(
            "yoke_cli.browser_node_toolchain.resolve_node_toolchain",
            return_value=None,
        ), patch(
            "yoke_cli.browser_node_toolchain.provision_managed_toolchain",
            return_value=MANAGED_TOOLCHAIN,
        ) as provision:
            actions = _ensure_node_toolchain(emit=lambda _line: None)

        provision.assert_called_once()
        assert actions == [
            {
                "action": "provision-node",
                "source": "managed",
                "version": "v24.20.0",
                "bin_dir": str(MANAGED_TOOLCHAIN.bin_dir),
            }
        ]

    def test_setup_json_failure_names_the_code_and_recovery(self):
        refusal = NodeToolchainError(
            "no Node here.", code="node_download_failed", recovery="check the network"
        )
        with patch(
            "yoke_harness.browser_runtime_home.ensure_materialized",
            return_value=Path("/machine/browser-runtime"),
        ), patch(
            "yoke_cli.commands.qa_browser_lifecycle._ensure_node_toolchain",
            side_effect=refusal,
        ):
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                rc = qa_browser_setup(["--json"])

        assert rc == 2
        payload = json.loads(out.getvalue())
        assert payload["ok"] is False
        assert payload["error_code"] == "node_download_failed"
        assert payload["recovery"] == "check the network"
        assert "check the network" in payload["error"]

    def test_setup_dry_run_materializes_without_starting_daemon(self):
        with patch(
            "yoke_harness.browser_runtime_home.ensure_materialized",
            return_value=Path("/machine/browser-runtime"),
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
        assert payload["runtime_dir"] == "/machine/browser-runtime"
        assert payload["readiness"]["daemon"]["status"] == "not_running"

    def test_setup_dry_run_text_reports_daemon_status(self):
        with patch(
            "yoke_harness.browser_runtime_home.ensure_materialized",
            return_value=Path("/machine/browser-runtime"),
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
        provisioned = [
            {
                "action": "provision-node",
                "source": "managed",
                "version": "v24.20.0",
                "bin_dir": str(MANAGED_TOOLCHAIN.bin_dir),
            }
        ]
        with patch(
            "yoke_harness.browser_runtime_home.ensure_materialized",
            return_value=Path("/machine/browser-runtime"),
        ), patch(
            "yoke_cli.commands.qa_browser_lifecycle._ensure_node_toolchain",
            return_value=provisioned,
        ), patch(
            "yoke_cli.commands.qa_browser_lifecycle._browser_readiness",
            return_value={"daemon": {"status": "not_running"}},
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
            profile_dir=None, port=9876, headed=True, idle_timeout=60_000,
        )
        payload = json.loads(out.getvalue())
        assert payload["prerequisite_actions"] == provisioned
        assert payload["daemon"]["status"] == "started"
