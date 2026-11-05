"""Architecture and DNS contracts for the latest cloud Packs."""

from __future__ import annotations

import base64
from dataclasses import replace
import json

import pytest

from yoke_core.domain.pack_catalog import pack_version_root
from runtime.api.domain.test_webapp_registry_stack import _Recorder, _load_pack_module
from runtime.api.domain.webapp_runner_fleet_test_support import (
    _runner_stack,
    default_runner_stack as default_runner_stack,
)


@pytest.fixture(scope="module")
def vps_module():
    with pytest.MonkeyPatch.context() as patch:
        yield _load_pack_module(patch, _Recorder(), "webapp_vps_stack.py")


@pytest.mark.parametrize(
    "instance_type",
    [
        "a1.medium",
        "t4g.medium",
        "c7gn.xlarge",
        "m7gd.large",
        "c8g.large",
        "m8g.large",
        "r8g.large",
        "x2gd.large",
        "im4gn.large",
        "hpc7g.4xlarge",
        "g5g.xlarge",
        "c99gn.large",
    ],
)
def test_graviton_processor_suffix_selects_arm_ami(vps_module, instance_type):
    assert vps_module._ami_arch_for_instance(instance_type) == "arm64"


@pytest.mark.parametrize(
    "instance_type",
    [
        "t3.medium",
        "c7i.large",
        "m7a.large",
        "g6.xlarge",
        "p5.48xlarge",
        "m7i-flex.large",
        "c7i.largeg",
    ],
)
def test_other_processors_select_x86_ami(vps_module, instance_type):
    assert vps_module._ami_arch_for_instance(instance_type) == "amd64"


@pytest.mark.parametrize(
    ("architecture", "runner_arch", "ami_arch"),
    [
        ("arm64", "arm64", "arm64"),
        ("aarch64", "arm64", "arm64"),
        (" AARCH64 ", "arm64", "arm64"),
        ("x64", "x64", "amd64"),
        ("amd64", "x64", "amd64"),
        ("x86_64", "x64", "amd64"),
    ],
)
def test_runner_architecture_normalization(
    default_runner_stack, architecture, runner_arch, ami_arch
):
    recorder, _ = default_runner_stack
    assert recorder.internals._ami_arch(architecture) == ami_arch
    assert (
        recorder.fleet_config.normalize_runner_architecture(architecture) == runner_arch
    )


@pytest.mark.parametrize(
    "architecture,runner_arch", [("arm64", "arm64"), ("x86_64", "x64")]
)
def test_fleet_ami_host_and_broker_share_normalized_architecture(
    monkeypatch, architecture, runner_arch
):
    recorder, _ = _runner_stack(
        monkeypatch, config_overrides={"architecture": architecture}
    )
    ami_arch = "arm64" if runner_arch == "arm64" else "amd64"
    assert recorder.internals._ami_arch(architecture) == ami_arch
    launch = recorder.single("runnerFleetLaunchTemplate")
    user_data = base64.b64decode(launch.kwargs["user_data"]).decode()
    assert f"RUNNER_ARCH={runner_arch}" in user_data
    broker = recorder.single("runnerFleetGithubBroker")
    assert (
        broker.kwargs["environment"].kwargs["variables"]["RUNNER_ARCHITECTURE"]
        == runner_arch
    )


@pytest.mark.parametrize("architecture", ["", "arm", "armv7", "riscv64", "typo"])
def test_unknown_runner_architecture_refuses(default_runner_stack, architecture):
    recorder, _ = default_runner_stack
    with pytest.raises(
        ValueError, match="unsupported_runner_architecture:.*set architecture"
    ):
        recorder.fleet_config.validate_runner_fleet_configuration(
            replace(recorder.runner_args, architecture=architecture)
        )


def test_unknown_runner_architecture_refuses_before_aws_resources(monkeypatch):
    recorder = _Recorder()
    with pytest.raises(
        ValueError, match="unsupported_runner_architecture:.*set architecture"
    ):
        _runner_stack(
            monkeypatch, recorder=recorder, config_overrides={"architecture": "typo"}
        )
    assert not any(
        resource.resource_type.startswith("aws:") for resource in recorder.resources
    )


def test_vps_docker_dns_uses_only_vpc_independent_resolver():
    source = (
        pack_version_root("vps-hosting") / "ops/provision-ec2.sh.tmpl"
    ).read_text()
    dns = source.split('\'{"dns": ', 1)[1].split("}'", 1)[0]
    assert json.loads(dns) == ["169.254.169.253"]
