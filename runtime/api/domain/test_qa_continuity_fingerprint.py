"""Continuity checks prove declared state before allowing machine QA setup."""

import hashlib
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.qa_continuity_fingerprint import (
    normalize_fingerprint,
    require_continuity_state,
)
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.qa_continuity_fingerprint import check_continuity
from yoke_core.domain.machine_qa_continuity import continuity_failure
from yoke_core.domain.qa_method_config_validation import validate_method_config
from yoke_core.domain.machine_qa_method_contracts import validate_machine_method_config


class LocalControl:
    def run_command(self, argv, *, timeout):
        return subprocess.run(argv, timeout=timeout, text=True, capture_output=True)


def fingerprint(path):
    return {
        "continuity_fingerprint": {
            str(path): hashlib.sha256(b"recorded conversation").hexdigest()
        }
    }


def test_matching_recorded_state_passes_without_exposing_contents(tmp_path):
    path = tmp_path / "conversation.json"
    path.write_bytes(b"recorded conversation")
    evidence = check_continuity(LocalControl(), fingerprint(path))
    assert evidence == {"ok": True, "checked_files": [str(path)]}
    assert "recorded conversation" not in str(evidence)


@pytest.mark.parametrize("state", ["missing", "changed", "directory", "symlink"])
def test_lost_continuity_refuses_before_a_case_starts(tmp_path, state):
    path = tmp_path / "conversation.json"
    if state == "changed":
        path.write_text("another subject reset this host")
    elif state == "directory":
        path.mkdir()
    elif state == "symlink":
        target = tmp_path / "other.json"
        target.write_bytes(b"recorded conversation")
        path.symlink_to(target)
    case = SimpleNamespace(method_config=fingerprint(path))
    result = continuity_failure(SimpleNamespace(control=LocalControl()), case)
    assert result.error_code == "continuity_lost"
    assert result.case_outcome == "blocked_on_precondition"
    assert result.evidence["case_started"] is False
    assert (
        "Restore the required continuity state"
        in result.evidence["continuity_fingerprint"]["recovery"]
    )


@pytest.mark.parametrize(
    "reply", ["not json", '{"ok":true}', '{"ok":false,"failures":[]}']
)
def test_unprovable_checker_reply_refuses(reply):
    control = SimpleNamespace(
        run_command=lambda *a, **k: SimpleNamespace(returncode=0, stdout=reply)
    )
    with pytest.raises(HostControlLocalError, match="could not be checked"):
        check_continuity(control, {"continuity_fingerprint": {"~/state": "a" * 64}})


def test_checker_timeout_refuses():
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("python3", 30)

    with pytest.raises(HostControlLocalError) as caught:
        check_continuity(
            SimpleNamespace(run_command=timeout),
            {"continuity_fingerprint": {"~/state": "a" * 64}},
        )
    assert caught.value.code == "continuity_lost"


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"relative": "a" * 64},
        {"~/../state": "a" * 64},
        {"~/state": "bad"},
        {"/": "a" * 64},
    ],
)
def test_invalid_fingerprints_are_rejected(raw):
    with pytest.raises(ValueError, match="continuity_fingerprint"):
        normalize_fingerprint(raw)


def test_fingerprint_requires_as_is():
    with pytest.raises(ValueError, match="requires starting_state as_is"):
        require_continuity_state(
            {
                "starting_state": "baseline",
                "method_config": {"continuity_fingerprint": {"~/state": "a" * 64}},
            }
        )


@pytest.mark.parametrize("method", ["agent-mission", "machine-state-check"])
def test_method_normalization_retains_recorded_fingerprint(method):
    config = {"continuity_fingerprint": {"~/state": "a" * 64}}
    if method == "agent-mission":
        config["executor"] = "informed_subagent"
    else:
        config["assertions"] = [{"argv": ["true"]}]
    normalized = validate_method_config(method, config)
    if method == "machine-state-check":
        normalized = validate_machine_method_config(
            method, normalized, entry_surface=None, required_completion=None
        )
    assert normalized["continuity_fingerprint"] == config["continuity_fingerprint"]


def test_local_case_refusal_skips_fixture_execution(monkeypatch, tmp_path):
    from runtime.api.domain.test_machine_qa_chain_restore import _contract
    from yoke_core.domain import machine_qa_local_execution as local

    contract = _contract(baselines=[], starting_state="as_is")
    contract.cases[0].method_config.update(fingerprint(tmp_path / "lost"))
    execution = SimpleNamespace(
        control=LocalControl(),
        material=SimpleNamespace(secrets={}),
        reach_baseline=lambda *args: pytest.fail("as_is must not reset the host"),
    )
    monkeypatch.setattr(
        local.HostControlExecutionContract, "model_validate", lambda raw: contract
    )
    monkeypatch.setattr(local, "_execution", lambda *a, **k: execution)

    def forbidden(*args):
        pytest.fail("fixture setup must not run after continuity is lost")

    monkeypatch.setattr(local, "execute_case_with_fixture_lifecycle", forbidden)
    row = local.execute_machine_case_contract({}).payload["results"][0]
    assert row["error_code"] == "continuity_lost"
    assert row["evidence"]["case_started"] is False


def test_continuity_contract_uses_a_protocol_older_runners_reject():
    from typing import Literal
    from pydantic import BaseModel, ValidationError
    from runtime.api.domain.machine_qa_fixture_lifecycle_test_support import (
        case_contract,
    )
    from yoke_contracts.machine_qa_execution import (
        issue_execution_contract,
        HostControlExecutionContract,
        execution_contract_digest,
    )

    case = case_contract()
    case.method_config["continuity_fingerprint"] = {"~/state": "a" * 64}
    contract = issue_execution_contract(
        operation="case",
        lease_id=1,
        lease_key="host:lab",
        project_id=1,
        project="yoke",
        settings={
            "resource_name": "lab",
            "host": "lab.local",
            "user": "tester",
            "os": "linux",
            "operating_notes": "",
        },
        cases=[case.model_dump(mode="json")],
    )
    assert contract.protocol == "host-control-continuity-v1"

    class OlderProtocol(BaseModel):
        protocol: Literal["host-control-v1"]

    with pytest.raises(ValidationError):
        OlderProtocol.model_validate(contract.model_dump(mode="json"))
    stale = contract.model_copy(update={"protocol": "host-control-v1"})
    stale.contract_digest = execution_contract_digest(stale)
    with pytest.raises(ValidationError, match="continuity_runner_required"):
        HostControlExecutionContract.model_validate(stale.model_dump(mode="json"))
