"""New client-machine checks work while the server still has an older roster."""

from __future__ import annotations

import json

import pytest

from yoke_cli.commands.adapters import doctor_https_compose as compose
from yoke_cli.commands.adapters import doctor_https_run as doctor
from yoke_contracts.api.function_call import FunctionCallResponse


@pytest.mark.parametrize(
    "scope, remote_only",
    [
        ({"only": "HC-hook-resident"}, None),
        ({"only": "hook-resident,stale-sessions"}, "stale-sessions"),
        ({"full": True}, ""),
    ],
)
def test_machine_check_does_not_require_a_server_roster_entry(
    monkeypatch,
    capsys,
    scope,
    remote_only,
):
    local_calls = []
    relay_calls = []
    receipts = []
    local_row = {
        "hc": "hook-resident",
        "name": "Resident",
        "severity": "WARN",
        "detail": "YOKE_HOOK_RESIDENT_UNREACHABLE; hooks use the canonical fallback",
    }

    def run_local(**kwargs):
        local_calls.append(kwargs)
        return [local_row]

    def old_server(**kwargs):
        relay_calls.append(kwargs["payload"])
        # An older server does not recognize the new machine-only check.
        assert "hook-resident" not in kwargs["payload"].get("only", "")
        return FunctionCallResponse(
            success=True,
            function="doctor.run.run",
            version="v1",
            request_id="old-roster",
            result={
                "results": [
                    {
                        "hc": "stale-sessions",
                        "severity": "PASS",
                        "name": "Sessions",
                        "detail": "",
                    }
                ],
                "project": "sample",
                "runtime": "hosted",
                "scope": "full" if scope.get("full") else "only",
            },
        )

    monkeypatch.setattr(
        compose, "requested_local_machine_slugs", lambda p: (["hook-resident"], [])
    )
    monkeypatch.setattr(compose, "run_local_runtime_checks", run_local)
    monkeypatch.setattr(compose, "machine_has_checkout_for", lambda p: False)
    monkeypatch.setattr(doctor, "collect_chunked", old_server)
    monkeypatch.setattr(
        doctor, "persist_composed_receipt", lambda result, **kw: receipts.append(result)
    )
    assert (
        doctor.dispatch_chunked(
            payload={"project": "sample", **scope},
            session_id="session",
            json_mode=True,
            chunk_max_checks=1,
            timeout_s=1,
        )
        == 0
    )
    envelope = json.loads(capsys.readouterr().out)
    result = envelope["result"]
    assert result["warn_count"] == 1
    assert local_row in result["results"]
    assert len(local_calls) == 1
    assert local_calls[0]["slugs"] == ["hook-resident"]
    assert receipts == [result]
    if remote_only is None:
        assert not relay_calls
        assert result["composed"] == "local_runtime"
    else:
        assert len(relay_calls) == 1
        assert relay_calls[0].get("only", "") == remote_only
        assert result["pass_count"] == 1


def test_known_machine_check_does_not_run_twice_for_server_na(monkeypatch, capsys):
    row = {
        "hc": "hook-resident",
        "severity": "N/A",
        "name": "Resident",
        "detail": "local runtime only",
    }
    calls = []
    monkeypatch.setattr(
        compose, "requested_local_machine_slugs", lambda p: (["hook-resident"], [])
    )
    monkeypatch.setattr(
        compose,
        "run_local_runtime_checks",
        lambda **kw: calls.append(kw) or [{**row, "severity": "PASS"}],
    )
    monkeypatch.setattr(compose, "machine_has_checkout_for", lambda p: False)
    monkeypatch.setattr(doctor, "persist_composed_receipt", lambda *a, **kw: None)
    monkeypatch.setattr(
        doctor,
        "collect_chunked",
        lambda **kw: FunctionCallResponse(
            success=True,
            function="doctor.run.run",
            version="v1",
            request_id="current-roster",
            result={"results": [row], "project": "sample", "runtime": "hosted"},
        ),
    )
    assert (
        doctor.dispatch_chunked(
            payload={"project": "sample", "full": True},
            session_id="session",
            json_mode=True,
            chunk_max_checks=1,
            timeout_s=1,
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)["result"]
    assert len(calls) == 1
    assert result["na_count"] == 0
    assert result["pass_count"] == 1
