"""Declared repository Actions policies: validation, drift and convergence."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from yoke_core.domain import actions_policy_apply as policy_apply
from yoke_core.domain import merge_queue_declaration as decl
from yoke_core.domain.actions_policy_declaration import diff_policies
from yoke_core.domain.gh_rest_transport import RestAuthError, RestTransportError

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cla_policy(**overrides):
    policy = {
        "name": "cla-pull-request-target",
        "enforcement": "active",
        "conditions": {
            "workflow_path": {"include": [".github/workflows/cla.yml"], "exclude": []}
        },
        "rules": [
            {
                "type": "restrict_action_events",
                "parameters": {
                    "allowed_events": ["pull_request_target", "issue_comment", "merge_group"]
                },
            }
        ],
    }
    policy.update(overrides)
    return policy


def _broad_hand_made(policy_id=12372):
    return {
        "id": policy_id,
        "name": "Allow all workflow events (incl. pull_request_target)",
        "source_type": "Repository",
        "enforcement": "active",
        "conditions": {"workflow_path": {"include": ["~ALL"], "exclude": []}},
        "rules": [
            {
                "type": "restrict_action_events",
                "parameters": {"allowed_events": ["pull_request_target", "push"]},
            }
        ],
    }


class FakePolicies:
    """In-memory GitHub repository Actions policies, recording writes."""

    def __init__(self, monkeypatch, live=()):
        self.live = {row["id"]: copy.deepcopy(row) for row in live}
        self.writes: list[tuple[str, object]] = []
        self.next_id = 50000
        for name in ("list_repository_policies", "get_policy", "create_policy",
                     "update_policy", "delete_policy"):
            monkeypatch.setattr(policy_apply.rest, name, getattr(self, name))

    def list_repository_policies(self, owner, repo, *, token):
        return [{"id": pid, "name": row["name"]} for pid, row in self.live.items()]

    def get_policy(self, owner, repo, policy_id, *, token):
        return copy.deepcopy(self.live[policy_id])

    def create_policy(self, owner, repo, body, *, token):
        self.next_id += 1
        self.live[self.next_id] = {"id": self.next_id, **copy.deepcopy(dict(body))}
        self.writes.append(("create", body["name"]))
        return self.live[self.next_id]

    def update_policy(self, owner, repo, policy_id, body, *, token):
        self.live[policy_id] = {"id": policy_id, **copy.deepcopy(dict(body))}
        self.writes.append(("update", policy_id))
        return self.live[policy_id]

    def delete_policy(self, owner, repo, policy_id, *, token):
        del self.live[policy_id]
        self.writes.append(("delete", policy_id))


def _converge(declared, *, preview=False):
    return policy_apply.converge_policies(
        declared, owner="upyoke", repo="yoke", token="tok", preview=preview,
    )


def test_repository_declaration_allows_pull_request_target_only_for_cla():
    declared = decl.load_declaration(REPO_ROOT / ".yoke" / "merge-queue.json")
    policies = declared["actions_policies"]
    assert len(policies) == 1
    policy = policies[0]
    assert policy["conditions"]["workflow_path"] == {
        "include": [".github/workflows/cla.yml"], "exclude": [],
    }
    (rule,) = policy["rules"]
    assert rule["type"] == "restrict_action_events"
    assert "pull_request_target" in rule["parameters"]["allowed_events"]
    workflows = REPO_ROOT / ".github" / "workflows"
    users = sorted(
        path.name for path in workflows.glob("*.y*ml")
        if "pull_request_target" in path.read_text(encoding="utf-8")
    )
    assert users == ["cla.yml"]


@pytest.mark.parametrize(
    "policies, message",
    [
        ({}, "must be a list"),
        ([{"enforcement": "active", "rules": [{"type": "x"}]}], "requires a name"),
        ([_cla_policy(), _cla_policy()], "repeats policy name"),
        ([_cla_policy(enforcement="on")], "enforcement must be one of"),
        ([_cla_policy(rules=[])], "non-empty rules list"),
        ([_cla_policy(conditions=[])], "conditions must be an object"),
    ],
)
def test_malformed_policies_refuse_with_the_reason(policies, message):
    payload = {"schema": 1, "ruleset": {"name": "q", "rules": [{"type": "merge_queue"}]},
               "repository": {"allow_auto_merge": True}, "actions_policies": policies}
    with pytest.raises(decl.MergeQueueDeclarationError, match=message):
        decl.parse_declaration(json.dumps(payload))


def test_live_list_order_is_not_drift():
    live = {"id": 7, **_cla_policy()}
    live["rules"][0]["parameters"]["allowed_events"].sort()
    assert diff_policies([_cla_policy()], [live]) == []


def test_drift_names_missing_changed_and_undeclared_policies():
    changed = {"id": 7, **_cla_policy(enforcement="evaluate")}
    changed["conditions"]["workflow_path"]["include"] = ["~ALL"]
    assert diff_policies([_cla_policy()], [changed]) == [
        "actions policy 'cla-pull-request-target' enforcement drifted "
        "(declared='active'; live='evaluate')",
        "actions policy 'cla-pull-request-target' conditions drifted "
        '(declared={"workflow_path":{"exclude":[],"include":[".github/workflows/cla.yml"]}}; '
        'live={"workflow_path":{"exclude":[],"include":["~ALL"]}})',
    ]
    problems = diff_policies([_cla_policy()], [_broad_hand_made()])
    assert problems == [
        "actions policy 'cla-pull-request-target' is missing live",
        "live actions policy 'Allow all workflow events (incl. pull_request_target)' "
        "(id=12372) is not declared",
    ]


def test_preview_plans_without_writing(monkeypatch):
    fake = FakePolicies(monkeypatch, [_broad_hand_made()])
    result = _converge([_cla_policy()], preview=True)
    assert result["changed"] is True
    assert result["actions"] == [
        "create actions policy 'cla-pull-request-target'",
        "delete undeclared actions policy "
        "'Allow all workflow events (incl. pull_request_target)' id=12372",
    ]
    assert fake.writes == []


def test_apply_replaces_the_broad_policy_creating_before_deleting(monkeypatch):
    fake = FakePolicies(monkeypatch, [_broad_hand_made()])
    result = _converge([_cla_policy()])
    assert fake.writes == [("create", "cla-pull-request-target"), ("delete", 12372)]
    assert [row["name"] for row in fake.live.values()] == ["cla-pull-request-target"]
    assert result["changed"] is True
    again = _converge([_cla_policy()])
    assert again["changed"] is False
    assert again["actions"] == ["actions policies already match (1 declared)"]
    assert fake.writes == [("create", "cla-pull-request-target"), ("delete", 12372)]


def test_apply_updates_a_drifted_policy_in_place(monkeypatch):
    fake = FakePolicies(monkeypatch, [{"id": 7, **_cla_policy(enforcement="disabled")}])
    _converge([_cla_policy()])
    assert fake.writes == [("update", 7)]
    assert fake.live[7]["enforcement"] == "active"


def test_an_empty_list_deletes_every_repository_policy(monkeypatch):
    fake = FakePolicies(monkeypatch, [_broad_hand_made()])
    _converge([])
    assert fake.writes == [("delete", 12372)] and fake.live == {}


def test_apply_raises_when_live_state_still_drifts(monkeypatch):
    fake = FakePolicies(monkeypatch)
    monkeypatch.setattr(policy_apply.rest, "create_policy", lambda *a, **k: {})
    with pytest.raises(RestTransportError, match="still drifts: .*missing live"):
        _converge([_cla_policy()])
    assert fake.live == {}


def test_a_refused_write_names_the_permission_to_grant(monkeypatch):
    FakePolicies(monkeypatch, [_broad_hand_made()])

    def _refuse(*a, **k):
        raise RestAuthError("Resource not accessible by integration", status=403)

    monkeypatch.setattr(policy_apply.rest, "create_policy", _refuse)
    with pytest.raises(RestAuthError) as caught:
        _converge([_cla_policy()])
    assert "actions policy write refused for upyoke/yoke" in str(caught.value)
    assert "Administration: write" in str(caught.value)
    assert caught.value.status == 403
