"""A case resolves only its own identity and sends paths, never credentials."""

import json
from unittest.mock import Mock

import pytest

from yoke_contracts.machine_config.capability_secret_store import store_machine_capability_secret
from yoke_contracts.browser_identity import parse_identity_declarations
from yoke_core.domain import browser_client, browser_qa_steps as steps
from yoke_core.domain.browser_qa_step_sign_in import set_case_identity


def identity(automatic=True):
    site = {
        "site": "shop",
        "origin": "https://shop.example",
        "probe": {"url": "https://shop.example/me", "signed_in_status": 204},
    }
    if automatic:
        site["sign_in"] = {
            "mode": "automatic",
            "credential_origins": ["https://identity.example"],
            "url": "https://shop.example/login",
            "steps": [{"fill": "#password", "secret": "password"}, {"click": "button"}],
        }
    return parse_identity_declarations({"identities": {"buyer": {"sites": [site]}}})[
        "buyer"
    ]


@pytest.fixture(autouse=True)
def case_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.setattr(browser_client, "daemon_running", lambda: True)
    set_case_identity("acme", identity())
    yield
    set_case_identity("", None)


@pytest.mark.parametrize(
    "declared,site", [(None, "shop"), (False, "shop"), (True, "other")]
)
def test_step_refuses_site_without_automatic_sign_in(monkeypatch, declared, site):
    set_case_identity("acme", identity(declared) if declared is not None else None)
    send = Mock()
    monkeypatch.setattr(browser_client, "daemon_request", send)
    outcome = steps._execute_step(
        {"action": "sign_in", "site": site}, "https://shop.example", "/tmp", "case"
    )
    assert not outcome["success"]
    assert "browser_sign_in_step_not_automatic" in outcome["error"]
    send.assert_not_called()


def test_missing_secret_names_recovery_without_a_daemon_request(monkeypatch):
    send = Mock()
    monkeypatch.setattr(browser_client, "daemon_request", send)
    outcome = steps._execute_step(
        {"action": "sign_in", "site": "shop"}, "https://shop.example", "/tmp", "case"
    )
    assert "browser_sign_in_secret_missing" in outcome["error"]
    assert "--key sign-in.buyer.shop.password --value-stdin" in outcome["error"]
    send.assert_not_called()


def test_paths_cross_daemon_boundary_and_only_outcomes_cross_evidence_boundary(
    monkeypatch, capsys
):
    secret = "planted-credential-never-in-evidence"
    file = store_machine_capability_secret(
        "acme", "browser-control", "sign-in.buyer.shop.password", secret
    )
    requests, writes = [], []

    def send(endpoint, body, **kwargs):
        requests.append(body)
        assert kwargs["timeout"] >= 75
        assert body["signIn"]["secret_files"] == {"password": str(file)}
        assert body["signIn"]["identity"] == "buyer"
        assert body["signIn"]["sign_in"]["credential_origins"] == (
            "https://identity.example",
        )
        return {
            "success": True,
            "data": {
                "success": True,
                "site": "shop",
                "identity": "buyer",
                "state": "signed_in",
            },
        }

    monkeypatch.setattr(browser_client, "daemon_request", send)
    outcome = steps._execute_step(
        {"action": "sign_in", "site": "shop"}, "https://shop.example", "/tmp", "case"
    )
    assert outcome["data"]["state"] == "signed_in"

    def record(function, requirement, payload, **kwargs):
        writes.append(payload)
        return {"qa_run_id": 1, "qa_artifact_id": 2}

    monkeypatch.setattr(steps, "_dispatch_qa_write", record)
    steps._record_run(1, "browser-check", "pass", json.dumps(outcome))
    steps._complete_run(1, 1, "pass", json.dumps(outcome))
    steps._record_artifact(1, 1, "step", "application/json", {}, json.dumps(outcome))
    assert writes
    for value in [requests, outcome, writes, str(capsys.readouterr())]:
        assert secret not in json.dumps(value)
    assert str(file) not in json.dumps(writes)
