"""Browser approval authority comes from the project's declaration."""

import hashlib
import json

import pytest

from runtime.api.domain.machine_qa_browser_flow_test_support import EXAMPLE_FLOW
from yoke_core.domain import machine_qa_browser_flow_policy as policy


@pytest.mark.parametrize(
    "changes",
    [
        {"origins": ["https://:@app.example.test"]},
        {"origins": ["http://app.example.test"]},
        {"origins": ["https://app.example.test/path"]},
        {"paths": ["//foreign.test/path"]},
        {"code_pattern": "["},
        {"query_parameter": "code&other"},
        {"denial_text": []},
    ],
)
def test_invalid_project_declaration_is_refused(changes):
    with pytest.raises(ValueError):
        policy.validate_browser_flow({**EXAMPLE_FLOW, **changes})


def test_registered_project_lane_declares_its_own_application(tmp_path, monkeypatch):
    root = tmp_path / "project"
    lane = root / "lanes" / "candidate"
    (lane / ".git").mkdir(parents=True)
    (lane / ".yoke").mkdir()
    content = json.dumps(
        {
            "required_sign_ins": ["Application approver"],
            "machine_browser_approval": EXAMPLE_FLOW,
        }
    ).encode()
    (lane / ".yoke" / "browser-flows.json").write_bytes(content)
    monkeypatch.setattr(policy, "checkout_for_project_id", lambda _: root)
    monkeypatch.chdir(lane)
    result = policy.load_browser_flow(1, "machine_browser_approval")
    assert result["origins"] == EXAMPLE_FLOW["origins"]
    assert result["declaration_sha256"] == hashlib.sha256(content).hexdigest()
    assert result["required_sign_ins"] == ["Application approver"]


def test_missing_declaration_names_the_project_file_and_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "checkout_for_project_id", lambda _: tmp_path)
    with pytest.raises(
        ValueError, match="browser_flow_declaration_missing_or_invalid"
    ) as caught:
        policy.load_browser_flow(1, "machine_browser_approval")
    assert str(tmp_path / ".yoke" / "browser-flows.json") in str(caught.value)
    assert "retry this case" in str(caught.value)


def test_project_must_list_needed_sign_ins(tmp_path, monkeypatch):
    (tmp_path / ".yoke").mkdir()
    (tmp_path / ".yoke" / "browser-flows.json").write_text(
        json.dumps({"required_sign_ins": [], "machine_browser_approval": EXAMPLE_FLOW})
    )
    monkeypatch.setattr(policy, "checkout_for_project_id", lambda _: tmp_path)
    with pytest.raises(ValueError, match="browser_flow_declaration_missing_or_invalid"):
        policy.load_browser_flow(1, "machine_browser_approval")
