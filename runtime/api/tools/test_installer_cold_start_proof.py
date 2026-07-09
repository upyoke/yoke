from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from yoke_core.tools import installer_cold_start_proof as proof
from yoke_core.tools import installer_cold_start_proof_cli as proof_cli
from yoke_core.tools import installer_cold_start_proof_core as proof_core


def test_linux_matrix_covers_endpoint_distro_and_arch() -> None:
    cells = proof.linux_proof_cells()

    assert len(cells) == 8
    assert {cell.endpoint for cell in cells} == {"prod", "stage"}
    assert {cell.distro for cell in cells} == {
        "amazon-linux-2023",
        "ubuntu-24.04",
    }
    assert {cell.aws_arch for cell in cells} == {"x86_64", "aarch64"}
    for cell in cells:
        # python tags are informational matrix dimensions; uv provisions the
        # managed interpreter, so there is no per-target wheelhouse selection.
        assert cell.targets == ("cp310", "cp311", "cp312", "cp313")
        assert cell.targets[-1].endswith("cp313")


def test_render_linux_probe_script_runs_installer_and_smokes_product() -> None:
    cell = proof.linux_proof_cells()[0]

    script = proof.render_linux_probe_script(cell)

    assert 'curl -fsSL "$INSTALL_BASE_URL/install"' in script
    assert 'YOKE_INSTALL_BASE_URL="$INSTALL_BASE_URL"' in script
    assert 'YOKE_CHANNEL="$CHANNEL"' in script
    assert 'YOKE_BIN=""' in script
    assert 'export PATH="$YOKE_DIR:$PATH"' in script
    # Smoke the product surface, including the new status check.
    assert "yoke --version" in script
    assert "yoke status --json" in script
    assert "YOKE_INSTALL_TEST_OK $LABEL" in script
    # Browser setup is NOT proven at install time.
    assert "qa browser" not in script
    # No raw secret markers leak into a generated script.
    assert "yoke_v1_" not in script
    assert "ghu_" not in script


def test_render_linux_probe_script_tolerates_first_run_status_nonzero() -> None:
    # A fresh, un-onboarded host's `yoke status --json` exits non-zero by
    # design; the probe must capture it without aborting `set -e`, while still
    # rejecting a genuinely broken install.
    cell = proof.linux_proof_cells()[0]

    script = proof.render_linux_probe_script(cell)

    # `set -eu` is the strict mode that the bug tripped on.
    assert "set -eu" in script
    # Status is captured with `|| true`, not run as a bare command that aborts.
    assert "yoke status --json >/tmp/yoke-status.json" in script
    assert "|| true" in script
    assert "yoke status --json >/tmp/yoke-status.json 2>/tmp/yoke-status.err || true" in script
    # The first-run allowlist is embedded so unexpected error codes still fail.
    for code in proof.FRESH_STATUS_ERROR_CODES:
        assert code in script
    assert "FRESH_STATUS_CODES=" in script
    # A genuinely broken install (empty output / unexpected code) still exits 1.
    assert "produced no output after install" in script
    assert "reported unexpected errors on a fresh install" in script


def test_render_linux_probe_script_resolves_installed_launcher_for_non_login_shell() -> None:
    # EC2 SSH proof commands execute in non-login shells, so they may not see
    # the launcher's directory on PATH even though the installer succeeded.
    cell = proof.linux_proof_cells()[0]

    script = proof.render_linux_probe_script(cell)

    assert 'if [ -n "${XDG_BIN_HOME:-}" ] && [ -x "${XDG_BIN_HOME}/yoke" ]' in script
    assert 'elif [ -n "$USER_HOME" ] && [ -x "$USER_HOME/.local/bin/yoke" ]' in script
    assert "elif [ -x /root/.local/bin/yoke ]" in script
    assert "elif command -v yoke >/dev/null 2>&1" in script
    assert 'echo "yoke command not found after install"' in script
    assert 'YOKE_DIR="$(dirname "$YOKE_BIN")"' in script
    assert 'export PATH="$YOKE_DIR:$PATH"' in script
    assert script.index('export PATH="$YOKE_DIR:$PATH"') < script.index("yoke --version")


def test_probe_first_run_allowlist_matches_public_installer() -> None:
    # The probe embeds the same fresh-install status allowlist the public
    # installer (`packaging/public-installer/install.py`) classifies with. The
    # shim cannot import yoke_core, so it keeps its own literal copy; this
    # guard fails if the two drift apart.
    installer_path = (
        Path(__file__).resolve().parents[3]
        / "packaging"
        / "public-installer"
        / "install.py"
    )
    spec = importlib.util.spec_from_file_location(
        "yoke_public_installer_for_proof_test", installer_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the shim's dataclass annotation resolution finds
    # its own module in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert set(proof.FRESH_STATUS_ERROR_CODES) == set(module.FRESH_STATUS_ERROR_CODES)
    assert proof.FRESH_STATUS_ERROR_CODES is proof_core.FRESH_STATUS_ERROR_CODES


def test_first_use_browser_script_defers_browser_to_first_use() -> None:
    script = proof.first_use_browser_script()

    assert "yoke qa browser setup" in script
    assert "yoke qa browser status" in script
    assert "YOKE_BROWSER_FIRST_USE_OK" in script


def test_prepare_evidence_dir_writes_manifest_scripts_and_browser_cell(
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "evidence"
    cell = proof.linux_proof_cells()[0]

    manifest = proof.prepare_evidence_dir(
        evidence_dir,
        run_id="e2e-test",
        commit_sha="abc123",
        cells=[cell],
    )

    assert manifest["run_id"] == "e2e-test"
    assert manifest["yoke_commit_sha"] == "abc123"
    assert evidence_dir.stat().st_mode & 0o077 == 0
    assert (evidence_dir / "scripts").stat().st_mode & 0o077 == 0
    manifest_path = evidence_dir / "acceptance-inputs.json"
    assert manifest_path.stat().st_mode & 0o077 == 0
    stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert stored["secret_marker_denies"] == list(proof.SECRET_MARKERS)
    assert proof.scan_log_file(manifest_path) == []
    [script_path] = stored["script_paths"]
    script = Path(script_path)
    assert script.is_file()
    assert script.stat().st_mode & 0o077 == 0
    assert "YOKE_INSTALL_TEST_OK" in script.read_text(encoding="utf-8")
    # The first-use browser cell is written alongside the installer cells.
    browser_script = Path(stored["first_use_browser_script"])
    assert browser_script.is_file()
    assert browser_script.stat().st_mode & 0o077 == 0
    assert "yoke qa browser setup" in browser_script.read_text(encoding="utf-8")


def test_scan_secret_markers_detects_raw_token_prefixes() -> None:
    assert proof.scan_secret_markers("clean log") == []
    assert proof.scan_secret_markers("oops yoke_v1_example") == ["yoke_v1_"]
    assert proof.scan_secret_markers("oops ghu_example") == ["ghu_"]


def test_scan_log_file_ignores_policy_field_but_not_other_json_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / "log.json"
    path.write_text(
        json.dumps(
            {
                "secret_marker_denies": list(proof.SECRET_MARKERS),
                "line": "clean",
            }
        ),
        encoding="utf-8",
    )
    assert proof.scan_log_file(path) == []

    path.write_text(
        json.dumps(
            {
                "secret_marker_denies": list(proof.SECRET_MARKERS),
                "line": "leaked yoke_v1_example",
            }
        ),
        encoding="utf-8",
    )
    assert proof.scan_log_file(path) == ["yoke_v1_"]


def test_matrix_command_lists_every_cell() -> None:
    parser = proof.build_parser()
    args = parser.parse_args(["matrix"])
    assert args.command == "matrix"
    text = proof_cli._matrix_text()
    assert text.count("\n") == len(proof.linux_proof_cells()) - 1
    assert "prod-amazon-linux-2023-x86_64" in text


def test_aws_preflight_help_names_local_postgres_env() -> None:
    help_text = proof.build_parser().format_help()

    assert "aws-preflight" in help_text
    assert "local-postgres" in help_text
    assert "prod-db-admin" in help_text


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def run(self, argv, *, env=None, timeout=60):  # noqa: ANN001, ANN201
        self.calls.append((list(argv), dict(env or {})))
        if argv == ["aws", "--version"]:
            return proof.CommandResult(0, "aws-cli/2.0\n", "")
        return proof.CommandResult(
            0,
            json.dumps(
                {
                    "Account": "123456789012",
                    "Arn": "arn:aws:iam::123456789012:user/proof",
                    "UserId": "AIDAEXAMPLE",
                }
            ),
            "",
        )


def test_aws_identity_preflight_uses_capability_env_without_reporting_secret(
    monkeypatch,
) -> None:
    def fake_aws_env(project: str, region: str) -> dict[str, str]:
        assert project == "yoke"
        assert region == "us-east-1"
        return {
            "AWS_ACCESS_KEY_ID": "AKIA_SECRET",
            "AWS_SECRET_ACCESS_KEY": "SECRET_VALUE",
            "AWS_DEFAULT_REGION": region,
        }

    monkeypatch.setattr(proof_core, "aws_capability_env", fake_aws_env)
    runner = FakeRunner()

    report = proof.aws_identity_preflight(runner=runner)

    assert report["ok"] is True
    assert report["account"] == "123456789012"
    rendered = json.dumps(report)
    assert "AKIA_SECRET" not in rendered
    assert "SECRET_VALUE" not in rendered
    assert runner.calls[0][0] == ["aws", "--version"]
    assert runner.calls[1][0] == [
        "aws",
        "sts",
        "get-caller-identity",
        "--output",
        "json",
    ]
    assert runner.calls[0][1]["AWS_ACCESS_KEY_ID"] == "AKIA_SECRET"
