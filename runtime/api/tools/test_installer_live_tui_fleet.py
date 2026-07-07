from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import json_helper
from yoke_core.tools import installer_live_tui_fleet as fleet


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def run(self, argv, *, env=None, timeout=600):  # noqa: ANN001, ANN201
        del timeout
        args = list(argv)
        self.calls.append((args, dict(env or {})))
        if args[:4] == ["aws", "ssm", "get-parameter", "--name"]:
            return fleet.CommandResult(0, "ami-123\n", "")
        if args[:3] == ["aws", "ec2", "describe-vpcs"]:
            return fleet.CommandResult(0, "vpc-123\n", "")
        if args[:3] == ["aws", "ec2", "describe-subnets"]:
            return fleet.CommandResult(0, "subnet-123\n", "")
        if args[:3] == ["aws", "ec2", "create-key-pair"]:
            return fleet.CommandResult(0, "PRIVATE_KEY_MATERIAL\n", "")
        if args[:3] == ["aws", "ec2", "create-security-group"]:
            return fleet.CommandResult(0, "sg-123\n", "")
        if args[:3] == ["aws", "ec2", "run-instances"]:
            return fleet.CommandResult(0, "i-123\n", "")
        if args[:3] == ["aws", "ec2", "describe-instances"]:
            return fleet.CommandResult(0, "203.0.113.10\n", "")
        if args and args[0] == "aws":
            return fleet.CommandResult(0, "", "")
        if args and args[0] == "scp":
            return fleet.CommandResult(0, "", "")
        if args and args[0] == "ssh":
            return fleet.CommandResult(0, "", "")
        raise AssertionError(f"unexpected argv: {args}")


def test_build_fleet_plan_is_dry_run_shape(tmp_path: Path) -> None:
    plan = fleet.build_fleet_plan(
        campaign_id="campaign-20260704-001",
        campaign_root=tmp_path,
        count=3,
        profile="prepared-git",
    )

    assert plan["execute_required"] is True
    assert plan["count"] == 3
    assert plan["profile"] == "prepared-git"
    assert plan["purpose_tag"] == fleet.PURPOSE_TAG


def test_build_fleet_plan_supports_ubuntu_2404(tmp_path: Path) -> None:
    plan = fleet.build_fleet_plan(
        campaign_id="campaign-20260704-001",
        campaign_root=tmp_path,
        count=1,
        profile="bare-no-uv",
        distro="ubuntu-24.04",
    )

    assert plan["distro"] == "ubuntu-24.04"
    assert plan["ssh_user"] == "ubuntu"
    assert plan["ami_parameter"] == fleet.UBUNTU_2404_AMI_PARAMS["x86_64"]


def test_prepare_fleet_uses_capability_env_and_writes_secret_key_elsewhere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_env(project: str, region: str) -> dict[str, str]:
        assert project == "yoke"
        assert region == "us-east-1"
        return {
            "AWS_ACCESS_KEY_ID": "AKIA_SECRET",
            "AWS_SECRET_ACCESS_KEY": "SECRET_VALUE",
        }

    monkeypatch.setattr(fleet, "aws_capability_env", fake_env)
    runner = FakeRunner()

    result = fleet.prepare_fleet(
        campaign_id="campaign-20260704-001",
        campaign_root=tmp_path / "campaign",
        count=1,
        profile="prepared-git",
        key_dir=tmp_path / "keys",
        runner=runner,
        public_ip_fetcher=lambda: "198.51.100.20",
    )

    ledger = result["ledger"]
    rendered = json.dumps(ledger)
    assert result["ok"] is True
    assert "PRIVATE_KEY_MATERIAL" not in rendered
    assert "AKIA_SECRET" not in rendered
    assert "SECRET_VALUE" not in rendered
    key_path = Path(str(ledger["key_path"]))
    assert key_path.read_text(encoding="utf-8") == "PRIVATE_KEY_MATERIAL\n"
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert ledger["hosts"][0]["key_path"] == str(key_path)
    assert (tmp_path / "campaign" / "host-ledger.json").is_file()
    aws_calls = [call for call, _env in runner.calls if call and call[0] == "aws"]
    assert any("run-instances" in call for call in aws_calls)
    ssh_commands = [call[-1] for call, _env in runner.calls if call and call[0] == "ssh"]
    assert any("sudo dnf install" in command for command in ssh_commands)
    assert any("command -v curl" in command for command in ssh_commands)
    assert all("dnf install -y tmux curl" not in command for command in ssh_commands)
    assert all("/tmp/yoke-bootstrap.log" not in command for command in ssh_commands)
    assert any("YOKE_NO_ONBOARD=1" in command for command in ssh_commands)


def test_prepare_fleet_bootstraps_ubuntu_with_apt_and_ubuntu_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fleet,
        "aws_capability_env",
        lambda _project, _region: {"AWS_ACCESS_KEY_ID": "AKIA_SECRET"},
    )
    runner = FakeRunner()

    result = fleet.prepare_fleet(
        campaign_id="campaign-20260704-001",
        campaign_root=tmp_path / "campaign",
        count=1,
        profile="prepared-git",
        distro="ubuntu-24.04",
        key_dir=tmp_path / "keys",
        runner=runner,
        public_ip_fetcher=lambda: "198.51.100.20",
    )

    ledger = result["ledger"]
    assert ledger["ssh_user"] == "ubuntu"
    assert ledger["hosts"][0]["ssh_user"] == "ubuntu"
    ssh_calls = [call for call, _env in runner.calls if call and call[0] == "ssh"]
    assert any("ubuntu@203.0.113.10" in call for call in ssh_calls)
    ssh_commands = [call[-1] for call in ssh_calls]
    assert any("sudo apt-get update" in command for command in ssh_commands)
    assert any("apt-get install -y tmux git $curl_pkg" in command for command in ssh_commands)
    assert all("sudo dnf install" not in command for command in ssh_commands)


def test_prepare_path_broken_profile_removes_startup_files_after_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fleet,
        "aws_capability_env",
        lambda _project, _region: {"AWS_ACCESS_KEY_ID": "AKIA_SECRET"},
    )
    runner = FakeRunner()

    result = fleet.prepare_fleet(
        campaign_id="campaign-20260704-001",
        campaign_root=tmp_path / "campaign",
        count=1,
        profile="prepared-path-broken",
        key_dir=tmp_path / "keys",
        runner=runner,
        public_ip_fetcher=lambda: "198.51.100.20",
    )

    assert result["ledger"]["hosts"][0]["profile"] == "prepared-path-broken"
    ssh_commands = [call[-1] for call, _env in runner.calls if call and call[0] == "ssh"]
    assert any("YOKE_NO_ONBOARD=1" in command for command in ssh_commands)
    path_break_command = ssh_commands[-1]
    assert "$HOME/.zprofile" in path_break_command
    assert "$HOME/.zshenv" in path_break_command
    assert 'test -x "$HOME/.local/bin/yoke"' in path_break_command


def test_prepare_screen_term_profile_records_terminal_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fleet,
        "aws_capability_env",
        lambda _project, _region: {"AWS_ACCESS_KEY_ID": "AKIA_SECRET"},
    )
    runner = FakeRunner()

    result = fleet.prepare_fleet(
        campaign_id="campaign-20260704-001",
        campaign_root=tmp_path / "campaign",
        count=1,
        profile="prepared-screen-term",
        key_dir=tmp_path / "keys",
        runner=runner,
        public_ip_fetcher=lambda: "198.51.100.20",
    )

    host = result["ledger"]["hosts"][0]
    assert host["profile"] == "prepared-screen-term"
    assert host["terminal_profile"] == "screen-256color"
    ssh_commands = [call[-1] for call, _env in runner.calls if call and call[0] == "ssh"]
    assert any("YOKE_NO_ONBOARD=1" in command for command in ssh_commands)


def test_prepare_fault_injection_profile_installs_yoke_and_records_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fleet,
        "aws_capability_env",
        lambda _project, _region: {"AWS_ACCESS_KEY_ID": "AKIA_SECRET"},
    )
    runner = FakeRunner()

    result = fleet.prepare_fleet(
        campaign_id="campaign-20260704-001",
        campaign_root=tmp_path / "campaign",
        count=1,
        profile="fault-injection",
        key_dir=tmp_path / "keys",
        runner=runner,
        public_ip_fetcher=lambda: "198.51.100.20",
    )

    host = result["ledger"]["hosts"][0]
    assert host["profile"] == "fault-injection"
    assert host["fault_injection"] is True
    ssh_commands = [call[-1] for call, _env in runner.calls if call and call[0] == "ssh"]
    assert any("YOKE_NO_ONBOARD=1" in command for command in ssh_commands)


def test_prepare_bare_no_curl_profile_hides_curl_without_installing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fleet,
        "aws_capability_env",
        lambda _project, _region: {"AWS_ACCESS_KEY_ID": "AKIA_SECRET"},
    )
    runner = FakeRunner()

    result = fleet.prepare_fleet(
        campaign_id="campaign-20260704-001",
        campaign_root=tmp_path / "campaign",
        count=1,
        profile="bare-no-curl",
        distro="ubuntu-24.04",
        key_dir=tmp_path / "keys",
        runner=runner,
        public_ip_fetcher=lambda: "198.51.100.20",
    )

    assert result["ledger"]["hosts"][0]["profile"] == "bare-no-curl"
    ssh_commands = [call[-1] for call, _env in runner.calls if call and call[0] == "ssh"]
    package_command = next(command for command in ssh_commands if "apt-get install" in command)
    assert "curl_pkg" not in package_command
    assert " apt-get install -y tmux" in package_command
    assert all("YOKE_NO_ONBOARD=1" not in command for command in ssh_commands)
    disable_command = ssh_commands[-1]
    assert '"$curl_path.yoke-hidden"' in disable_command
    assert "! command -v curl" in disable_command


def test_prepare_stored_state_profile_preloads_machine_config_without_secret_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fleet,
        "aws_capability_env",
        lambda _project, _region: {"AWS_ACCESS_KEY_ID": "AKIA_SECRET"},
    )
    yoke_token = tmp_path / "stage.token"
    github_token = tmp_path / "github.token"
    yoke_token.write_text("yoke-secret-value\n", encoding="utf-8")
    github_token.write_text("github-secret-value\n", encoding="utf-8")
    runner = FakeRunner()

    result = fleet.prepare_fleet(
        campaign_id="campaign-20260704-001",
        campaign_root=tmp_path / "campaign",
        count=1,
        profile="prepared-stored-state",
        endpoint="stage",
        distro="ubuntu-24.04",
        key_dir=tmp_path / "keys",
        yoke_token_file=yoke_token,
        github_token_file=github_token,
        github_repo="example-org/buzz",
        runner=runner,
        public_ip_fetcher=lambda: "198.51.100.20",
    )

    rendered_ledger = json.dumps(result["ledger"])
    assert "yoke-secret-value" not in rendered_ledger
    assert "github-secret-value" not in rendered_ledger
    host = result["ledger"]["hosts"][0]
    assert host["profile"] == "prepared-stored-state"
    assert host["stored_state"] == {
        "yoke_connection": True,
        "github_connection": True,
        "github_repo": "example-org/buzz",
    }
    scp_targets = [call[-1] for call, _env in runner.calls if call and call[0] == "scp"]
    assert "ubuntu@203.0.113.10:/tmp/yoke-api.token" in scp_targets
    assert "ubuntu@203.0.113.10:/tmp/yoke-github.token" in scp_targets
    ssh_commands = [call[-1] for call, _env in runner.calls if call and call[0] == "ssh"]
    assert any(
        "apt-get install -y tmux git $curl_pkg" in command
        for command in ssh_commands
    )
    stored_state_command = ssh_commands[-1]
    assert "connection set stage --transport https" in stored_state_command
    assert "--token-file /tmp/yoke-api.token" in stored_state_command
    assert "github connect --token-file /tmp/yoke-github.token" in stored_state_command
    assert "--github-repo example-org/buzz" in stored_state_command
    assert "rm -f /tmp/yoke-api.token" in stored_state_command
    assert "rm -f /tmp/yoke-github.token" in stored_state_command
    assert "yoke-secret-value" not in stored_state_command
    assert "github-secret-value" not in stored_state_command


def test_prepare_stored_state_profile_requires_yoke_token_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires --yoke-token-file"):
        fleet.prepare_fleet(
            campaign_id="campaign-20260704-001",
            campaign_root=tmp_path / "campaign",
            count=1,
            profile="prepared-stored-state",
            key_dir=tmp_path / "keys",
            runner=FakeRunner(),
            public_ip_fetcher=lambda: "198.51.100.20",
        )


def test_prepare_no_git_no_sudo_profile_hides_auto_install_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fleet,
        "aws_capability_env",
        lambda _project, _region: {"AWS_ACCESS_KEY_ID": "AKIA_SECRET"},
    )
    runner = FakeRunner()

    result = fleet.prepare_fleet(
        campaign_id="campaign-20260704-001",
        campaign_root=tmp_path / "campaign",
        count=1,
        profile="prepared-no-git-no-sudo",
        distro="ubuntu-24.04",
        key_dir=tmp_path / "keys",
        runner=runner,
        public_ip_fetcher=lambda: "198.51.100.20",
    )

    host = result["ledger"]["hosts"][0]
    assert host["profile"] == "prepared-no-git-no-sudo"
    assert host["package_install"] == {"git": "missing", "sudo": "missing"}
    ssh_commands = [call[-1] for call, _env in runner.calls if call and call[0] == "ssh"]
    package_command = next(command for command in ssh_commands if "apt-get install" in command)
    assert "git" not in package_command
    assert any("YOKE_NO_ONBOARD=1" in command for command in ssh_commands)
    no_auto_install_command = ssh_commands[-1]
    assert 'git_path="$(command -v git || true)"' in no_auto_install_command
    assert 'sudo_path="$(command -v sudo || true)"' in no_auto_install_command
    assert '"$sudo_path.yoke-hidden"' in no_auto_install_command
    assert "hash -r" in no_auto_install_command
    assert '[ -z "$sudo_path" ] || [ ! -e "$sudo_path" ]' in no_auto_install_command
    assert "! command -v git" in no_auto_install_command
    assert "! command -v sudo" in no_auto_install_command


def test_prepare_no_git_profile_removes_git_but_keeps_sudo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fleet,
        "aws_capability_env",
        lambda _project, _region: {"AWS_ACCESS_KEY_ID": "AKIA_SECRET"},
    )
    runner = FakeRunner()

    result = fleet.prepare_fleet(
        campaign_id="campaign-20260704-001",
        campaign_root=tmp_path / "campaign",
        count=1,
        profile="prepared-no-git",
        key_dir=tmp_path / "keys",
        runner=runner,
        public_ip_fetcher=lambda: "198.51.100.20",
    )

    host = result["ledger"]["hosts"][0]
    assert host["profile"] == "prepared-no-git"
    assert host["package_install"] == {"git": "missing", "sudo": "available"}
    ssh_commands = [call[-1] for call, _env in runner.calls if call and call[0] == "ssh"]
    package_command = next(command for command in ssh_commands if "dnf install" in command)
    assert "git" not in package_command
    no_git_command = ssh_commands[-1]
    assert "sudo dnf remove -y git git-core git-core-doc" in no_git_command
    assert "! command -v git" in no_git_command
    assert "command -v sudo" in no_git_command


def test_remote_failure_reports_stdout_and_stderr_tail() -> None:
    class FailingRunner:
        def run(self, argv, *, env=None, timeout=600):  # noqa: ANN001, ANN201
            del argv, env, timeout
            return fleet.CommandResult(
                1,
                "No match for argument: tmux\n",
                "Warning: Permanently added host\n",
            )

    with pytest.raises(RuntimeError) as excinfo:
        fleet._run_ssh(  # noqa: SLF001
            FailingRunner(),
            Path("/tmp/key.pem"),
            "203.0.113.10",
            "sudo dnf install -y tmux",
            timeout=1,
        )

    message = str(excinfo.value)
    assert "Warning: Permanently added host" in message
    assert "No match for argument: tmux" in message


def test_cleanup_fleet_deletes_resources_and_key_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fleet,
        "aws_capability_env",
        lambda _project, _region: {"AWS_ACCESS_KEY_ID": "AKIA_SECRET"},
    )
    key_path = tmp_path / "keys" / "host.pem"
    key_path.parent.mkdir()
    key_path.write_text("PRIVATE_KEY\n", encoding="utf-8")
    ledger_path = tmp_path / "host-ledger.json"
    json_helper.dump_path(
        ledger_path,
        {
            "key_name": "key-123",
            "key_path": str(key_path),
            "security_group_id": "sg-123",
            "hosts": [{"instance_id": "i-123"}],
        },
    )
    runner = FakeRunner()

    result = fleet.cleanup_fleet(ledger_path=ledger_path, runner=runner)

    assert result["ok"] is True
    assert not key_path.exists()
    aws_calls = [call for call, _env in runner.calls if call and call[0] == "aws"]
    assert any("terminate-instances" in call for call in aws_calls)
    assert any("delete-security-group" in call for call in aws_calls)
    assert any("delete-key-pair" in call for call in aws_calls)


def test_reset_fleet_host_removes_user_local_yoke_state(tmp_path: Path) -> None:
    key_path = tmp_path / "host.pem"
    key_path.write_text("PRIVATE_KEY\n", encoding="utf-8")
    ledger_path = tmp_path / "host-ledger.json"
    json_helper.dump_path(
        ledger_path,
        {
            "key_path": str(key_path),
            "hosts": [
                {
                    "host_id": "tui-linux-001",
                    "instance_id": "i-123",
                    "public_ip": "203.0.113.10",
                }
            ],
        },
    )
    runner = FakeRunner()

    result = fleet.reset_fleet_host(
        ledger_path=ledger_path,
        host_id="tui-linux-001",
        target_profile="bare-no-uv",
        runner=runner,
    )

    assert result["ok"] is True
    ssh_commands = [call[-1] for call, _env in runner.calls if call and call[0] == "ssh"]
    reset_command = ssh_commands[0]
    assert "pkill -TERM" in reset_command
    assert "'[y]oke.*onboard'" in reset_command
    assert "tmux kill-server" in reset_command
    assert "$HOME/.local/bin/yoke" in reset_command
    assert "$HOME/.local/bin/uv" in reset_command
    assert "$HOME/.local/share/uv" in reset_command
    assert "/tmp/yoke-stored-stage-token.backup" in reset_command
    assert any("dnf install -y tmux" in command for command in ssh_commands)
    updated = json_helper.load_path(ledger_path)
    assert updated["hosts"][0]["profile"] == "bare-no-uv"


def test_reset_fleet_host_uses_ledger_ssh_user(tmp_path: Path) -> None:
    key_path = tmp_path / "host.pem"
    key_path.write_text("PRIVATE_KEY\n", encoding="utf-8")
    ledger_path = tmp_path / "host-ledger.json"
    json_helper.dump_path(
        ledger_path,
        {
            "key_path": str(key_path),
            "hosts": [
                {
                    "host_id": "tui-linux-001",
                    "instance_id": "i-123",
                    "public_ip": "203.0.113.10",
                    "ssh_user": "ubuntu",
                }
            ],
        },
    )
    runner = FakeRunner()

    result = fleet.reset_fleet_host(
        ledger_path=ledger_path,
        host_id="tui-linux-001",
        target_profile="bare-no-uv",
        runner=runner,
    )

    assert result["ok"] is True
    ssh_calls = [call for call, _env in runner.calls if call and call[0] == "ssh"]
    assert "ubuntu@203.0.113.10" in ssh_calls[0]


def test_reset_fleet_host_prefers_host_key_path(tmp_path: Path) -> None:
    root_key = tmp_path / "root.pem"
    root_key.write_text("ROOT_KEY\n", encoding="utf-8")
    host_key = tmp_path / "host.pem"
    host_key.write_text("HOST_KEY\n", encoding="utf-8")
    ledger_path = tmp_path / "host-ledger.json"
    json_helper.dump_path(
        ledger_path,
        {
            "key_path": str(root_key),
            "hosts": [
                {
                    "host_id": "tui-linux-001",
                    "instance_id": "i-123",
                    "key_path": str(host_key),
                    "public_ip": "203.0.113.10",
                }
            ],
        },
    )
    runner = FakeRunner()

    result = fleet.reset_fleet_host(
        ledger_path=ledger_path,
        host_id="tui-linux-001",
        target_profile="bare-no-uv",
        runner=runner,
    )

    assert result["ok"] is True
    ssh_calls = [call for call, _env in runner.calls if call and call[0] == "ssh"]
    assert ssh_calls[0][:3] == ["ssh", "-i", str(host_key)]


def test_reset_fleet_host_rebuilds_prepared_path_profile_and_updates_ledger(
    tmp_path: Path,
) -> None:
    ledger_path = _write_reset_ledger(
        tmp_path,
        profile="prepared-yoke",
        distro="ubuntu-24.04",
        stale_metadata={"terminal_profile": "screen-256color"},
    )
    runner = FakeRunner()

    result = fleet.reset_fleet_host(
        ledger_path=ledger_path,
        host_id="tui-linux-001",
        target_profile="prepared-path-broken",
        runner=runner,
    )

    assert result["ok"] is True
    ssh_commands = [call[-1] for call, _env in runner.calls if call and call[0] == "ssh"]
    assert "tmux kill-server" in ssh_commands[0]
    assert any("sudo apt-get update" in command for command in ssh_commands)
    assert any("YOKE_NO_ONBOARD=1" in command for command in ssh_commands)
    assert 'test -x "$HOME/.local/bin/yoke"' in ssh_commands[-1]
    updated = json_helper.load_path(ledger_path)
    host = updated["hosts"][0]
    assert host["profile"] == "prepared-path-broken"
    assert host["endpoint"] == "stage"
    assert host["lease_state"] == "available"
    assert "terminal_profile" not in host


def test_reset_fleet_host_records_screen_term_metadata(tmp_path: Path) -> None:
    ledger_path = _write_reset_ledger(tmp_path, profile="prepared-yoke")
    runner = FakeRunner()

    result = fleet.reset_fleet_host(
        ledger_path=ledger_path,
        host_id="tui-linux-001",
        target_profile="prepared-screen-term",
        runner=runner,
    )

    assert result["ok"] is True
    updated = json_helper.load_path(ledger_path)
    host = updated["hosts"][0]
    assert host["profile"] == "prepared-screen-term"
    assert host["terminal_profile"] == "screen-256color"


def test_reset_fleet_host_rebuilds_prepared_no_git_profile(tmp_path: Path) -> None:
    ledger_path = _write_reset_ledger(
        tmp_path,
        profile="prepared-git",
        stale_metadata={"terminal_profile": "screen-256color"},
    )
    runner = FakeRunner()

    result = fleet.reset_fleet_host(
        ledger_path=ledger_path,
        host_id="tui-linux-001",
        target_profile="prepared-no-git",
        runner=runner,
    )

    assert result["ok"] is True
    ssh_commands = [call[-1] for call, _env in runner.calls if call and call[0] == "ssh"]
    no_git_command = ssh_commands[-1]
    assert "sudo dnf remove -y git git-core git-core-doc" in no_git_command
    assert "! command -v git" in no_git_command
    assert "command -v sudo" in no_git_command
    updated = json_helper.load_path(ledger_path)
    host = updated["hosts"][0]
    assert host["profile"] == "prepared-no-git"
    assert host["package_install"] == {"git": "missing", "sudo": "available"}
    assert "terminal_profile" not in host


def test_reset_fleet_host_reseeds_prepared_stored_state(tmp_path: Path) -> None:
    yoke_token = tmp_path / "stage.token"
    github_token = tmp_path / "github.token"
    yoke_token.write_text("yoke-secret-value\n", encoding="utf-8")
    github_token.write_text("github-secret-value\n", encoding="utf-8")
    ledger_path = _write_reset_ledger(
        tmp_path,
        profile="prepared-stored-state",
        stale_metadata={
            "terminal_profile": "screen-256color",
            "stored_state": {
                "yoke_connection": True,
                "github_connection": True,
                "github_repo": "example-org/buzz",
            },
        },
    )
    runner = FakeRunner()

    result = fleet.reset_fleet_host(
        ledger_path=ledger_path,
        host_id="tui-linux-001",
        target_profile="prepared-stored-state",
        yoke_token_file=yoke_token,
        github_token_file=github_token,
        runner=runner,
    )

    assert result["ok"] is True
    scp_calls = [call for call, _env in runner.calls if call and call[0] == "scp"]
    assert any(
        str(yoke_token) in call
        and "ubuntu@203.0.113.10:/tmp/yoke-api.token" in call
        for call in scp_calls
    )
    assert any(
        str(github_token) in call
        and "ubuntu@203.0.113.10:/tmp/yoke-github.token" in call
        for call in scp_calls
    )
    ssh_commands = [call[-1] for call, _env in runner.calls if call and call[0] == "ssh"]
    assert any("dnf install -y tmux git" in command for command in ssh_commands)
    assert any("connection set stage --transport https" in command for command in ssh_commands)
    assert any("--token-file /tmp/yoke-api.token" in command for command in ssh_commands)
    assert any(
        "github connect --token-file /tmp/yoke-github.token" in command
        for command in ssh_commands
    )
    updated = json_helper.load_path(ledger_path)
    rendered = json.dumps(updated)
    host = updated["hosts"][0]
    assert host["profile"] == "prepared-stored-state"
    assert host["stored_state"] == {
        "yoke_connection": True,
        "github_connection": True,
        "github_repo": "example-org/buzz",
    }
    assert "terminal_profile" not in host
    assert "yoke-secret-value" not in rendered
    assert "github-secret-value" not in rendered


def test_reset_fleet_host_rejects_unrestorable_profiles(tmp_path: Path) -> None:
    ledger_path = _write_reset_ledger(tmp_path, profile="prepared-yoke")

    with pytest.raises(ValueError, match="unsupported reset profile"):
        fleet.reset_fleet_host(
            ledger_path=ledger_path,
            host_id="tui-linux-001",
            target_profile="prepared-no-git-no-sudo",
            runner=FakeRunner(),
        )


def _write_reset_ledger(
    tmp_path: Path,
    *,
    profile: str,
    distro: str = "amazon-linux-2023",
    stale_metadata: dict[str, object] | None = None,
) -> Path:
    key_path = tmp_path / "host.pem"
    key_path.write_text("PRIVATE_KEY\n", encoding="utf-8")
    host = {
        "host_id": "tui-linux-001",
        "instance_id": "i-123",
        "public_ip": "203.0.113.10",
        "profile": profile,
        "endpoint": "stage",
        "distro": distro,
        "ssh_user": "ubuntu",
        "lease_state": "available",
    }
    if stale_metadata:
        host.update(stale_metadata)
    ledger_path = tmp_path / "host-ledger.json"
    json_helper.dump_path(
        ledger_path,
        {
            "key_path": str(key_path),
            "base_url": "https://api.stage.upyoke.com",
            "endpoint": "stage",
            "distro": distro,
            "ssh_user": "ubuntu",
            "hosts": [host],
        },
    )
    return ledger_path
