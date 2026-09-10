"""The earlier report tells the truth about what it did and did not check.

An advisory that goes quiet is worse than none: silence reads as a clean
answer. So each of its three outcomes has to stay distinguishable — the
change did not touch the shared surface, the consumer was asked and
answered, or nothing was checked because no scoped credential reached the
run. That last one is the ordinary fork case, and it must say so.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import pytest

from yoke_core.domain.yaml_helper import load_document

from runtime.api.tools import consumer_compatibility_advisory as advisory
from runtime.api.tools import require_platform_consumer_compatibility as gate

REPO_ROOT = Path(__file__).resolve().parents[3]
YOKE_CI = REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml"
MERGE_QUEUE = REPO_ROOT / ".yoke" / "merge-queue.json"
ADVISORY_MODULE = "runtime.api.tools.consumer_compatibility_advisory"
CANDIDATE = "a" * 40
CONTRACT_VERSION_ASSET = (
    "packages/yoke-core/src/yoke_core/ui/static/contract-version.js"
)


class _Scope:
    """The one changed-path scope the repo-contracts job resolves."""

    def __init__(self, paths: Sequence[str]) -> None:
        self.base_sha = "base"
        self.paths = tuple(paths)


def _never_called(*_args: Any, **_kwargs: Any):
    raise AssertionError("the consumer must not be asked in this case")


def _scope_of(monkeypatch: pytest.MonkeyPatch, *paths: str) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(
        advisory, "resolve_changed_path_scope", lambda _root, _base: _Scope(paths),
    )
    monkeypatch.setattr(advisory.gate, "prove", _never_called)


def test_the_watched_surface_is_derived_from_the_shipped_asset_contract() -> None:
    # A hand-kept path list goes stale in silence: the asset moves, the list
    # keeps matching nothing, and the advisory never fires again.
    paths = advisory.host_consumed_paths()

    assert CONTRACT_VERSION_ASSET in paths
    for path in paths:
        assert (REPO_ROOT / path).is_file(), path


def test_a_contract_change_puts_the_consumer_in_play() -> None:
    assert advisory.touches_host_contract([CONTRACT_VERSION_ASSET])
    assert advisory.touches_host_contract(
        ["packages/yoke-core/src/yoke_core/ui/contracts/universe-app.ts"]
    )
    assert advisory.touches_host_contract(["docs/testing-verification.md"]) == ()


def test_a_run_without_the_scoped_credential_says_it_did_not_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # The fork case. Reporting nothing here would read as a clean answer.
    _scope_of(monkeypatch, CONTRACT_VERSION_ASSET)
    monkeypatch.delenv(gate.CONSUMER_TOKEN_ENV, raising=False)

    code = advisory.main(
        ["--base", "origin/main", "--candidate-sha", CANDIDATE, "--dispatch-key", "k"]
    )
    printed = capsys.readouterr().out

    assert code == 0
    assert "NOT CHECKED" in printed
    assert "::warning" in printed


def test_an_unrelated_change_reports_not_applicable_and_asks_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _scope_of(monkeypatch, "docs/testing-verification.md")

    code = advisory.main(
        ["--base", "origin/main", "--candidate-sha", CANDIDATE, "--dispatch-key", "k"]
    )

    assert code == 0
    assert "not applicable" in capsys.readouterr().out


def test_an_unreadable_scope_reports_rather_than_going_quiet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def _explode(_root: Path, _base: str) -> _Scope:
        raise RuntimeError("no such ref")

    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(advisory, "resolve_changed_path_scope", _explode)
    monkeypatch.setattr(advisory.gate, "prove", _never_called)

    code = advisory.main(
        [
            "--base", "origin/nowhere",
            "--candidate-sha", CANDIDATE,
            "--dispatch-key", "k",
        ]
    )
    printed = capsys.readouterr().out

    assert code == 0
    assert "unresolvable" in printed
    assert "::warning" in printed


def test_a_refusal_is_reported_as_a_warning_and_a_non_zero_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _scope_of(monkeypatch, CONTRACT_VERSION_ASSET)
    monkeypatch.setenv(gate.CONSUMER_TOKEN_ENV, "scoped-token")
    monkeypatch.setattr(
        advisory.gate,
        "prove",
        lambda *_a, **_k: (gate.UNPROVEN, "the hosted consumer refused", ""),
    )

    code = advisory.main(
        ["--base", "origin/main", "--candidate-sha", CANDIDATE, "--dispatch-key", "k"]
    )
    printed = capsys.readouterr().out

    assert code == gate.UNPROVEN
    assert "refused" in printed
    assert "::warning" in printed


CONSUMER_ADVISORY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "consumer-compatibility-advisory.yml"
)


def test_the_advisory_runs_as_an_independent_job() -> None:
    # An independent job beats a gate of its own: no new required context,
    # no ruleset, and the job carries no `needs`, so repo-contracts and the
    # shard matrix never wait on it finishing.
    workflow = load_document(YOKE_CI)
    call_job = workflow["jobs"]["consumer_advisory"]

    assert workflow["permissions"] == {"contents": "read"}
    assert not call_job.get("needs")
    assert call_job["uses"] == "./.github/workflows/consumer-compatibility-advisory.yml"
    assert call_job["secrets"] == "inherit"

    repo_contracts = workflow["jobs"]["repo_contracts"]
    token = gate.CONSUMER_TOKEN_ENV
    assert token not in (repo_contracts.get("env") or {})
    assert not any(token in (step.get("env") or {}) for step in repo_contracts["steps"])
    assert not any(
        ADVISORY_MODULE in str(step.get("run", "")) for step in repo_contracts["steps"]
    )


def test_the_called_workflow_carries_the_scoped_credential_on_one_step() -> None:
    called = load_document(CONSUMER_ADVISORY_WORKFLOW)
    job = called["jobs"]["advisory"]
    token = gate.CONSUMER_TOKEN_ENV

    assert called["permissions"] == {"contents": "read"}
    assert token not in (job.get("env") or {})
    carrying = [step for step in job["steps"] if token in (step.get("env") or {})]
    assert len(carrying) == 1
    step = carrying[0]
    assert ADVISORY_MODULE in str(step["run"])
    # Advisory: the calling job's verdict stays the tree contracts.
    assert step["continue-on-error"] is True


def test_no_other_workflow_carries_the_scoped_consumer_credential() -> None:
    # It belongs to the release bridge and this one advisory step. Anywhere
    # else would be a second place to reason about who can reach the consumer.
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    carrying = {
        path.name
        for path in workflows
        if gate.CONSUMER_TOKEN_ENV in path.read_text(encoding="utf-8")
    }

    assert carrying == {
        "consumer-compatibility-advisory.yml",
        "platform-release-bridge.yml",
    }


def test_the_advisory_job_carries_no_required_status_check() -> None:
    # Independence buys nothing if the queue starts waiting on it anyway.
    declared = json.loads(MERGE_QUEUE.read_text(encoding="utf-8"))
    contexts = {
        str(entry["context"])
        for rule in declared["ruleset"]["rules"]
        if rule["type"] == "required_status_checks"
        for entry in rule["parameters"]["required_status_checks"]
    }

    assert "consumer-advisory" not in contexts
    assert not any("consumer-compatibility-advisory" in c for c in contexts)
