"""Every codex plan-limit failure names itself and still reaches the mirror."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from yoke_contracts.session_control.plan_limits import reading_is_ok
from yoke_harness import session_relay_codex_plan_limit as codex_limits
from yoke_harness.session_relay_codex_app_server_client import (
    CodexAppServerError,
    _Client,
)
from yoke_harness.session_relay_failure_log import FailureReporter


NOW = "2026-08-30T01:00:00Z"
_OK_APP_SERVER_RESULT = {
    "rateLimitsByLimitId": {
        "codex": {
            "planType": "pro",
            "primary": {
                "usedPercent": 12,
                "windowDurationMins": 10080,
                "resetsAt": 1788643692,
            },
        }
    }
}


def _only_reason(reading: dict) -> str:
    return reading["windows"][0]["reason"]


_OK_MIRROR_PAYLOAD = {
    "plan_type": "pro",
    "rate_limit": {
        "primary_window": {
            "used_percent": 40,
            "limit_window_seconds": 604800,
            "reset_at": 1788643692,
        }
    },
}


@pytest.fixture(autouse=True)
def _fresh_failure_reporter(monkeypatch) -> None:
    """The module reporter suppresses repeats for 300s; each test starts clean."""
    monkeypatch.setattr(codex_limits, "_failures", FailureReporter())


class _FakeClient:
    """Stands in for the bounded app-server client the probe reuses."""

    def __init__(self, *, result=None, failure=None, stderr_tail_text="") -> None:
        self.result = result
        self.failure = failure
        self.stderr_tail_text = stderr_tail_text
        self.closed = False
        self.requested: list[tuple[str, dict]] = []

    def request(self, method: str, params: dict) -> dict:
        self.requested.append((method, params))
        if self.failure is not None:
            raise self.failure
        return self.result

    def stderr_tail(self) -> str:
        return self.stderr_tail_text

    def close(self) -> None:
        self.closed = True


def _install_client(monkeypatch, client) -> None:
    monkeypatch.setattr(codex_limits, "_Client", lambda *_a, **_k: client)


def _install_failing_construction(monkeypatch, failure) -> None:
    def _raise(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(codex_limits, "_Client", _raise)


def _install_mirror(monkeypatch, reading, reason) -> None:
    monkeypatch.setattr(
        codex_limits,
        "_usage_mirror_reading",
        lambda _observed_at: (reading, reason),
    )


def test_app_server_read_uses_the_proven_client_and_returns_the_bucket(
    monkeypatch,
) -> None:
    client = _FakeClient(result=_OK_APP_SERVER_RESULT)
    _install_client(monkeypatch, client)

    reading = codex_limits.probe_codex_cli(observed_at=NOW)

    assert client.requested == [("account/rateLimits/read", {})]
    assert client.closed is True
    assert reading_is_ok(reading)
    assert reading["windows"] == [
        {
            "window_kind": "rolling_7d",
            "scope": "all",
            "remaining_percent": 88.0,
            "resets_at": "2026-09-05T21:28:12Z",
            "status": "ok",
            "reason": None,
        }
    ]
    assert reading["plan_tier"] == "pro"


@pytest.mark.parametrize(
    ("code", "expected_reason"),
    [
        ("binary_resolve", "cli_unavailable"),
        ("spawn", "app_server_spawn_failed"),
        ("pipes", "app_server_pipes_unavailable"),
        ("request_rejected", "app_server_request_rejected"),
        ("write_failed", "app_server_write_failed"),
        ("eof", "app_server_eof_before_reply"),
        ("timeout", "app_server_timeout"),
        ("response_oversize", "app_server_response_oversize"),
        ("stdout_unavailable", "app_server_stdout_unavailable"),
        ("method_error", "unsupported_on_this_build"),
        ("something_new", "app_server_something_new"),
    ],
)
def test_each_client_failure_code_names_its_own_reason(
    monkeypatch, code: str, expected_reason: str
) -> None:
    _install_client(
        monkeypatch,
        _FakeClient(failure=CodexAppServerError("boom", code=code)),
    )
    _install_mirror(monkeypatch, None, "codex_auth_missing_tokens")

    reading = codex_limits.probe_codex_cli(observed_at=NOW)

    assert not reading_is_ok(reading)
    assert _only_reason(reading) == f"{expected_reason}+codex_auth_missing_tokens"


def test_spawn_failure_carries_the_class_that_actually_raised(monkeypatch) -> None:
    failure = CodexAppServerError("app-server unavailable", "spawn", code="spawn")
    failure.__cause__ = PermissionError("denied")
    _install_failing_construction(monkeypatch, failure)
    _install_mirror(monkeypatch, None, "codex_auth_not_json")

    reading = codex_limits.probe_codex_cli(observed_at=NOW)

    assert (
        _only_reason(reading)
        == "app_server_spawn_failed:PermissionError+codex_auth_not_json"
    )


def test_a_result_that_is_not_the_rate_limit_shape_is_named_unparsed(
    monkeypatch,
) -> None:
    _install_client(monkeypatch, _FakeClient(result={"somethingElse": 1}))
    _install_mirror(monkeypatch, None, "codex_auth_missing_tokens")

    reading = codex_limits.probe_codex_cli(observed_at=NOW)

    assert _only_reason(reading).startswith("app_server_result_unparsed+")


def test_an_empty_result_is_named_rather_than_parsed(monkeypatch) -> None:
    _install_client(monkeypatch, _FakeClient(result={}))
    _install_mirror(monkeypatch, None, "codex_auth_missing_tokens")

    reading = codex_limits.probe_codex_cli(observed_at=NOW)

    assert _only_reason(reading).startswith("app_server_empty_result+")


@pytest.mark.parametrize("code", ["eof", "timeout", "spawn", "response_oversize"])
def test_every_app_server_failure_mode_falls_back_to_the_mirror(
    monkeypatch, code: str
) -> None:
    _install_client(
        monkeypatch,
        _FakeClient(failure=CodexAppServerError("boom", code=code)),
    )
    healed = {
        "surface": "codex-cli",
        "plan_tier": "pro",
        "observed_at": NOW,
        "windows": [
            {
                "window_kind": "rolling_7d",
                "scope": "all",
                "remaining_percent": 60.0,
                "resets_at": None,
                "status": "ok",
                "reason": None,
            }
        ],
    }
    _install_mirror(monkeypatch, healed, "")

    assert codex_limits.probe_codex_cli(observed_at=NOW) is healed


def test_the_app_server_failure_is_logged_even_when_the_mirror_heals_it(
    monkeypatch, caplog
) -> None:
    _install_client(
        monkeypatch,
        _FakeClient(
            failure=CodexAppServerError(
                "app-server exited before replying", code="eof"
            ),
            stderr_tail_text="codex: could not reach the desktop app",
        ),
    )
    _install_mirror(
        monkeypatch,
        {"surface": "codex-cli", "plan_tier": None, "observed_at": NOW, "windows": []},
        "",
    )
    caplog.set_level(logging.WARNING, logger="yoke_harness.session_relay_failure_log")

    codex_limits.probe_codex_cli(observed_at=NOW)

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "app_server_eof_before_reply" in logged
    assert "could not reach the desktop app" in logged


def test_the_client_is_closed_even_when_the_exchange_fails(monkeypatch) -> None:
    client = _FakeClient(failure=CodexAppServerError("boom", code="timeout"))
    _install_client(monkeypatch, client)
    _install_mirror(monkeypatch, None, "codex_auth_not_json")

    codex_limits.probe_codex_cli(observed_at=NOW)

    assert client.closed is True


def test_the_mirror_reads_the_primary_window_from_stored_credentials(
    monkeypatch, tmp_path: Path
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(
        json.dumps({"tokens": {"access_token": "t", "account_id": "a"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    seen: dict[str, object] = {}

    def _http(url, *, headers, data=None, method=None):
        seen["url"] = url
        seen["headers"] = headers
        return _OK_MIRROR_PAYLOAD

    monkeypatch.setattr(codex_limits, "plan_limit_http_json", _http)

    reading, reason = codex_limits._usage_mirror_reading(NOW)

    assert reason == ""
    assert reading_is_ok(reading)
    assert reading["windows"][0]["remaining_percent"] == 60.0
    assert reading["windows"][0]["window_kind"] == "rolling_7d"
    assert seen["url"] == codex_limits.CODEX_USAGE_URL
    assert seen["headers"]["chatgpt-account-id"] == "a"


@pytest.mark.parametrize(
    ("document", "expected_reason"),
    [
        ("not json at all", "codex_auth_not_json"),
        (json.dumps({"tokens": "nope"}), "codex_auth_missing_tokens"),
        (
            json.dumps({"tokens": {"account_id": "a"}}),
            "codex_auth_missing_access_token",
        ),
    ],
)
def test_each_stored_credential_problem_names_itself(
    monkeypatch, tmp_path: Path, document: str, expected_reason: str
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(document, encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    assert codex_limits._usage_mirror_reading(NOW) == (None, expected_reason)


def test_a_missing_credential_file_names_the_read_error(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    reading, reason = codex_limits._usage_mirror_reading(NOW)

    assert reading is None
    assert reason == "codex_auth_unreadable_FileNotFoundError"


def test_the_client_keeps_the_failing_child_stderr_tail() -> None:
    client = object.__new__(_Client)
    import tempfile

    client.stderr_file = tempfile.TemporaryFile()
    client.stderr_file.write(b"codex: app-server refused the connection\n")

    assert "refused the connection" in client.stderr_tail()


def test_the_client_reports_no_tail_when_capture_is_off() -> None:
    client = object.__new__(_Client)
    client.stderr_file = None

    assert client.stderr_tail() == ""
