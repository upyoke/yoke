"""Transport and quota diagnostics publish canonical microsecond UTC clocks."""

from datetime import timedelta
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_harness import session_relay_plan_limit_http as http
from yoke_harness import ssh_linux_golden_diagnostics as golden

START = "2026-10-05T00:00:00.123456Z"
END = "2026-10-05T00:00:00.123457Z"


@pytest.mark.parametrize("offset", ["-04:00", "+05:45"])
@pytest.mark.parametrize("failed", [False, True])
def test_golden_diagnostics_format_success_and_failure_clocks(
    monkeypatch, tmp_path, offset, failed
):
    from datetime import timezone

    hours, minutes = map(int, offset[1:].split(":"))
    delta = timedelta(hours=hours, minutes=minutes)
    zone = timezone(-delta if offset[0] == "-" else delta)
    start = parse_instant(START).astimezone(zone)
    clock = iter([start, start + timedelta(microseconds=1)])
    monkeypatch.setattr(golden, "utc_now", lambda: next(clock))
    directory = tmp_path / "diagnostics"
    directory.mkdir()
    monkeypatch.setattr(golden.tempfile, "mkdtemp", lambda **k: str(directory))
    commands = []

    class Transport:
        secret_values = ()

        def _run(self, command, **kwargs):
            commands.append(command)
            return SimpleNamespace(returncode=int(failed), stdout="", stderr="")

    monkeypatch.setattr(golden, "SshTestMachineTransport", Transport)
    _, evidence = golden.run_golden_command(
        Transport(), "archive", input_text="", timeout=10
    )
    assert evidence["started_at"] == START
    assert evidence["completed_at"] == END
    if failed:
        assert START in commands[1] and END in commands[1]
        assert Path(evidence["ssh_client_log"]).exists()
    else:
        assert not directory.exists()


def test_quota_failure_preserves_microseconds_in_utc(monkeypatch):
    monkeypatch.setattr(
        http, "utc_now", lambda: parse_instant("2026-10-05T05:45:00.123456+05:45")
    )
    seen = []
    monkeypatch.setattr(http._failures, "failed", lambda *a: seen.append(a))
    detail = http._http_failure(
        HTTPError("https://vendor.example/usage", 429, "limited", Message(), None), {}
    )
    assert detail.endswith("at " + START)
    assert seen[0][1] == detail
