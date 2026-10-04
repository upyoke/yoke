"""Deployment retirement probes bind their target before any fixture write."""

import pytest

from ops.qa import project_retirement as probe


def environment(monkeypatch):
    for key, value in {
        "BASE_URL": "https://example.test",
        "DEPLOYMENT_RUN_ID": "run",
        "DEPLOYMENT_MEMBER_REF": "member",
    }.items():
        monkeypatch.setenv(key, value)


def test_probe_keeps_fixture_identity_and_checks_default_and_historical_lists(
    monkeypatch,
):
    environment(monkeypatch)
    calls, retired = [], set()
    rows = {
        "fixture": {
            "id": 2,
            "slug": "fixture",
            "public_item_prefix": "QA",
            "created_at": "then",
        },
        "real": {
            "id": 1,
            "slug": "real",
            "public_item_prefix": "LIVE",
            "created_at": "then",
        },
    }

    def call(connection, *argv):
        calls.append(argv)
        if argv == ("env", "list"):
            return {
                "rows": [
                    {
                        "env": "prod",
                        "api_url": "https://example.test/api/orgs/qa",
                        "transport": "https",
                    }
                ]
            }
        if argv[:2] == ("projects", "get"):
            row = next(
                row for row in rows.values() if argv[3] in (row["slug"], str(row["id"]))
            )
            return {
                "row": {**row, "retired_at": "now" if row["id"] in retired else None}
            }
        if argv[:2] == ("projects", "retire"):
            retired.add(int(argv[3]))
            return {"changed": True}
        assert argv[:2] == ("projects", "list")
        return {
            "rows": [
                row
                for row in rows.values()
                if "--include-retired" in argv or row["id"] not in retired
            ]
        }

    monkeypatch.setattr(probe, "call", call)
    probe.prove("prod", ["fixture"], ["LIVE"])
    assert retired == {2}
    assert ("projects", "list", "--include-retired") in calls


def test_probe_refuses_non_https_connection_before_mutation(monkeypatch):
    environment(monkeypatch)
    calls = []

    def call(connection, *argv):
        calls.append(argv)
        return {"rows": [{"env": "prod", "api_url": "", "transport": "local-postgres"}]}

    monkeypatch.setattr(probe, "call", call)
    with pytest.raises(RuntimeError, match="target_mismatch"):
        probe.prove("prod", ["fixture"], ["LIVE"])
    assert calls == [("env", "list")]
