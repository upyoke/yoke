"""Container registry repository and lifecycle declarations."""

from __future__ import annotations

import json

from runtime.api.domain.test_webapp_registry_stack import _registry_stack


def test_repository_declares_scan_push_mutability_and_force_delete(monkeypatch):
    recorder, _stack = _registry_stack(monkeypatch)
    repo = recorder.single("containerRepository")
    assert repo.kwargs["name"] == "yoke-core"
    assert repo.kwargs["image_tag_mutability"] == "MUTABLE"
    assert repo.kwargs["force_delete"] is True
    scanning = repo.kwargs["image_scanning_configuration"]
    assert scanning.kwargs == {"scan_on_push": True}
    assert repo.kwargs["tags"] == {"project": "yoke"}


def test_lifecycle_policy_expires_untagged_and_caps_tagged_history(monkeypatch):
    recorder, _stack = _registry_stack(monkeypatch)
    lifecycle = recorder.single("containerRepositoryLifecycle")
    assert lifecycle.kwargs["repository"] == "yoke-core"
    rules = json.loads(lifecycle.kwargs["policy"])["rules"]
    assert [rule["rulePriority"] for rule in rules] == [1, 2]
    untagged, tagged = rules
    assert untagged["selection"]["tagStatus"] == "untagged"
    assert untagged["action"] == {"type": "expire"}
    assert tagged["selection"]["tagStatus"] == "tagged"
    assert tagged["selection"]["countType"] == "imageCountMoreThan"
    assert tagged["selection"]["countNumber"] == 20
    assert tagged["action"] == {"type": "expire"}


def test_outputs_exported_and_registered(monkeypatch):
    recorder, stack = _registry_stack(monkeypatch)
    expected = {
        "containerRepositoryUrl",
        "containerRepositoryName",
        "containerRegistryId",
    }
    assert set(recorder.exports) == expected
    assert set(stack.registered_outputs) == expected
    assert recorder.exports["containerRepositoryName"] == "yoke-core"
    assert stack.component_type == "webapp:infra:WebappRegistryStack"
