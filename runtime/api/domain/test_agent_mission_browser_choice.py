"""Mission walkers pick a browser that exists on the Test Machine."""

from __future__ import annotations

import pytest

from yoke_core.domain.agent_mission_review import agent_mission_dispatch_contract


EXECUTION_ID = "01JQ8P4Z9K2M7V6T5R3N1B0AXY"


def _walker(executor: str, identities: list[str] | None = None, conn=None) -> dict:
    bundle = {
        "bundle_id": "bundle-1",
        "bundle_digest": "d" * 64,
        "execution_id": EXECUTION_ID,
        "subject": {"item_id": 4550, "deployment_run_id": None},
        "execution_target": {
            "project": {"id": 1, "slug": "yoke"},
            "environment": {"name": "stage"},
            "tenant": {"slug": "yoke"},
            "endpoints": {"base_url": "https://stage.example"},
        },
        "execution_target_digest": "e" * 64,
        "cases": [
            {
                "requirement_id": 18152,
                "capture_runner": "agent_mission",
                "capture_run_id": 991,
                "executor": executor,
                "method_config": {"browser_identities": identities or []},
                "instructions": "Install as a new user.",
                "expected_outcome": "Ranked findings.",
                "artifacts": [],
                "transcript": {},
            }
        ],
    }
    return agent_mission_dispatch_contract(bundle, conn=conn)["walker_dispatches"][0]


def test_walker_prompt_uses_yoke_browser_only_when_the_walk_installed_yoke() -> None:
    walker = _walker("informed_subagent")
    prompt = walker["prompt"]

    assert "if Yoke is on the target because this walk installed it" in prompt
    assert walker["browser_setup_command"] in prompt
    assert walker["browser_step_command"] in prompt
    assert "Otherwise open the host's own browser" in prompt
    assert "Safari on macOS" in prompt
    assert "the desktop's default browser elsewhere" in prompt
    assert "screenshots and keystrokes" in prompt
    assert "Never install Yoke on a Test Machine to get a browser." in prompt


@pytest.mark.parametrize("identities", [["operator"], ["operator", "admin"]])
def test_named_identities_select_managed_browser_without_installing_yoke(
    identities: list[str],
) -> None:
    walker = _walker("informed_subagent", identities)
    prompt = walker["prompt"]

    assert "For named browser identities, use the managed browser" in prompt
    assert "because this walk installed it" not in prompt
    assert "Otherwise open the host's own browser" not in prompt
    assert walker["browser_setup_command"] in prompt
    assert walker["browser_step_command"] in prompt
    assert walker["browser_identities"] == identities
    for name, command in zip(identities, walker["browser_verify_commands"]):
        assert f"--identity {name}" in command
        assert command in prompt
    assert "pass `--identity NAME` to every step" in prompt
    assert "Re-sign in yourself or route an approval to steering." in prompt
    assert (
        "Return WALK_STATUS: HUMAN_GATE only when re-signing in needs a "
        "password or credential the agent may not type"
    ) in prompt
    assert (
        "the identity, the site and the account from the report, and resume state"
        in prompt
    )
    assert "A site the check reports expired is WALK_STATUS: HUMAN_GATE" not in prompt
    assert "Never install Yoke on a Test Machine to get a browser." in prompt


def test_project_identities_covering_target_select_managed_browser(monkeypatch) -> None:
    from yoke_core.domain import agent_mission_browser_identities as identities

    settings = {
        "identities": {
            name: {
                "sites": [
                    {
                        "site": "app",
                        "origin": "https://stage.example",
                        "account": f"{name}@example.com",
                        "probe": {
                            "url": "https://stage.example/api/me",
                            "signed_in_status": 200,
                        },
                    }
                ]
            }
            for name in ("operator", "admin")
        }
    }
    reads = []

    def read(conn, query, params):
        reads.append(params)
        return settings

    monkeypatch.setattr(identities, "query_scalar", read)
    monkeypatch.setattr(identities, "marker", lambda conn: "%s")
    walker = _walker("informed_subagent", conn=object())
    assert reads == [(1, "browser-control")]
    assert walker["browser_identities"] == ["operator", "admin"]
    assert "For named browser identities, use the managed browser" in walker["prompt"]
    assert "Use the identity whose account fits the case" in walker["prompt"]
    for name, command in zip(
        walker["browser_identities"], walker["browser_verify_commands"]
    ):
        assert f"--identity {name}" in command
        assert command in walker["prompt"]


def test_case_identities_do_not_read_project_defaults(monkeypatch) -> None:
    from yoke_core.domain import agent_mission_browser_identities as identities

    def unexpected_read(*args):
        pytest.fail("explicit case identities must avoid a settings read")

    monkeypatch.setattr(identities, "query_scalar", unexpected_read)
    walker = _walker("informed_subagent", ["reviewer"], conn=object())
    assert walker["browser_identities"] == ["reviewer"]


@pytest.mark.parametrize("identities", [[], ["operator"]])
def test_walker_human_gate_names_only_prohibited_credential_entry(identities) -> None:
    prompt = _walker("informed_subagent", identities)["prompt"]
    assert (
        "If a password or credential entry the agent may not type is needed, "
        "return immediately with WALK_STATUS: HUMAN_GATE naming that one entry "
        "and resume state."
    ) in prompt
    assert "If a permission dialog" not in prompt
