from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import json_helper
from yoke_core.tools import installer_live_tui_capture as capture


class FakeRunner:
    def __init__(self, *, stdout: str = "", stderr: str = "", rc: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.rc = rc
        self.calls: list[list[str]] = []

    def run(self, argv, *, env=None, timeout=30):  # noqa: ANN001, ANN201
        del env, timeout
        args = list(argv)
        self.calls.append(args)
        return capture.CommandResult(self.rc, self.stdout, self.stderr)


def test_write_paired_evidence_writes_text_and_png(tmp_path: Path) -> None:
    result = capture.write_paired_evidence(
        campaign_root=tmp_path,
        assignment_id="A001",
        scenario_id="INSTALL-SMOKE-003",
        step="000-initial",
        text="Yoke onboard\nAdd Yoke to your PATH\n",
    )

    text_path = Path(result.capture_path)
    screenshot_path = Path(result.screenshot_path)
    assert text_path.read_text(encoding="utf-8") == "Yoke onboard\nAdd Yoke to your PATH\n"
    assert screenshot_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert result.text_bytes > 0
    assert result.screenshot_bytes > 0


def test_display_renderer_maps_lowercase_to_available_glyphs() -> None:
    assert capture._display_line("Add Yoke to your PATH") == "ADD YOKE TO YOUR PATH"  # noqa: SLF001


def test_display_renderer_maps_live_tui_symbols_without_question_fallback() -> None:
    line = capture._display_line(  # noqa: SLF001
        "☀ ✔ ✓ ✗ ● ○ ↑↓ ↵ • — ~/.yoke {json} `cmd` $ "
        "╭─╮ ╰─╯ ╔═╗ ╚═╝ ║ ▂▃▄▅▆▇█▀▐▌ "
        "⬛⬜🟩🟧🟥🟦🟪🟣🟢💚💧🎫🌱⛔🧊✅⚫🔲🔳◐▪\x1b\x07"
    )

    assert "?" not in line
    assert all(char.upper() in capture.FONT for char in line)  # noqa: SLF001


def test_capture_local_invokes_tmux_and_saves_evidence(tmp_path: Path) -> None:
    runner = FakeRunner(stdout="screen text\n")

    text = capture.capture_tmux_pane(pane="ob", history=True, runner=runner)
    result = capture.write_paired_evidence(
        campaign_root=tmp_path,
        assignment_id="A001",
        scenario_id="PATH-001",
        step="010-after-enter",
        text=text,
    )

    assert runner.calls == [["tmux", "capture-pane", "-t", "ob", "-p", "-S", "-"]]
    assert Path(result.capture_path).is_file()
    assert Path(result.screenshot_path).is_file()


def test_ssh_capture_reads_ledger_and_uses_shared_ssh_shape(tmp_path: Path) -> None:
    key_path = tmp_path / "host.pem"
    key_path.write_text("PRIVATE\n", encoding="utf-8")
    ledger_path = tmp_path / "host-ledger.json"
    json_helper.dump_path(
        ledger_path,
        {
            "key_path": str(key_path),
            "hosts": [
                {
                    "host_id": "tui-linux-001",
                    "public_ip": "203.0.113.10",
                }
            ],
        },
    )
    runner = FakeRunner(stdout="remote screen\n")

    key, public_ip, host_id = capture.host_from_ledger(ledger_path, "tui-linux-001")
    text = capture.capture_remote_tmux_pane(
        key_path=key,
        public_ip=public_ip,
        pane="ob",
        runner=runner,
    )

    assert host_id == "tui-linux-001"
    assert text == "remote screen\n"
    call = runner.calls[0]
    assert call[:3] == ["ssh", "-i", str(key_path)]
    assert "ec2-user@203.0.113.10" in call
    assert call[-1] == "tmux capture-pane -t ob -p"


def test_ssh_capture_uses_ledger_ssh_user(tmp_path: Path) -> None:
    key_path = tmp_path / "host.pem"
    key_path.write_text("PRIVATE\n", encoding="utf-8")
    ledger_path = tmp_path / "host-ledger.json"
    json_helper.dump_path(
        ledger_path,
        {
            "key_path": str(key_path),
            "hosts": [
                {
                    "host_id": "tui-linux-001",
                    "public_ip": "203.0.113.10",
                    "ssh_user": "ubuntu",
                }
            ],
        },
    )
    runner = FakeRunner(stdout="remote screen\n")

    connection = capture.host_connection_from_ledger(ledger_path, "tui-linux-001")
    text = capture.capture_remote_tmux_pane(
        key_path=connection.key_path,
        public_ip=connection.public_ip,
        ssh_user=connection.ssh_user,
        pane="ob",
        runner=runner,
    )

    assert connection.host_id == "tui-linux-001"
    assert text == "remote screen\n"
    assert "ubuntu@203.0.113.10" in runner.calls[0]


def test_ssh_capture_prefers_host_key_path(tmp_path: Path) -> None:
    root_key = tmp_path / "root.pem"
    root_key.write_text("ROOT\n", encoding="utf-8")
    host_key = tmp_path / "host.pem"
    host_key.write_text("HOST\n", encoding="utf-8")
    ledger_path = tmp_path / "host-ledger.json"
    json_helper.dump_path(
        ledger_path,
        {
            "key_path": str(root_key),
            "hosts": [
                {
                    "host_id": "tui-linux-001",
                    "key_path": str(host_key),
                    "public_ip": "203.0.113.10",
                }
            ],
        },
    )

    connection = capture.host_connection_from_ledger(ledger_path, "tui-linux-001")

    assert connection.key_path == host_key


def test_send_remote_tmux_keys_quotes_keys(tmp_path: Path) -> None:
    key_path = tmp_path / "host.pem"
    key_path.write_text("PRIVATE\n", encoding="utf-8")
    runner = FakeRunner()

    capture.send_remote_tmux_keys(
        key_path=key_path,
        public_ip="203.0.113.10",
        pane="ob",
        keys=["Down", "Enter"],
        runner=runner,
    )

    assert runner.calls[0][-1] == "tmux send-keys -t ob Down Enter"


def test_rejects_unsafe_path_components(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        capture.write_paired_evidence(
            campaign_root=tmp_path,
            assignment_id="../bad",
            scenario_id="INSTALL-SMOKE-003",
            step="000-initial",
            text="nope\n",
        )
