"""Project defaults select personas by the immutable target site's origin."""

import pytest

from yoke_core.domain.agent_mission_browser_identities import (
    mission_browser_settings,
    walker_identity_dispatch,
)


def _settings():
    return {
        "identities": {
            name: {
                "sites": [
                    {
                        "site": "app",
                        "origin": origin,
                        "account": f"{name}@example.com",
                        "probe": {"url": origin + "/api/me", "signed_in_status": 200},
                    }
                ]
            }
            for name, origin in (
                ("buyer", "https://shop.example"),
                ("admin", "https://shop.example"),
                ("other", "https://elsewhere.example"),
            )
        }
    }


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://shop.example/path?query=1", ["buyer", "admin"]),
        ("https://elsewhere.example", ["other"]),
        ("https://uncovered.example", []),
        ("http://shop.example", []),
        ("https://shop.example.evil", []),
        ("", []),
    ],
)
def test_defaults_match_target_origin(url, expected):
    identities, commands, clause = walker_identity_dispatch(
        {"method_config": {}},
        "host-command",
        browser_settings=_settings(),
        execution_target={"endpoints": {"base_url": url}},
    )
    assert identities == expected
    assert len(commands) == len(expected)
    assert bool(clause) == bool(expected)
    if expected:
        assert "site and the account" in clause
        assert "result.settings_json verbatim" in clause


def test_explicit_list_wins_over_project_declarations():
    identities, commands, _ = walker_identity_dispatch(
        {"method_config": {"browser_identities": ["other"]}},
        "host-command",
        browser_settings=_settings(),
        execution_target={"endpoints": {"base_url": "https://shop.example"}},
    )
    assert identities == ["other"]
    assert "--identity other" in commands[0]


def test_undeclared_project_has_no_implicit_default():
    identities, commands, clause = walker_identity_dispatch(
        {},
        "host-command",
        browser_settings={},
        execution_target={"endpoints": {"base_url": "https://shop.example"}},
    )
    assert (identities, commands, clause) == ([], [], "")


@pytest.mark.parametrize("raw", ["not JSON", "[]"])
def test_malformed_settings_teach_repair(monkeypatch, raw):
    from yoke_core.domain import agent_mission_browser_identities as module

    monkeypatch.setattr(module, "query_scalar", lambda *args: raw)
    monkeypatch.setattr(module, "marker", lambda conn: "%s")
    with pytest.raises(
        ValueError, match="browser_identity_declaration_invalid.*Repair"
    ):
        mission_browser_settings(
            object(),
            {
                "execution_target": {"project": {"id": 73}},
                "cases": [{"capture_runner": "agent_mission", "method_config": {}}],
            },
        )


def test_public_bundle_passes_its_database_to_mission_selection(monkeypatch):
    import json
    from yoke_core.domain import agent_mission_review, qa_plan_review
    from yoke_core.domain import qa_plan_review_subject

    conn = object()
    monkeypatch.setattr(
        qa_plan_review, "stage_review_verdicts", lambda *args: ("pass",)
    )
    monkeypatch.setattr(
        qa_plan_review_subject, "public_review_subject", lambda *args: {}
    )
    observed = []

    def dispatch(bundle, *, allowed_verdicts, conn):
        observed.append(conn)
        return {"dispatch_kind": "main_agent_mission"}

    monkeypatch.setattr(
        agent_mission_review, "agent_mission_dispatch_contract", dispatch
    )
    result = qa_plan_review._public_bundle(
        conn,
        {
            "id": "bundle",
            "bundle_digest": "d" * 64,
            "state": "pending",
            "bundle_json": json.dumps({"cases": [{"capture_runner": "agent_mission"}]}),
        },
        execution={},
    )
    assert observed == [conn]
    assert result["dispatch"]["dispatch_kind"] == "main_agent_mission"
