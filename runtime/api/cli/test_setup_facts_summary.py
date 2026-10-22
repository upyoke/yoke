"""Client setup reads preserve scope, refusal truth and older-server absence."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from yoke_cli.config import setup_facts_summary as summary
from yoke_cli.config import machine_config, onboard_setup_facts
from yoke_cli.config import project_onboarding_handoff as handoff
from yoke_cli.commands import _helpers
from yoke_cli.transport import dispatcher


def install_read(monkeypatch, response):
    # Load consumers before patching the dispatcher so lazy imports cannot
    # retain this test's response after monkeypatch restores the provider.
    from yoke_cli.config import project_onboard_support

    observed = {
        "machine_id": "second-machine",
        "observations": {
            "checkout-binding": {"status": "unknown", "reason": "machine_not_checked"},
        },
    }
    monkeypatch.setattr(onboard_setup_facts, "collect", lambda **_: observed)
    monkeypatch.setattr(_helpers, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(machine_config, "project_id", lambda *_: 9)
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(dispatcher, "call_dispatcher", dispatch)
    monkeypatch.setattr(project_onboard_support, "call_dispatcher", dispatch)
    return calls, observed


def test_second_machine_observations_and_no_guessed_next(monkeypatch):
    calls, observed = install_read(
        monkeypatch,
        SimpleNamespace(
            success=True,
            result={
                "schema_version": 2,
                "run": {"rows": [{"row_id": "checkout-binding", "status": "unknown"}]},
            },
        ),
    )
    result = summary.read_project(Path("/unrelated"))
    assert calls[0]["payload"]["observations"] is observed["observations"]
    assert calls[0]["target"].project_id == "9"
    assert result["next_action"] is None
    assert not any(line.startswith("Next:") for line in result["lines"])
    assert "unknown checkout-binding" in result["lines"][0]


@pytest.mark.parametrize(
    "code",
    [
        "function_version_skew",
        "https_unreachable",
        "response_timeout",
        "actor_required",
    ],
)
def test_failure_names_reason_and_recovery(monkeypatch, code):
    install_read(
        monkeypatch,
        SimpleNamespace(
            success=False,
            error=SimpleNamespace(
                code=code,
                recovery_hint="Repair the connection, then retry.",
                message="refused",
            ),
        ),
    )
    lines = summary.read_project(Path("/unrelated"))["lines"]
    assert len(lines) == 1
    assert code in lines[0] and "Repair the connection" in lines[0]


def test_permission_denial_omits_setup_without_claiming_readiness(monkeypatch):
    install_read(
        monkeypatch,
        SimpleNamespace(
            success=False,
            error=SimpleNamespace(
                code="permission_denied",
                recovery_hint="Ask an admin",
                message="denied",
            ),
        ),
    )
    assert summary.read_project(Path("/unrelated"))["lines"] == []


def test_settled_orientation_is_suppressed():
    run = {
        "rows": [{"row_id": "lifecycle-readiness", "status": "verified"}],
        "setup_readiness": {"ready": True},
        "next_action": None,
    }
    assert summary.summary_lines(run, orientation=True) == []
    assert summary.summary_lines(run)


@pytest.mark.parametrize("status", ["blocked", "needed"])
def test_unsettled_handoff_remains_visible_after_first_work(monkeypatch, status):
    action = {
        "row_id": "human-interview",
        "command": "/yoke onboard",
        "reason": "setup_required",
        "home": ".yoke/docs/start/terminal-onboarding.md",
    }
    install_read(
        monkeypatch,
        SimpleNamespace(
            success=True,
            result={
                "schema_version": 2,
                "run": {
                    "rows": [
                        {"row_id": "setup-checklist-handoff", "status": status},
                        {"row_id": "lifecycle-readiness", "status": "verified"},
                        {"row_id": "capability-setup", "status": "unknown"},
                    ],
                    "setup_readiness": {"ready": True},
                    "next_action": action,
                },
            },
        ),
    )
    result = summary.read_project(Path("/unrelated"), orientation=True)
    assert f"{status} setup-checklist-handoff" in result["lines"][0]
    assert "capability-setup" not in result["lines"][0]
    assert result["next_action"] == action
    assert result["lines"][1] == summary.next_line(action)


def test_global_summary_has_only_this_machine_facts(monkeypatch):
    def collect(**kwargs):
        assert kwargs == {"machine_only": True}
        return {"observations": {"package-install": {"status": "configured"}}}

    monkeypatch.setattr(onboard_setup_facts, "collect", collect)
    result = summary.machine_summary()
    assert result["next_action"]["command"] == "yoke setup --agent"
    assert "https://upyoke.com/docs/" in result["next_action"]["home"]
    assert "project-identity" not in str(result)


def test_diagnosed_machine_failure_keeps_its_reachable_repair(monkeypatch):
    def collect(**kwargs):
        raise ValueError(
            "setup_machine_config_unreadable: repair this machine with yoke setup."
        )

    monkeypatch.setattr(onboard_setup_facts, "collect", collect)
    lines = summary.read_project(Path("/external"))["lines"]
    assert lines == [
        "Setup: setup_machine_config_unreadable; repair this machine with yoke setup."
    ]


@pytest.mark.parametrize(
    "family, router",
    [
        ("codex", "$yoke"),
        ("claude-code", "/yoke"),
        ("cursor", "/yoke"),
    ],
)
def test_orientation_uses_native_skill_with_recovery_arguments(
    monkeypatch, family, router
):
    monkeypatch.setattr(handoff, "nearest_harness_family", lambda: family)
    action = {
        "command": "/yoke onboard --project 9",
        "reason": "setup_required",
        "home": "guide",
    }
    lines = summary.summary_lines({"rows": [], "next_action": action}, orientation=True)
    assert f"{router} onboard --project 9" in lines[1]
    assert "setup_required" in lines[1]
    assert action["command"] == "/yoke onboard --project 9"


def test_setup_terminal_guidance_names_both_harness_forms(monkeypatch):
    from yoke_cli.config.onboard_report import next_steps

    monkeypatch.setattr(handoff, "nearest_harness_family", lambda: None)
    command = next_steps(Path("config.json"), "local-checkout")[1]
    for router in ("$yoke", "/yoke"):
        assert f"{router} onboard --run-id <run-id>" in command


def test_shell_recovery_stays_a_shell_command(monkeypatch):
    monkeypatch.setattr(handoff, "nearest_harness_family", lambda: "codex")
    action = {
        "command": "yoke setup --agent",
        "reason": "setup_required",
        "home": "guide",
    }
    assert "Next: yoke setup --agent" in summary.next_line(action)


def test_recovery_sentence_uses_native_onboarding_router(monkeypatch):
    monkeypatch.setattr(handoff, "nearest_harness_family", lambda: "codex")
    action = {
        "command": "Resume /yoke onboard and confirm the changed setup proposal.",
        "reason": "setup_changed",
        "home": "guide",
    }
    line = summary.next_line(action)
    assert "Resume $yoke onboard" in line
    assert "/yoke" not in line
