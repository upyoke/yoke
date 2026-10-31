"""EC2 power calls keyed by instance id, driven through a fake runner."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.deploy_remote import CommandResult
from yoke_core.domain.ec2_instance_power import (
    Ec2InstancePowerError,
    ensure_instance_running,
    instance_public_address,
    stop_instance,
)
from runtime.api.domain.test_deploy_remote import FakeRunner

OK = CommandResult(0, "", "")


def _json(value) -> CommandResult:
    return CommandResult(0, json.dumps(value), "")


def _argvs(runner: FakeRunner) -> list[list[str]]:
    return [call["argv"][2:] for call in runner.calls]


def test_running_instance_is_described_by_id_and_left_alone():
    runner = FakeRunner([_json(["running"])])
    assert ensure_instance_running(runner, "i-1", {}, lambda _l: None) == "running"
    assert _argvs(runner) == [
        [
            "describe-instances",
            "--instance-ids",
            "i-1",
            "--query",
            "Reservations[].Instances[].State.Name",
            "--output",
            "json",
        ]
    ]


def test_stopped_instance_is_started_then_waited():
    runner = FakeRunner([_json(["stopped"]), OK, OK])
    assert ensure_instance_running(runner, "i-1", {}, lambda _l: None) == "stopped"
    assert [argv[0:2] for argv in _argvs(runner)[1:]] == [
        ["start-instances", "--instance-ids"],
        ["wait", "instance-running"],
    ]


def test_stopping_instance_waits_for_stopped_before_starting():
    runner = FakeRunner([_json(["stopping"]), OK, OK, OK])
    ensure_instance_running(runner, "i-1", {}, lambda _l: None)
    assert [argv[0:2] for argv in _argvs(runner)[1:]] == [
        ["wait", "instance-stopped"],
        ["start-instances", "--instance-ids"],
        ["wait", "instance-running"],
    ]


def test_pending_instance_is_only_waited():
    runner = FakeRunner([_json(["pending"]), OK])
    ensure_instance_running(runner, "i-1", {}, lambda _l: None)
    assert [argv[0:2] for argv in _argvs(runner)[1:]] == [["wait", "instance-running"]]


def test_terminated_instance_refuses_without_a_start():
    runner = FakeRunner([_json(["terminated"])])
    with pytest.raises(Ec2InstancePowerError, match="i-1 is terminated"):
        ensure_instance_running(runner, "i-1", {}, lambda _l: None)
    assert len(runner.calls) == 1


def test_unknown_instance_id_names_the_recorded_id():
    runner = FakeRunner([_json([])])
    with pytest.raises(Ec2InstancePowerError, match="check the recorded instance id"):
        ensure_instance_running(runner, "i-1", {}, lambda _l: None)


def test_failed_start_names_instance_action_and_stderr():
    runner = FakeRunner([_json(["stopped"]), CommandResult(1, "", "Denied")])
    with pytest.raises(Ec2InstancePowerError) as exc:
        ensure_instance_running(runner, "i-1", {}, lambda _l: None)
    assert str(exc.value) == "instance i-1: start-instances failed: Denied"


def test_missing_aws_cli_names_install_and_preflight():
    class MissingCli:
        def run(self, argv, **_kwargs):
            raise FileNotFoundError("aws")

    with pytest.raises(Ec2InstancePowerError) as exc:
        ensure_instance_running(MissingCli(), "i-1", {}, lambda _l: None)
    assert "yoke aws preflight" in str(exc.value)


@pytest.mark.parametrize("address", ["54.0.0.1", None])
def test_public_address_reads_the_instance(address):
    runner = FakeRunner([_json([address])])
    assert instance_public_address(runner, "i-1", {}) == address
    assert "i-1" in _argvs(runner)[0]


@pytest.mark.parametrize(
    "answer", [_json([]), _json(["a", "b"]), CommandResult(0, "bad", "")]
)
def test_public_address_refuses_ambiguous_or_non_json_response(answer):
    with pytest.raises(Ec2InstancePowerError):
        instance_public_address(FakeRunner([answer]), "i-1", {})


def test_stop_requests_stop_without_waiting():
    runner = FakeRunner([OK])
    stop_instance(runner, "i-1", {}, lambda _l: None)
    assert _argvs(runner) == [["stop-instances", "--instance-ids", "i-1"]]
