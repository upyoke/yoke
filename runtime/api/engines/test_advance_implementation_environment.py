"""Env-phase provisioning tests for advance_implementation_environment.

AC-21/AC-29 capable-project provisioning chain, the flow-triggered skip,
policy-invalid handling, and push-failure short-circuit.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest import mock

from yoke_core.engines import advance_implementation_environment as env_mod
from yoke_core.domain.ephemeral_substrate import (
    EphemeralPolicy,
    EphemeralPolicyError,
)


def _policy(trigger="github-push", preview_domain="buzzabuzz.com"):
    return EphemeralPolicy(
        project="buzz", deploy_namespace="buzz", trigger=trigger,
        preview_domain=preview_domain,
        host_env="production", api_base_port=9000, web_base_port=4000,
        port_range=100, ttl_hours=24,
    )


def test_env_phase_provisions_capable_project_chain(monkeypatch, tmp_path):
    calls: Dict[str, List[Any]] = {
        "push": [], "create": [], "update_url": [], "update_sha": [],
    }

    with mock.patch(
        "yoke_core.domain.projects_crud.cmd_has_capability",
        return_value=True,
    ), mock.patch.object(
        env_mod, "_git_push",
        lambda repo_root, branch: (
            calls["push"].append((repo_root, branch)) or (True, "")
        ),
    ), mock.patch.object(
        env_mod, "_git_ref_sha", lambda repo_root, ref: "deadbeef",
    ), mock.patch.object(
        env_mod, "load_ephemeral_policy", lambda project: _policy(),
    ), mock.patch.object(
        env_mod, "_item_label", lambda conn, item: "BUZ-42",
    ), mock.patch(
        "yoke_core.domain.ephemeral_env.cmd_create",
        lambda conn, project, branch, item="": (
            calls["create"].append((project, branch, item)) or "77"
        ),
    ), mock.patch(
        "yoke_core.domain.ephemeral_env.cmd_update",
        lambda conn, env_id, field, value: (
            calls[f"update_{'url' if field == 'url' else 'sha'}"].append(
                (env_id, field, value),
            ) or "ok"
        ),
    ):
        outcome, ctx = env_mod.run(
            item={"id": 42, "project": "buzz"},
            branch="YOK-42",
            session_id="s1",
            repo_root=str(tmp_path),
            config_root=str(tmp_path),
        )

    assert outcome == "provisioned"
    assert ctx["env_id"] == 77
    assert ctx["url"] == "https://yok-42.buzzabuzz.com"
    assert ctx["deployed_sha"] == "deadbeef"
    assert calls["push"] == [(str(tmp_path), "YOK-42")]
    assert calls["create"] == [("buzz", "YOK-42", "BUZ-42")]
    assert calls["update_url"] == [(77, "url", "https://yok-42.buzzabuzz.com")]
    assert calls["update_sha"] == [(77, "deployed_sha", "deadbeef")]


def test_env_phase_policy_invalid_for_malformed_capability(tmp_path):
    def _raise(project):
        raise EphemeralPolicyError("missing preview_domain")

    with mock.patch(
        "yoke_core.domain.projects_crud.cmd_has_capability",
        return_value=True,
    ), mock.patch.object(env_mod, "load_ephemeral_policy", _raise):
        outcome, ctx = env_mod.run(
            item={"id": 42, "project": "buzz"},
            branch="YOK-42", session_id="s1", repo_root=str(tmp_path),
            config_root=str(tmp_path),
        )

    assert outcome == "pending:policy-invalid"
    assert "preview_domain" in ctx["error"]


def test_env_phase_skipped_for_flow_triggered_project(tmp_path):
    pushes: List[Any] = []
    with mock.patch(
        "yoke_core.domain.projects_crud.cmd_has_capability",
        return_value=True,
    ), mock.patch.object(
        env_mod, "load_ephemeral_policy",
        lambda project: _policy(trigger="flow"),
    ), mock.patch.object(
        env_mod, "_git_push",
        lambda repo_root, branch: pushes.append(branch) or (True, ""),
    ):
        outcome, ctx = env_mod.run(
            item={"id": 42, "project": "yoke"},
            branch="YOK-42", session_id="s1", repo_root=str(tmp_path),
        )

    assert outcome == "skipped:flow-triggered"
    assert ctx["trigger"] == "flow"
    assert pushes == [], "flow-triggered projects must not push at advance"


def test_env_phase_push_failure_short_circuits_before_env_row(tmp_path):
    create_calls: List[Any] = []
    with mock.patch(
        "yoke_core.domain.projects_crud.cmd_has_capability",
        return_value=True,
    ), mock.patch.object(
        env_mod, "load_ephemeral_policy", lambda project: _policy(),
    ), mock.patch.object(
        env_mod, "_git_push", lambda repo_root, branch: (False, "refused"),
    ), mock.patch(
        "yoke_core.domain.ephemeral_env.cmd_create",
        lambda *a, **kw: create_calls.append(a) or "1",
    ):
        outcome, ctx = env_mod.run(
            item={"id": 42, "project": "buzz"},
            branch="YOK-42", session_id="s1", repo_root=str(tmp_path),
        )
    assert outcome == "pending:push-failed"
    assert ctx["push_error"] == "refused"
    assert create_calls == [], "env row must not be created when push fails"


def test_env_phase_skipped_for_no_capability_project():
    with mock.patch(
        "yoke_core.domain.projects_crud.cmd_has_capability",
        return_value=False,
    ):
        outcome, ctx = env_mod.run(
            item={"id": 42, "project": "yoke"},
            branch="YOK-42", session_id="s1", repo_root="/tmp",
        )
    assert outcome == "skipped:no-capability"
    assert ctx == {"project": "yoke"}


def test_env_phase_skipped_for_no_project():
    with mock.patch(
        "yoke_core.domain.projects_crud.cmd_has_capability",
        return_value=True,
    ) as cap_check:
        outcome, _ctx = env_mod.run(
            item={"id": 42}, branch="YOK-42", session_id="s1", repo_root="/tmp",
        )
    assert outcome == "skipped:no-project"
    cap_check.assert_not_called()
