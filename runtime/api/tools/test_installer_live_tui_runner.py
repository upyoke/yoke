from __future__ import annotations

from pathlib import Path

from yoke_core.domain import json_helper
from yoke_core.tools import installer_live_tui_capture as capture
from yoke_core.tools import installer_live_tui_runner as runner


class FakeRunner:
    def __init__(self, captures: list[str]) -> None:
        self.captures = captures
        self.calls: list[list[str]] = []
        self.scp_payloads: dict[str, str] = {}

    def run(self, argv, *, env=None, timeout=30):  # noqa: ANN001, ANN201
        del env, timeout
        args = list(argv)
        self.calls.append(args)
        if args[0] == "scp" and Path(args[-2]).is_file():
            self.scp_payloads[args[-1]] = Path(args[-2]).read_text(encoding="utf-8")
        command = args[-1]
        if "capture-pane" in command:
            return capture.CommandResult(0, self.captures.pop(0), "")
        return capture.CommandResult(0, "", "")


class DirectCommandRunner(FakeRunner):
    def run(self, argv, *, env=None, timeout=30):  # noqa: ANN001, ANN201
        del env, timeout
        args = list(argv)
        self.calls.append(args)
        command = args[-1]
        if args[0] == "ssh" and "tmux" not in command:
            return capture.CommandResult(
                1,
                "uv/uvx is required to install Yoke.\nThen rerun:\n",
                "",
            )
        return capture.CommandResult(0, "", "")


class TmuxStatusRunner(FakeRunner):
    def __init__(
        self,
        captures: list[str],
        *,
        status: str,
        file_status: str | None = None,
        display_returncode: int = 0,
    ) -> None:
        super().__init__(captures)
        self.status = status
        self.file_status = file_status
        self.display_returncode = display_returncode

    def run(self, argv, *, env=None, timeout=30):  # noqa: ANN001, ANN201
        del env, timeout
        args = list(argv)
        self.calls.append(args)
        command = args[-1]
        if "capture-pane" in command:
            return capture.CommandResult(0, self.captures.pop(0), "")
        if "cat /tmp/yoke-live-tui-" in command:
            if self.file_status is None:
                return capture.CommandResult(1, "", "missing status file")
            return capture.CommandResult(0, self.file_status, "")
        if "display-message" in command and "pane_dead_status" in command:
            return capture.CommandResult(
                self.display_returncode,
                self.status,
                "" if self.display_returncode == 0 else "no tmux server",
            )
        return capture.CommandResult(0, "", "")


def test_run_remote_sequence_writes_paired_evidence_and_report(tmp_path: Path) -> None:
    ledger_path = _write_ledger(tmp_path)
    fake = FakeRunner(
        [
            "Yoke onboard\nAdd Yoke to my PATH\n",
            "Yoke onboard\nSee exactly what changes\n",
        ]
    )

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=tmp_path / "campaign",
        assignment_id="A001",
        scenario_id="INSTALL-SMOKE-003",
        command="/home/ec2-user/.local/bin/yoke onboard",
        actions=[
            runner.ScenarioAction("000-initial"),
            runner.ScenarioAction("010-after-down", ("Down",)),
        ],
        expected_text=["See exactly what changes"],
        host_id="tui-linux-001",
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result.ok is True
    assert result.capture_count == 2
    assert result.screenshot_count == 2
    report = json_helper.load_path(Path(result.report_path))
    assert isinstance(report, dict)
    assert report["overall_result"] == "pass"
    scenario = report["scenarios"][0]
    assert len(scenario["captures"]) == 2
    assert len(scenario["screenshots"]) == 2
    for item in scenario["captures"]:
        assert Path(item["path"]).is_file()
    for item in scenario["screenshots"]:
        assert Path(item["path"]).is_file()
    commands = [call[-1] for call in fake.calls]
    assert any(
        "tmux set-option -g remain-on-exit on" in command for command in commands
    )
    launch_command = next(command for command in commands if "tmux new-session" in command)
    assert "sh /tmp/yoke-live-tui-ob.sh" in launch_command
    assert "/home/ec2-user/.local/bin/yoke onboard" not in launch_command
    launch_destination = next(
        destination
        for destination in fake.scp_payloads
        if destination.endswith(":/tmp/yoke-live-tui-ob.sh")
    )
    assert "/home/ec2-user/.local/bin/yoke onboard" in fake.scp_payloads[
        launch_destination
    ]
    assert "printf '%s\\n' \"$rc\" > /tmp/yoke-live-tui-ob.exit" in fake.scp_payloads[
        launch_destination
    ]
    assert any("tmux send-keys -t ob Down" in command for command in commands)
    assert commands[-1] == "tmux kill-session -t ob >/dev/null 2>&1 || true"


def test_run_remote_sequence_retries_blank_capture_before_retaining(
    tmp_path: Path,
) -> None:
    ledger_path = _write_ledger(tmp_path)
    fake = FakeRunner(["\n", "   \n", "Yoke onboard\nReady\n"])

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=tmp_path / "campaign",
        assignment_id="A001",
        scenario_id="GITHUB-001",
        command="/home/ec2-user/.local/bin/yoke path fix --yes && yoke onboard",
        actions=[runner.ScenarioAction("000-path-all-clear")],
        expected_text=["Ready"],
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result.ok is True
    report = json_helper.load_path(Path(result.report_path))
    assert isinstance(report, dict)
    capture_entry = report["scenarios"][0]["captures"][0]
    assert capture_entry["bytes"] > 1
    assert Path(capture_entry["path"]).read_text(encoding="utf-8") == (
        "Yoke onboard\nReady\n"
    )
    capture_calls = [call for call in fake.calls if "capture-pane" in call[-1]]
    assert len(capture_calls) == 3


def test_run_remote_sequence_fails_blank_retained_capture(tmp_path: Path) -> None:
    ledger_path = _write_ledger(tmp_path)
    fake = FakeRunner(["\n"] * runner.DEFAULT_CAPTURE_READY_ATTEMPTS)

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=tmp_path / "campaign",
        assignment_id="A001",
        scenario_id="GITHUB-001",
        command="/home/ec2-user/.local/bin/yoke path fix --yes && yoke onboard",
        actions=[runner.ScenarioAction("000-path-all-clear")],
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result.ok is False
    assert "000-path-all-clear capture was blank" in result.failure
    report = json_helper.load_path(Path(result.report_path))
    assert isinstance(report, dict)
    scenario = report["scenarios"][0]
    assert scenario["result"] == "fail"
    assert scenario["captures"][0]["bytes"] == 1


def test_run_remote_sequence_can_paste_remote_file_contents(
    tmp_path: Path,
) -> None:
    ledger_path = _write_ledger(tmp_path)
    fake = FakeRunner(["Yoke token connected.\n"])

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=tmp_path / "campaign",
        assignment_id="A001",
        scenario_id="AUTH-004",
        command="/home/ec2-user/.local/bin/yoke onboard",
        actions=[
            runner.ScenarioAction(
                "010-token-pasted",
                ("paste_file:/tmp/yoke-stage.token", "Enter"),
            ),
        ],
        expected_text=["Yoke token connected."],
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result.ok is True
    commands = [call[-1] for call in fake.calls]
    assert any("load-buffer" in command for command in commands)
    assert any("/tmp/yoke-stage.token" in command for command in commands)
    assert any("tmux send-keys -t ob Enter" in command for command in commands)


def test_run_remote_sequence_records_failed_expected_text(tmp_path: Path) -> None:
    ledger_path = _write_ledger(tmp_path)
    fake = FakeRunner(["Yoke onboard\nAdd Yoke to my PATH\n"])

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=tmp_path / "campaign",
        assignment_id="A001",
        scenario_id="INSTALL-SMOKE-003",
        command="/home/ec2-user/.local/bin/yoke onboard",
        actions=[runner.ScenarioAction("000-initial")],
        expected_text=["missing text"],
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result.ok is False
    assert result.overall_result == "fail"
    report = json_helper.load_path(Path(result.report_path))
    assert isinstance(report, dict)
    scenario = report["scenarios"][0]
    assert "missing text" in scenario["failure"]
    assert scenario["assertions"]["secret_free"] is True


def test_run_remote_sequence_records_wall_clock_timeout(tmp_path: Path) -> None:
    ledger_path = _write_ledger(tmp_path)
    fake = FakeRunner([])
    now = 0.0

    def clock() -> float:
        return now

    def sleeper(seconds: float) -> None:
        nonlocal now
        now += seconds

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=tmp_path / "campaign",
        assignment_id="A001",
        scenario_id="INSTALL-SMOKE-003",
        command="/home/ec2-user/.local/bin/yoke onboard",
        actions=[runner.ScenarioAction("000-initial")],
        expected_text=["Set up your machine"],
        start_delay=2,
        max_wall_seconds=1,
        runner=fake,
        sleeper=sleeper,
        clock=clock,
    )

    assert result.ok is False
    assert "max_wall_seconds=1 after start delay" in result.failure
    report = json_helper.load_path(Path(result.report_path))
    assert isinstance(report, dict)
    scenario = report["scenarios"][0]
    assert scenario["result"] == "fail"
    assert scenario["assertions"]["max_wall_seconds"] == 1.0
    assert fake.calls[-1][-1] == "tmux kill-session -t ob >/dev/null 2>&1 || true"


def test_run_remote_sequence_writes_one_report_per_assignment_scenario(
    tmp_path: Path,
) -> None:
    ledger_path = _write_ledger(tmp_path)
    campaign_root = tmp_path / "campaign"
    first = FakeRunner(["first scenario\n"])
    second = FakeRunner(["second scenario\n"])
    third = FakeRunner(["third scenario\n"])

    first_result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=campaign_root,
        assignment_id="A001",
        scenario_id="INSTALL-SMOKE-001",
        command="/home/ec2-user/.local/bin/yoke onboard",
        actions=[runner.ScenarioAction("000-first")],
        expected_text=["first scenario"],
        runner=first,
        sleeper=lambda _seconds: None,
    )
    second_result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=campaign_root,
        assignment_id="A001",
        scenario_id="INSTALL-SMOKE-002",
        command="/home/ec2-user/.local/bin/yoke onboard",
        actions=[runner.ScenarioAction("000-second")],
        expected_text=["second scenario"],
        runner=second,
        sleeper=lambda _seconds: None,
    )
    third_result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=campaign_root,
        assignment_id="A001",
        scenario_id="INSTALL-SMOKE-003",
        command="/home/ec2-user/.local/bin/yoke onboard",
        actions=[runner.ScenarioAction("000-third")],
        expected_text=["missing text"],
        runner=third,
        sleeper=lambda _seconds: None,
    )

    assert first_result.report_path != second_result.report_path
    assert second_result.report_path != third_result.report_path
    assert Path(first_result.report_path).name == "A001-INSTALL-SMOKE-001.json"
    assert Path(second_result.report_path).name == "A001-INSTALL-SMOKE-002.json"
    assert Path(third_result.report_path).name == "A001-INSTALL-SMOKE-003.json"
    first_report = json_helper.load_path(Path(first_result.report_path))
    second_report = json_helper.load_path(Path(second_result.report_path))
    report = json_helper.load_path(Path(third_result.report_path))
    assert isinstance(first_report, dict)
    assert isinstance(second_report, dict)
    assert isinstance(report, dict)
    assert first_report["overall_result"] == "pass"
    assert second_report["overall_result"] == "pass"
    assert report["overall_result"] == "fail"
    assert [item["scenario_id"] for item in first_report["scenarios"]] == [
        "INSTALL-SMOKE-001"
    ]
    assert [item["scenario_id"] for item in second_report["scenarios"]] == [
        "INSTALL-SMOKE-002"
    ]
    assert [item["scenario_id"] for item in report["scenarios"]] == [
        "INSTALL-SMOKE-003"
    ]
    assert report["scenarios"][0]["result"] == "fail"


def test_run_remote_sequence_archives_prior_attempt_evidence(
    tmp_path: Path,
) -> None:
    ledger_path = _write_ledger(tmp_path)
    campaign_root = tmp_path / "campaign"
    stale_capture_dir = campaign_root / "captures" / "A001" / "TERM-006"
    stale_screenshot_dir = campaign_root / "screenshots" / "A001" / "TERM-006"
    stale_report_dir = campaign_root / "reports"
    stale_capture_dir.mkdir(parents=True)
    stale_screenshot_dir.mkdir(parents=True)
    stale_report_dir.mkdir(parents=True)
    (stale_capture_dir / "010-wrap-to-quit.txt").write_text(
        "old capture\n",
        encoding="utf-8",
    )
    (stale_screenshot_dir / "010-wrap-to-quit.png").write_bytes(b"old png")
    stale_report = stale_report_dir / "A001-TERM-006.json"
    json_helper.dump_path(
        stale_report,
        {
            "assignment_id": "A001",
            "overall_result": "fail",
            "scenarios": [{"scenario_id": "TERM-006", "result": "fail"}],
        },
    )
    fake = FakeRunner(["current path health\n"])

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=campaign_root,
        assignment_id="A001",
        scenario_id="TERM-006",
        command="/home/ec2-user/.local/bin/yoke onboard",
        actions=[runner.ScenarioAction("000-path-all-clear")],
        expected_text=["current path health"],
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result.ok is True
    assert sorted(path.name for path in stale_capture_dir.iterdir()) == [
        "000-path-all-clear.txt"
    ]
    assert sorted(path.name for path in stale_screenshot_dir.iterdir()) == [
        "000-path-all-clear.png"
    ]
    archive_roots = list((campaign_root / "evidence-archive").iterdir())
    assert len(archive_roots) == 1
    archive_root = archive_roots[0]
    assert (
        archive_root / "captures" / "A001" / "TERM-006" / "010-wrap-to-quit.txt"
    ).is_file()
    assert (
        archive_root / "screenshots" / "A001" / "TERM-006" / "010-wrap-to-quit.png"
    ).is_file()
    assert (archive_root / "reports" / "A001-TERM-006.json").is_file()
    current_report = json_helper.load_path(Path(result.report_path))
    assert current_report["overall_result"] == "pass"
    assert current_report["scenarios"][0]["captures"][0]["name"] == (
        "000-path-all-clear.txt"
    )


def test_run_remote_sequence_uses_ledger_ssh_user(tmp_path: Path) -> None:
    ledger_path = _write_ledger(tmp_path, ssh_user="ubuntu")
    fake = FakeRunner(["Yoke onboard\n"])

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=tmp_path / "campaign",
        assignment_id="A001",
        scenario_id="INSTALL-SMOKE-003",
        command="/home/ubuntu/.local/bin/yoke onboard",
        actions=[runner.ScenarioAction("000-initial")],
        host_id="tui-linux-001",
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result.ok is True
    assert any("ubuntu@203.0.113.10" in call for call in fake.calls)


def test_run_remote_sequence_stages_local_file_before_tmux(tmp_path: Path) -> None:
    ledger_path = _write_ledger(tmp_path)
    source = tmp_path / "install"
    source.write_text("#!/bin/sh\n", encoding="utf-8")
    fake = FakeRunner(["uv/uvx is required and curl is missing\n"])

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=tmp_path / "campaign",
        assignment_id="A001",
        scenario_id="INSTALL-UV-004",
        command="YOKE_INSTALL_YES=1 sh /tmp/yoke-install --yes",
        actions=[runner.ScenarioAction("000-missing-curl")],
        expected_text=["uv/uvx is required and curl is missing"],
        stage_files=[
            {
                "source_path": str(source),
                "remote_path": "/tmp/yoke-install",
            }
        ],
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result.ok is True
    scp_index = next(index for index, call in enumerate(fake.calls) if call[0] == "scp")
    tmux_index = next(
        index for index, call in enumerate(fake.calls) if "tmux new-session" in call[-1]
    )
    assert scp_index < tmux_index
    assert fake.calls[scp_index][-2] == str(source)
    assert fake.calls[scp_index][-1].endswith(":/tmp/yoke-install")


def test_run_remote_sequence_supports_no_tty_ssh_command_mode(
    tmp_path: Path,
) -> None:
    ledger_path = _write_ledger(tmp_path)
    source = tmp_path / "install"
    source.write_text("#!/bin/sh\n", encoding="utf-8")
    fake = DirectCommandRunner([])

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=tmp_path / "campaign",
        assignment_id="A001",
        scenario_id="INSTALL-UV-006",
        command="cat /tmp/yoke-install | sh",
        actions=[runner.ScenarioAction("000-no-tty-decline")],
        expected_text=["uv/uvx is required to install Yoke.", "Then rerun:"],
        post_checks=["no_text:Device not configured"],
        stage_files=[
            {
                "source_path": str(source),
                "remote_path": "/tmp/yoke-install",
            }
        ],
        execution_mode="ssh-command",
        expected_return_codes=[1],
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result.ok is True
    assert any(call[0] == "scp" for call in fake.calls)
    assert any(
        call[0] == "ssh" and call[-1] == "cat /tmp/yoke-install | sh"
        for call in fake.calls
    )
    assert all("tmux" not in call[-1] for call in fake.calls)
    report = json_helper.load_path(Path(result.report_path))
    assert isinstance(report, dict)
    assertions = report["scenarios"][0]["assertions"]
    assert assertions["post_checks"] == ["no_text:Device not configured"]


def test_run_remote_sequence_checks_tmux_exit_code(tmp_path: Path) -> None:
    ledger_path = _write_ledger(tmp_path)
    fake = TmuxStatusRunner(["Yoke is installed\nQuit\n"], status="1:0\n")

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=tmp_path / "campaign",
        assignment_id="A001",
        scenario_id="PATH-008",
        command="/home/ec2-user/.local/bin/yoke onboard --post-install",
        actions=[
            runner.ScenarioAction("000-install-summary"),
            runner.ScenarioAction("010-after-quit", ("Down", "Enter"), capture=False),
        ],
        expected_text=["Quit"],
        post_checks=["tmux_exit_code:0"],
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result.ok is True
    assert result.capture_count == 1
    assert any("display-message" in call[-1] for call in fake.calls)
    report = json_helper.load_path(Path(result.report_path))
    assert isinstance(report, dict)
    assertions = report["scenarios"][0]["assertions"]
    assert assertions["post_checks"] == ["tmux_exit_code:0"]


def test_run_remote_sequence_uses_exit_status_file_when_tmux_exits(
    tmp_path: Path,
) -> None:
    ledger_path = _write_ledger(tmp_path)
    fake = TmuxStatusRunner(
        ["Yoke is installed\nQuit\n"],
        status="",
        file_status="0\n",
        display_returncode=1,
    )

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=tmp_path / "campaign",
        assignment_id="A001",
        scenario_id="PATH-008",
        command="/home/ec2-user/.local/bin/yoke onboard --post-install",
        actions=[
            runner.ScenarioAction("000-install-summary"),
            runner.ScenarioAction("010-after-quit", ("Down", "Enter"), capture=False),
        ],
        expected_text=["Quit"],
        post_checks=["tmux_exit_code:0"],
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result.ok is True
    assert any("cat /tmp/yoke-live-tui-ob.exit" in call[-1] for call in fake.calls)
    assert not any("display-message" in call[-1] for call in fake.calls)


def test_run_remote_sequence_fails_unexpected_tmux_exit_code(
    tmp_path: Path,
) -> None:
    ledger_path = _write_ledger(tmp_path)
    fake = TmuxStatusRunner(["Yoke is installed\nQuit\n"], status="1:2\n")

    result = runner.run_remote_sequence(
        ledger_path=ledger_path,
        campaign_root=tmp_path / "campaign",
        assignment_id="A001",
        scenario_id="PATH-008",
        command="/home/ec2-user/.local/bin/yoke onboard --post-install",
        actions=[
            runner.ScenarioAction("000-install-summary"),
            runner.ScenarioAction("010-after-quit", ("Down", "Enter"), capture=False),
        ],
        expected_text=["Quit"],
        post_checks=["tmux_exit_code:0"],
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result.ok is False
    assert "tmux exit status 2 was not in expected set: 0" in result.failure


def test_parse_action_supports_step_and_keys() -> None:
    action = runner.parse_action("020-after-down:Down,Enter")

    assert action == runner.ScenarioAction("020-after-down", ("Down", "Enter"))


def test_scenario_action_defaults_to_capture() -> None:
    assert runner.ScenarioAction("000-summary").capture is True


def test_parse_action_preserves_paste_file_key() -> None:
    action = runner.parse_action("020-token:paste_file:/tmp/yoke-stage.token,Enter")

    assert action == runner.ScenarioAction(
        "020-token",
        ("paste_file:/tmp/yoke-stage.token", "Enter"),
    )


def test_cli_launch_command_does_not_replace_subcommand() -> None:
    args = runner.build_parser().parse_args(
        [
            "run-ssh",
            "--ledger",
            "/tmp/ledger.json",
            "--campaign-root",
            "/tmp/campaign",
            "--assignment-id",
            "A001",
            "--scenario-id",
            "INSTALL-SMOKE-003",
            "--command",
            "TERM=xterm-256color yoke onboard",
            "--action",
            "000-initial",
        ]
    )

    assert args.subcommand == "run-ssh"
    assert args.launch_command == "TERM=xterm-256color yoke onboard"


def _write_ledger(tmp_path: Path, *, ssh_user: str | None = None) -> Path:
    key_path = tmp_path / "host.pem"
    key_path.write_text("PRIVATE\n", encoding="utf-8")
    ledger_path = tmp_path / "host-ledger.json"
    host = {
        "host_id": "tui-linux-001",
        "public_ip": "203.0.113.10",
    }
    if ssh_user is not None:
        host["ssh_user"] = ssh_user
    json_helper.dump_path(
        ledger_path,
        {
            "key_path": str(key_path),
            "hosts": [host],
        },
    )
    return ledger_path
