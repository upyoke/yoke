"""Guard inventory and real client/server applicability behavior."""

from __future__ import annotations

import json
import subprocess
import time

import pytest

from yoke_contracts.hook_runner.guard_scope import (
    GUARD_SCOPES,
    GuardScope,
    applicable_chain,
    guard_scope,
)
from yoke_contracts.hook_runner.hook_guard_catalog import GUARD_CATALOG
from yoke_contracts.hook_runner.hook_ordering import HOOK_ORDERING
from yoke_contracts.hook_runner import project_scope
from yoke_core.hooks import runner, run_tail
from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.decision_render import render_claude_decision
from yoke_core.hooks.remote_policy import RunControls
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_harness.hooks import local_subset
from yoke_harness.hooks.deadline import HookDeadline


@pytest.fixture
def scope_repos(tmp_path, monkeypatch):
    managed, other = tmp_path / "managed", tmp_path / "other"
    for root in (managed, other):
        root.mkdir()
        subprocess.run(
            ["git", "-C", str(root), "init", "-b", "main"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "initialize",
            ],
            check=True,
            capture_output=True,
        )
        (root / "source.py").write_text("print('hello')\n")
        subprocess.run(["git", "-C", str(root), "add", "source.py"], check=True)
    config = tmp_path / "config.json"
    config.write_text("{}")
    monkeypatch.setattr(project_scope.machine_config, "config_path", lambda: config)
    monkeypatch.setattr(
        project_scope.machine_config,
        "load_config",
        lambda *_args, **_kwargs: {
            "projects": [{"checkout": str(managed), "project_id": 7}],
        },
    )
    return managed, other


def test_every_catalog_guard_and_chain_guard_has_scope():
    for spec in GUARD_CATALOG:
        assert spec.module in GUARD_SCOPES, spec.module
    for matchers in HOOK_ORDERING.values():
        for chain in matchers.values():
            for module in chain:
                scope = guard_scope(module)
                if (
                    ".lint_" in module
                    or "path_claim_" in module
                    or module.endswith("_gate")
                ):
                    assert scope in GuardScope, module
    assert (
        guard_scope("yoke_core.domain.turn_end_promised_work_gate")
        is GuardScope.PROJECT
    )


def test_unknown_guard_names_its_declaration_recovery():
    with pytest.raises(ValueError, match="hook_guard_scope_missing.*declare machine"):
        applicable_chain(["yoke_core.domain.lint_new_guard"], None)


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
def test_main_commit_facts_ship_only_for_the_managed_checkout(scope_repos, executor):
    """The main-commit guard runs on the authority from the client's git facts.

    The client never denies the commit itself; it ships the staged-commit
    facts only when the checkout belongs to a project, so an unrelated
    repository's main commit is never policed.
    """
    from yoke_contracts.hook_runner.main_commit import CLIENT_GIT_COMMIT_FACTS_KEY

    managed, other = scope_repos
    for root, shipped in ((other, False), (managed, True)):
        payload = {
            "cwd": str(root),
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m change"},
        }
        result = local_subset.evaluate_local_subset(
            "PreToolUse",
            json.dumps(payload),
            executor,
            None,
            HookDeadline(budget_ms=3000, started_at=time.monotonic()),
            collect_facts=True,
        )
        assert result.denied is False, result.stdout
        assert (CLIENT_GIT_COMMIT_FACTS_KEY in result.payload_extra) is shipped


@pytest.mark.parametrize("command", ["git reset --hard", "git clean -fd"])
def test_unrelated_destructive_git_is_not_policed(scope_repos, command):
    _, other = scope_repos
    (other / "source.py").write_text("changed\n")
    (other / "untracked.txt").write_text("keep\n")
    payload = {
        "cwd": str(other),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        json.dumps(payload),
        "codex",
        None,
        HookDeadline(budget_ms=3000, started_at=time.monotonic()),
    )
    assert not result.denied
    assert (other / "untracked.txt").read_text() == "keep\n"


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
def test_unmatched_glob_still_denies_outside_projects(scope_repos, executor):
    _, other = scope_repos
    payload = {
        "cwd": str(other),
        "tool_name": "Bash",
        "shell": "zsh",
        "tool_input": {"command": "cat ./nonexistent/*.missing"},
    }
    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        json.dumps(payload),
        executor,
        None,
        HookDeadline(budget_ms=3000, started_at=time.monotonic()),
    )
    assert result.denied, result.stdout
    assert "glob" in result.stdout.lower()


def test_privacy_guard_still_denies_outside_projects(scope_repos):
    _, other = scope_repos
    payload = {
        "cwd": str(other),
        "tool_name": "Bash",
        "tool_input": {
            "command": "cat /Library/Application\\ Support/com.apple.TCC/TCC.db",
        },
    }
    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        json.dumps(payload),
        "codex",
        None,
        HookDeadline(budget_ms=3000, started_at=time.monotonic()),
    )
    assert result.denied, result.stdout
    assert "privacy" in result.stdout.lower() or "TCC" in result.stdout


@pytest.mark.parametrize(
    "remote,authorized,mapped",
    [(False, None, False), (False, None, True), (True, None, True), (True, 7, False)],
)
def test_engine_filters_by_local_membership_or_authorized_remote_context(
    scope_repos,
    monkeypatch,
    remote,
    authorized,
    mapped,
):
    managed, other = scope_repos
    chain = [
        "yoke_core.domain.lint_local_privacy",
        "yoke_core.domain.lint_main_commit",
        "yoke_core.domain.lint_session_cwd",
        "yoke_core.hooks.session_message_delivery",
    ]
    seen = []
    monkeypatch.setattr(runner, "chain_for", lambda *_a: chain)
    monkeypatch.setattr(runner, "deduplicated_dispatch", lambda *_a, **_k: False)
    monkeypatch.setattr(run_tail, "preflight_remote_registration", lambda **_k: None)
    monkeypatch.setattr(run_tail, "flush_run_tail", lambda **_k: None)
    monkeypatch.setattr(
        runner._mode_gate, "apply_mode", lambda decision, *_a, **_k: decision
    )
    monkeypatch.setattr(
        runner._guard_denial_identity, "bind", lambda decision, *_a, **_k: decision
    )

    def invoke(module, **_kwargs):
        seen.append(module)
        return (
            HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE),
            "",
            None,
            (module, {}),
        )

    monkeypatch.setattr(runner, "invoke_module", invoke)
    capability = AdapterCapability(
        family="claude",
        payload_parser=json.loads,
        decision_renderer=render_claude_decision,
    )
    payload = {
        "cwd": str(managed if mapped else other),
        "project_id": 999,
        "tool_name": "Bash",
    }
    controls = RunControls(
        remote=remote, authorized_project_id=authorized, flush_tail=False
    )
    runner.run_event(
        "PreToolUse",
        capability=capability,
        stdin_data=json.dumps(payload),
        controls=controls,
    )
    expected = (
        chain
        if (authorized is not None if remote else mapped)
        else [chain[0], chain[-1]]
    )
    assert seen == expected


from runtime.harness.test_hook_runner_runner import (  # noqa: E402
    _capability,
    _patch_typed_modules,
    _silence_telemetry,
    _SUBPROC_RUN,
)
from yoke_core.hooks import runner as runner_module  # noqa: E402


def test_ordering_preserved_with_mixed_typed_and_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = ["mod.first", "mod.middle", "mod.third"]
    capability = _capability(
        monkeypatch,
        chain,
        subprocess_modules=frozenset({"mod.middle"}),
    )
    invocations: list[str] = []

    def make_typed(mid: str):
        def evaluate(ctx: HookContext) -> HookDecision:  # noqa: ARG001
            invocations.append(mid)
            return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)

        return evaluate

    class _First:
        evaluate = staticmethod(make_typed("mod.first"))

    class _Third:
        evaluate = staticmethod(make_typed("mod.third"))

    _patch_typed_modules(monkeypatch, {"mod.first": _First, "mod.third": _Third})

    def fake_run(argv, **kwargs):  # noqa: ARG001
        if "mod.middle" in argv:
            invocations.append("mod.middle")
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(project_scope, "project_id_for_payload", lambda _payload: None)
    monkeypatch.setattr(_SUBPROC_RUN, fake_run)
    _silence_telemetry(monkeypatch)

    runner_module.run_event("PreToolUse", capability=capability, stdin_data="")
    assert invocations == ["mod.first", "mod.middle", "mod.third"]


def test_typed_policy_stdout_audit_field_is_appended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle policies can return hook stdout without printing directly."""
    capability = _capability(monkeypatch, ["mod.lifecycle"])

    class _Lifecycle:
        @staticmethod
        def evaluate(context: HookContext) -> HookDecision:  # noqa: ARG001
            return HookDecision(
                outcome=Outcome.AUDIT_ONLY,
                audit_fields={"stdout": "orientation\n"},
            )

    _patch_typed_modules(monkeypatch, {"mod.lifecycle": _Lifecycle})
    _silence_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "SessionStart",
        capability=capability,
        stdin_data="",
    )
    assert exit_code == 0
    assert text == "orientation\n"
