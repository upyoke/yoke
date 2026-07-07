"""Tests for the pulumi preview invariant assertions (real --json shapes).

Fixture shapes mirror live ``pulumi preview --json`` output observed on
the yoke-stage stack 2026-06-10: ``same`` steps are elided, each step
carries ``op``/``urn``/``newState.type``/``newState.inputs`` with
camelCase provider input keys.
"""

from __future__ import annotations

from yoke_core.tools.pulumi_preview_assert import assert_preview

_STACK_URN = "urn:pulumi:yoke-stage::webapp-infra"
_GUARD_URN = (
    f"{_STACK_URN}::webapp:infra:WebappEnvironmentStack$"
    "pulumi-python:dynamic:Resource::databaseMasterSecretRotationDisabled"
)
_CLUSTER_URN = (
    f"{_STACK_URN}::webapp:infra:WebappEnvironmentStack$"
    "aws:rds/cluster:Cluster::databaseCluster"
)


def _cluster_step(op="update", *, pause=1800, manage=True):
    return {
        "op": op,
        "urn": _CLUSTER_URN,
        "newState": {
            "type": "aws:rds/cluster:Cluster",
            "inputs": {
                "manageMasterUserPassword": manage,
                "serverlessv2ScalingConfiguration": {
                    "minCapacity": 0,
                    "maxCapacity": 4,
                    "secondsUntilAutoPause": pause,
                },
            },
        },
    }


def _guard_step(op="same"):
    return {
        "op": op,
        "urn": _GUARD_URN,
        "newState": {"type": "pulumi-python:dynamic:Resource", "inputs": {}},
    }


def _instance_step(op="update"):
    return {
        "op": op,
        "urn": f"{_STACK_URN}::...$aws:ec2/instance:Instance::vpsInstance",
        "newState": {"type": "aws:ec2/instance:Instance", "inputs": {}},
    }


class TestAssertPreview:
    def test_declared_db_with_guard_passes(self):
        payload = {"steps": [_cluster_step(), _guard_step(), _instance_step()]}
        assert assert_preview(payload) == []

    def test_no_db_steps_trivially_passes(self):
        """pulumi --json elides same steps: a no-database-diff preview
        carries no cluster step and the assertions bite only when the
        database resources are actually changing."""
        payload = {"steps": [_instance_step("update")]}
        assert assert_preview(payload) == []

    def test_guard_delete_fails(self):
        payload = {"steps": [_cluster_step(), _guard_step("delete")]}
        violations = assert_preview(payload)
        assert any("rotation guard" in v for v in violations)

    def test_cluster_without_guard_fails(self):
        payload = {"steps": [_cluster_step()]}
        violations = assert_preview(payload)
        assert any("no\ndatabaseMasterSecretRotationDisabled" in v
                   or "databaseMasterSecretRotationDisabled" in v
                   for v in violations)

    def test_missing_auto_pause_fails(self):
        step = _cluster_step()
        del step["newState"]["inputs"]["serverlessv2ScalingConfiguration"]
        payload = {"steps": [step, _guard_step()]}
        violations = assert_preview(payload)
        assert any("secondsUntilAutoPause" in v for v in violations)

    def test_rotation_flip_fails(self):
        payload = {"steps": [_cluster_step(manage=False), _guard_step()]}
        violations = assert_preview(payload)
        assert any("manageMasterUserPassword" in v for v in violations)

    def test_cluster_replace_fails(self):
        payload = {"steps": [_cluster_step("replace"), _guard_step()]}
        violations = assert_preview(payload)
        assert any("database identity" in v for v in violations)

    def test_instance_replace_fails(self):
        payload = {
            "steps": [
                _cluster_step(), _guard_step(),
                _instance_step("create-replacement"),
            ]
        }
        violations = assert_preview(payload)
        assert any("AMI pin" in v for v in violations)

    def test_not_a_preview_payload_fails(self):
        assert assert_preview({}) != []
