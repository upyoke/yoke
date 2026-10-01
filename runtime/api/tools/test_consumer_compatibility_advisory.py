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
MODEL_REFERENCE_REVISION_CHANGE = (
    "packages/yoke-contracts/src/yoke_contracts/model_reference_catalog.py",
    "packages/yoke-core/src/yoke_core/domain/model_reference_store.py",
    "packages/yoke-core/src/yoke_core/domain/schema_init.py",
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
        advisory,
        "resolve_changed_path_scope",
        lambda _root, _base: _Scope(paths),
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
    assert advisory.touches_hosted_consumer_surface([CONTRACT_VERSION_ASSET])
    assert advisory.touches_hosted_consumer_surface(
        ["packages/yoke-core/src/yoke_core/ui/contracts/universe-app.ts"]
    )
    assert (
        advisory.touches_hosted_consumer_surface(["docs/testing-verification.md"]) == ()
    )


def test_a_model_reference_revision_change_puts_the_consumer_in_play() -> None:
    assert advisory.touches_hosted_consumer_surface(
        MODEL_REFERENCE_REVISION_CHANGE
    ) == (MODEL_REFERENCE_REVISION_CHANGE)


@pytest.mark.parametrize(
    "path",
    [
        "packages/yoke-core/src/yoke_core/domain/session_control_schema.py",
        "packages/yoke-core/src/yoke_core/domain/schema_init_columns.py",
        "packages/yoke-core/src/yoke_core/domain/migrations/0047_example.py",
    ],
)
def test_control_plane_schema_changes_put_the_consumer_in_play(path: str) -> None:
    assert advisory.touches_hosted_consumer_surface([path]) == (path,)


def test_an_unrelated_domain_change_does_not_put_the_consumer_in_play() -> None:
    path = "packages/yoke-core/src/yoke_core/domain/sessions_list_rows.py"

    assert advisory.touches_hosted_consumer_surface([path]) == ()


def test_a_run_without_the_scoped_credential_says_it_did_not_check(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The fork case. Reporting nothing here would read as a clean answer.
    _scope_of(monkeypatch, CONTRACT_VERSION_ASSET)
    monkeypatch.delenv(gate.CONSUMER_TOKEN_ENV, raising=False)

    code = advisory.main(["--base", "origin/main", "--candidate-sha", CANDIDATE])
    printed = capsys.readouterr().out

    assert code == 0
    assert "NOT CHECKED" in printed
    assert "::warning" in printed


def test_an_unrelated_change_reports_not_applicable_and_asks_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _scope_of(monkeypatch, "docs/testing-verification.md")

    code = advisory.main(["--base", "origin/main", "--candidate-sha", CANDIDATE])

    assert code == 0
    assert "not applicable" in capsys.readouterr().out


def test_an_unreadable_scope_reports_rather_than_going_quiet(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _explode(_root: Path, _base: str) -> _Scope:
        raise RuntimeError("no such ref")

    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(advisory, "resolve_changed_path_scope", _explode)
    monkeypatch.setattr(advisory.gate, "prove", _never_called)

    code = advisory.main(
        [
            "--base",
            "origin/nowhere",
            "--candidate-sha",
            CANDIDATE,
        ]
    )
    printed = capsys.readouterr().out

    assert code == 0
    assert "unresolvable" in printed
    assert "::warning" in printed


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out"])
def test_a_refusal_is_reported_as_a_warning_and_a_non_zero_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    conclusion: str,
) -> None:
    _scope_of(monkeypatch, *MODEL_REFERENCE_REVISION_CHANGE)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv(gate.CONSUMER_TOKEN_ENV, "scoped-token")

    consumer_revision = "b" * 40

    def _refuse(
        candidate: str,
        consumer_ref: str,
        *,
        timeout_sec: int,
        exact_pair: bool,
    ) -> tuple[int, str, str]:
        assert candidate == CANDIDATE
        assert consumer_ref == gate.CONSUMER_TRUNK_REF
        assert timeout_sec == 1800
        assert exact_pair is False
        return gate.classify(
            {
                "state": "failed",
                "conclusion": conclusion,
                "head_sha": consumer_revision,
                "html_url": "https://example.invalid/platform-run/42",
            },
            candidate_sha=candidate,
            consumer_sha=consumer_ref,
            run_id="42",
            exact_pair=False,
        )

    monkeypatch.setattr(
        advisory.gate,
        "prove",
        _refuse,
    )

    code = advisory.main(["--base", "origin/main", "--candidate-sha", CANDIDATE])
    printed = capsys.readouterr().out

    assert code == gate.UNPROVEN
    assert CANDIDATE in printed
    assert consumer_revision in printed
    assert f"concluded {conclusion}" in printed
    assert f"concluded {conclusion}" in summary.read_text()
    assert "https://example.invalid/platform-run/42" in printed
    assert "::warning" in printed


CONSUMER_ADVISORY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "consumer-compatibility-advisory.yml"
)


def test_advisory_timeout_cannot_cancel_the_required_qa_workflow() -> None:
    # QA adopts the WHOLE yoke-ci run conclusion. Job-level continue-on-error
    # did not isolate a reusable advisory's timeout from that conclusion.
    required = load_document(YOKE_CI)
    evidence = load_document(CONSUMER_ADVISORY_WORKFLOW)
    assert evidence["name"] != required["name"]
    assert set(evidence[True]) == {
        "pull_request",
        "merge_group",
        "push",
        "workflow_dispatch",
    }
    assert evidence[True]["pull_request"]["branches"] == ["main"]
    assert evidence[True]["push"]["branches"] == ["main"]
    assert evidence["concurrency"]["group"] == (
        "${{ github.workflow }}-${{ github.ref }}"
    )
    assert set(required["jobs"]) == {
        "repo_contracts",
        "reuse_coverage",
        "test_shard",
        "browser_runtime",
        "container",
    }
    for job in required["jobs"].values():
        assert "consumer" not in str(job)
        assert not job.get("continue-on-error")
    assert required["permissions"] == {"contents": "read"}


def test_advisory_records_its_own_failures_with_one_scoped_credential() -> None:
    workflow = load_document(CONSUMER_ADVISORY_WORKFLOW)
    job = workflow["jobs"]["advisory"]
    token = gate.CONSUMER_TOKEN_ENV

    assert workflow["name"] == "consumer-compatibility-advisory"
    assert workflow["permissions"] == {"contents": "read"}
    assert job["if"] == "github.repository == 'upyoke/yoke'"
    assert not job.get("needs")
    assert not job.get("continue-on-error")
    assert token not in (job.get("env") or {})
    carrying = [step for step in job["steps"] if token in (step.get("env") or {})]
    assert len(carrying) == 1
    step = carrying[0]
    assert ADVISORY_MODULE in str(step["run"])
    assert step["env"][token] == "${{ secrets." + token + " }}"
    assert not step.get("continue-on-error")


def test_no_other_workflow_carries_the_scoped_consumer_credential() -> None:
    # It belongs to the release bridge and the one advisory step. Anywhere
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
