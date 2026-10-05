"""Drain allowance follows loaded service-manager settings and safe fallback."""

from types import SimpleNamespace

import pytest

from yoke_harness import session_relay_stop_deadline as deadline


@pytest.mark.parametrize(
    "platform,output,expected",
    [
        ("linux", "1min 30s\n", 89),
        ("linux", "5s\n", 4.5),
        ("linux", "500ms\n", 0.45),
        ("darwin", "service = {\n\texit timeout = 20\n}\n", 19),
    ],
)
def test_loaded_manager_deadline_reserves_small_margin(
    monkeypatch, platform, output, expected
):
    monkeypatch.setattr(deadline.sys, "platform", platform)
    monkeypatch.setattr(
        deadline,
        "resolve_relay_instance",
        lambda: SimpleNamespace(label="relay-instance"),
    )
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=output)

    monkeypatch.setattr(deadline.subprocess, "run", run)
    assert deadline.read_stop_settlement_seconds() == pytest.approx(expected)
    argv, kwargs = calls[0]
    if platform == "linux":
        assert argv == [
            "systemctl",
            "--user",
            "show",
            "relay-instance.service",
            "--property=TimeoutStopUSec",
            "--value",
        ]
    else:
        assert argv == [
            "launchctl",
            "print",
            f"gui/{deadline.os.getuid()}/relay-instance",
        ]
    assert kwargs["timeout"] == deadline.STOP_QUERY_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "platform,output,returncode",
    [
        ("linux", "", 1),
        ("linux", "infinity", 0),
        ("linux", "0s", 0),
        ("darwin", "no exit timeout", 0),
        ("darwin", "exit timeout = 0", 0),
        ("win32", "", 0),
    ],
)
def test_unreadable_deadline_uses_named_conservative_fallback(
    monkeypatch, caplog, platform, output, returncode
):
    monkeypatch.setattr(deadline.sys, "platform", platform)
    monkeypatch.setattr(
        deadline,
        "resolve_relay_instance",
        lambda: SimpleNamespace(label="relay-instance"),
    )
    monkeypatch.setattr(
        deadline.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=returncode, stdout=output),
    )
    assert deadline.read_stop_settlement_seconds() == 4.5
    assert "relay_stop_deadline_unavailable" in caplog.text
    assert "then restart it" in caplog.text


def test_manager_query_failure_uses_fallback(monkeypatch):
    monkeypatch.setattr(deadline.sys, "platform", "linux")
    monkeypatch.setattr(
        deadline,
        "resolve_relay_instance",
        lambda: SimpleNamespace(label="relay-instance"),
    )

    def unavailable(*args, **kwargs):
        raise OSError("manager unavailable")

    monkeypatch.setattr(deadline.subprocess, "run", unavailable)
    assert deadline.read_stop_settlement_seconds() == 4.5
