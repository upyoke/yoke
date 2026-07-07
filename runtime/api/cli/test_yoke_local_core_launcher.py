from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

from yoke_cli import main as yoke_cli_main
from yoke_cli import operation_inventory as op_inventory
from yoke_cli import product_boundary_inventory as boundary_inventory
from yoke_cli.local_core.launcher import LocalCoreLauncher
from yoke_cli.local_core.runner import CommandResult


REPO_ROOT = Path(__file__).resolve().parents[3]
TOKEN = "yoke-test-token"


class FakeRunner:
    def __init__(self, *, docker_rc: int = 0) -> None:
        self.docker_rc = docker_rc
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: int = 30,
    ) -> CommandResult:
        cmd = tuple(str(part) for part in args)
        self.calls.append(cmd)
        if cmd[:3] == ("docker", "version", "--format"):
            if self.docker_rc == 127:
                return CommandResult(cmd, 127, "", "docker missing")
            return CommandResult(cmd, self.docker_rc, "26.0.0\n", "")
        if cmd[:2] == ("docker", "inspect"):
            if self.docker_rc != 0:
                return CommandResult(cmd, self.docker_rc, "", "docker missing")
            return CommandResult(cmd, 0, "true healthy\n", "")
        if "yoke_core.domain.api_tokens_cli" in cmd:
            return CommandResult(cmd, 0, json.dumps({"raw_token": TOKEN}), "")
        return CommandResult(cmd, 0, "", "")


def test_top_level_help_lists_core_commands(capsys) -> None:
    rc = yoke_cli_main.main(["--help"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "yoke core build" in out
    assert "yoke core status" in out
    assert "client-local helper (no function id)" in out


def test_operation_inventory_marks_core_launcher_as_permanent_tool_shaped() -> None:
    for verb in ("build", "start", "status", "logs", "stop", "upgrade"):
        entry = op_inventory.lookup(f"yoke core {verb}")
        assert entry is not None
        assert entry.status == op_inventory.PERMANENT
        assert entry.reason == op_inventory.REASON_TOOL_SHAPED


def test_product_boundary_inventory_keeps_core_launcher_product_side() -> None:
    rows = {
        row.command_helper: row
        for row in boundary_inventory.generate_inventory(repo_root=REPO_ROOT)
    }

    row = rows["yoke core status"]
    assert row.disposition == boundary_inventory.PRODUCT_CLIENT
    assert row.function_id is None
    assert row.import_edges == ()
    assert "no yoke-core import" in row.expected_refusal_shape


def test_local_core_workflow_has_no_public_image_publication() -> None:
    workflow = REPO_ROOT / ".github" / "workflows" / "yoke-core-image.yml"
    body = workflow.read_text(encoding="utf-8")

    assert "ghcr.io/upyoke/yoke-core" not in body
    assert "packages: write" not in body
    assert "publish-ghcr" not in body
    assert "Build and push public local-core image" not in body
    assert "ECR_REPOSITORY: yoke-core" in body


def test_status_json_reports_missing_runtime_and_machine_state(tmp_path: Path) -> None:
    launcher = LocalCoreLauncher(
        runner=FakeRunner(docker_rc=127),
        machine_home=str(tmp_path / "machine-home"),
        system="linux",
    )

    payload = launcher.status()

    assert payload["ok"] is False
    assert payload["installed"] is False
    assert payload["running"] is False
    assert payload["api"]["url"] == "http://127.0.0.1:8765"
    assert payload["runtime"]["docker"]["status"] == "missing"
    assert payload["state_dir"] == str(tmp_path / "machine-home" / "local-core")
    assert _issue_codes(payload) >= {"docker_missing", "local_core_not_installed"}


def test_build_dry_run_plans_without_writing_machine_state(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "yoke_cli.local_core.docker_plan.port_free", lambda _port: True
    )
    machine_home = tmp_path / "machine-home"
    launcher = LocalCoreLauncher(
        runner=FakeRunner(),
        machine_home=str(machine_home),
        system="linux",
    )

    payload = launcher.build(
        checkout_path=str(REPO_ROOT),
        image="example/yoke-core:test",
        api_port=19001,
        postgres_port=19032,
        dry_run=True,
    )

    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert [
        "docker", "build",
        "--build-arg", "YOKE_BUILD_SHA=local",
        "-t", "example/yoke-core:test",
        str(REPO_ROOT),
    ] in payload["plan"]
    assert not any(cmd[:2] == ["docker", "pull"] for cmd in payload["plan"])
    assert not (machine_home / "local-core" / "state.json").exists()


def test_start_builds_from_checkout_and_writes_config_without_leaking_token(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "yoke_cli.local_core.docker_plan.port_free", lambda _port: True
    )
    machine_home = tmp_path / "machine-home"
    config_path = machine_home / "config.json"
    launcher = LocalCoreLauncher(
        runner=FakeRunner(),
        machine_home=str(machine_home),
        system="linux",
    )

    payload = launcher.start(
        from_checkout=str(REPO_ROOT),
        image="example/yoke-core:test",
        build=True,
        api_port=19001,
        postgres_port=19032,
        config_path=str(config_path),
    )

    assert payload["ok"] is True
    assert payload["installed"] is True
    assert TOKEN not in json.dumps(payload)
    state_path = machine_home / "local-core" / "state.json"
    assert state_path.is_file()
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["api_url"] == "http://127.0.0.1:19001"
    assert state_payload["image"] == "example/yoke-core:test"

    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    connection = config_payload["connections"]["local-core"]
    assert connection["transport"] == "https"
    assert connection["api_url"] == "http://127.0.0.1:19001"
    assert connection["prod"] is False
    secret_path = Path(connection["credential_source"]["path"])
    assert secret_path == machine_home / "secrets" / "local-core.token"
    assert secret_path.read_text(encoding="utf-8") == TOKEN + "\n"
    assert TOKEN not in config_path.read_text(encoding="utf-8")


def test_start_requires_explicit_image_or_checkout_build(tmp_path: Path) -> None:
    launcher = LocalCoreLauncher(
        runner=FakeRunner(),
        machine_home=str(tmp_path / "machine-home"),
        system="linux",
    )

    payload = launcher.start(dry_run=True)

    assert payload["ok"] is False
    assert payload["image"] is None
    assert payload["plan"] == []
    assert "local_core_image_required" in _issue_codes(payload)
    assert not any("ghcr.io" in " ".join(cmd) for cmd in payload["plan"])


def _issue_codes(payload: dict[str, object]) -> set[str]:
    return {
        str(issue.get("code") or "")
        for issue in payload.get("issues") or []
        if isinstance(issue, dict)
    }
