"""A replaced release bridge exits before its tag and releases nothing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from runtime.api.tools import require_current_bridge_dispatch as gate
from yoke_core.domain.yaml_helper import load_document

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_BRIDGE = REPO_ROOT / ".github" / "workflows" / "platform-release-bridge.yml"
GATE_MODULE = "runtime.api.tools.require_current_bridge_dispatch"
GATE_CONDITION = "steps.dispatch_currency.outputs.current == 'true'"


def _answer(result: Dict[str, Any]) -> str:
    return json.dumps({"success": True, "result": result})


def _refusal(code: str) -> str:
    return json.dumps({"success": False, "error": {"code": code, "message": code}})


def _steps() -> List[Dict[str, Any]]:
    workflow = load_document(RELEASE_BRIDGE)
    return workflow["jobs"]["dispatch-platform-release"]["steps"]


def _run(monkeypatch, tmp_path, stdout: str, code: int = 0):
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(gate, "_read", lambda _id: (code, stdout, ""))
    rc = gate.main(["--dispatch-id", "stuck"])
    return rc, output.read_text() if output.exists() else ""


def test_superseded_bridge_exits_cleanly_with_a_named_notice(
    monkeypatch, tmp_path, capsys
) -> None:
    rc, output = _run(
        monkeypatch,
        tmp_path,
        _answer(
            {
                "found": True,
                "current": False,
                "scope": "deploy:yoke:run-1:release",
                "newest_correlation_id": "replacement",
                "newest_run_id": "",
            }
        ),
    )

    assert rc == 0
    assert output == "current=false\n"
    line = capsys.readouterr().out
    assert "bridge_superseded" in line
    assert "replaced by replacement" in line
    assert "before its tag" in line


def test_current_bridge_proceeds(monkeypatch, tmp_path) -> None:
    rc, output = _run(
        monkeypatch,
        tmp_path,
        _answer({"found": True, "current": True, "scope": "deploy:yoke:run-1:release"}),
    )
    assert (rc, output) == (0, "current=true\n")


@pytest.mark.parametrize("code", ["function_version_skew", "function_not_registered"])
def test_a_control_plane_predating_the_read_proceeds_with_a_warning(
    monkeypatch, tmp_path, capsys, code
) -> None:
    rc, output = _run(monkeypatch, tmp_path, _refusal(code), code=4)
    assert (rc, output) == (0, "current=true\n")
    assert "dispatch_currency_unserved" in capsys.readouterr().out


@pytest.mark.parametrize(
    "stdout,title",
    [
        (_refusal("workflow_dispatch_state_unavailable"), "dispatch_currency_refused"),
        ("not json", "dispatch_currency_unread"),
        (_answer({"found": False}), "dispatch_intent_unknown"),
    ],
)
def test_unanswerable_currency_fails_before_anything_is_tagged(
    monkeypatch, tmp_path, capsys, stdout, title
) -> None:
    rc, output = _run(monkeypatch, tmp_path, stdout, code=0)
    assert rc == gate.UNAVAILABLE
    assert output == ""
    assert title in capsys.readouterr().err


def test_the_gate_runs_right_before_the_tag_on_this_bridges_dispatch_id() -> None:
    steps = _steps()
    names = [str(step.get("name") or "") for step in steps]
    gate_index = next(i for i, s in enumerate(steps) if GATE_MODULE in str(s.get("run")))
    tag_index = next(i for i, n in enumerate(names) if n.startswith("Create or recover"))

    assert gate_index == tag_index - 1
    gate_step = steps[gate_index]
    assert gate_step["id"] == "dispatch_currency"
    assert gate_step["env"]["YOKE_DISPATCH_ID"] == "${{ inputs.yoke_dispatch_id }}"
    assert "if" not in gate_step


def test_a_superseded_bridge_skips_every_later_step_but_cleanup() -> None:
    steps = _steps()
    gate_index = next(i for i, s in enumerate(steps) if GATE_MODULE in str(s.get("run")))
    later = steps[gate_index + 1 :]
    cleanup = [s for s in later if "Cancel the Platform promotion" in str(s["name"])]

    assert len(cleanup) == 1
    for step in later:
        if step is cleanup[0]:
            continue
        assert step.get("if") == GATE_CONDITION, step["name"]
    # Platform promotion is dispatched only after the gate.
    promotion = [s for s in steps if "promote_platform_release" in str(s.get("run"))]
    assert promotion and steps.index(promotion[0]) > gate_index
