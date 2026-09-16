"""The Pack must publish a release preview under the name it is handed.

Yoke knows a release preview's URL before the deploy workflow reports one —
that is the only way the receipt can ask the preview which commit it serves.
The name therefore travels as its own dispatch input and is published
verbatim; the two sides once derived it independently, each hashing a
different value, and nothing at runtime caught it: the dispatch succeeded,
the preview stood up somewhere, and the probe read a host serving nothing.

These run the Pack's own shipped guard against the engine's Python.
"""

from __future__ import annotations

import subprocess
import sys

from pathlib import Path

import pytest

from yoke_core.domain import json_helper
from yoke_core.domain.ephemeral_substrate import (
    is_release_preview_slug,
    release_preview_slug,
)

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "packs/ephemeral-environments"

#: The version that carries the recorded preview name as its own dispatch
#: input. Later versions inherit the contract, so the floor is pinned and the
#: assertions follow whichever version the manifest publishes as latest.
RELEASE_PREVIEW_FLOOR = "1.3.0"

PREVIEW_NAMES = [
    "run-20260915-001",
    "run-20260915-001-web",
    "run-20261231-099",
    "run-20260101-0001-api-two",
]


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _latest() -> str:
    manifest = json_helper.loads_text((PACK / "pack.json").read_text(encoding="utf-8"))
    return manifest["latest_version"]


def _files() -> Path:
    return PACK / "versions" / _latest() / "files"


def _workflow(name: str) -> str:
    return (_files() / ".github/workflows" / name).read_text(encoding="utf-8")


def _guard(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_files() / "ops/frozen_preview_occupancy.py"), *args],
        capture_output=True,
        text=True,
    )


def test_the_published_version_still_carries_release_previews() -> None:
    assert _version_key(_latest()) >= _version_key(RELEASE_PREVIEW_FLOOR)


@pytest.mark.parametrize("preview_slug", PREVIEW_NAMES)
def test_the_pack_guard_publishes_the_name_it_is_handed(preview_slug: str) -> None:
    """Executed, not pattern-matched: reading the guard would pass against
    one that quietly transformed the name it received."""
    resolved = _guard(
        "resolve", "--commit-sha", "a" * 40, "--preview-slug", preview_slug
    )
    assert resolved.returncode == 0, resolved.stderr
    assert f"occupancy_slug={preview_slug}" in resolved.stdout
    assert f"occupancy_slug={release_preview_slug(preview_slug)}" in resolved.stdout


def test_the_pack_guard_reserves_the_same_namespace_the_engine_does() -> None:
    """Both sides refuse a branch that resolves into it, so agreeing on the
    shape is what keeps a branch out of a candidate's occupancy."""
    refused = _guard("assert-unreserved", "--slug", "run-20260915-001")
    assert refused.returncode == 1
    assert "reserved for frozen release previews" in refused.stderr
    assert is_release_preview_slug("run-20260915-001")

    allowed = _guard("assert-unreserved", "--slug", "run-2026915-001")
    assert allowed.returncode == 0
    assert not is_release_preview_slug("run-2026915-001")


def test_the_pack_guard_refuses_a_name_outside_that_namespace() -> None:
    """A preview named anything else is unprotected: a branch of that name
    would slugify straight onto it."""
    refused = _guard(
        "resolve", "--commit-sha", "a" * 40, "--preview-slug", "preview-for-main"
    )
    assert refused.returncode == 1
    assert "reserved release shape" in refused.stderr


def test_the_workflow_resolves_the_name_through_the_shipped_guard() -> None:
    """One resolver, in a file the install places and the tests execute —
    inline shell in three workflows would be three chances to drift."""
    body = _workflow("{{project_name}}-ephemeral.yml")
    assert "ops/frozen_preview_occupancy.py resolve" in body


def test_the_correlation_token_never_names_the_preview() -> None:
    """It is scoped to one dispatch attempt and is replaced before the POST,
    so naming the preview after it published one host and probed another."""
    body = _workflow("{{project_name}}-ephemeral.yml")
    resolver = body[body.index("- name: Resolve preview slug and candidate"):]
    assert "YOKE_DISPATCH_ID" not in resolver
    assert "yoke_dispatch_id" not in _workflow("{{project_name}}-ephemeral-run.yml")


def test_both_dispatch_inputs_are_declared_and_reach_the_guard() -> None:
    """The requirement itself is enforced in the guard and executed there;
    what this pins is that the workflow declares both and hands both over."""
    body = _workflow("{{project_name}}-ephemeral.yml")
    assert "commit_sha:" in body and "preview_slug:" in body
    assert '--commit-sha "$COMMIT_SHA"' in body
    assert '--preview-slug "$PREVIEW_SLUG"' in body


def test_the_frozen_candidate_is_what_gets_checked_out() -> None:
    """Otherwise the preview serves whatever the ref points at by the time
    the job runs, and the receipt's proof is about a different commit."""
    entry = _workflow("{{project_name}}-ephemeral.yml")
    run = _workflow("{{project_name}}-ephemeral-run.yml")
    assert "candidate_sha: ${{ needs.prepare.outputs.candidate_sha }}" in entry
    assert "candidate_sha:" in run
    assert "ref: ${{ inputs.candidate_sha }}" in run


def test_a_release_preview_is_never_cancelled_in_flight() -> None:
    """Two dispatches under one name carry the same frozen candidate, so the
    later has nothing different to deploy while the earlier may already be
    serving a review."""
    body = _workflow("{{project_name}}-ephemeral.yml")
    assert "cancel-in-progress: ${{ github.event.inputs.preview_slug == '' }}" in body


def test_teardown_addresses_a_release_preview_by_its_recorded_name() -> None:
    body = _workflow("{{project_name}}-ephemeral-teardown.yml")
    assert "preview_slug:" in body
    assert "ops/frozen_preview_occupancy.py teardown-slug" in body


def test_teardown_proves_ownership_before_removing_anything() -> None:
    """An occupancy a caller cannot prove it owns is one somebody else is
    still being shown."""
    body = _workflow("{{project_name}}-ephemeral-teardown.yml")
    guard = body.index("frozen_preview_occupancy.py check-cleanup")
    assert guard < body.index("docker compose"), "ownership is checked first"


def test_the_deploy_claims_the_occupancy_before_any_mutation() -> None:
    """Including the fast path, which rsyncs into the same directory: a
    guard that runs after the write has already lost the candidate."""
    body = _workflow("{{project_name}}-ephemeral-run.yml")
    claim = body.index("- name: Claim the preview occupancy")
    assert claim < body.index("- name: Create ephemeral directory")
    assert claim < body.index("- name: Rsync app and docker-compose")
    assert claim < body.index("- name: Deploy ephemeral environment (fast-path rebuild)")
    # Guarded by branch_exists alone — never by the fast-path flag, which is
    # exactly the branch that would skip it.
    claim_step = body[claim:body.index("- name: Create ephemeral directory")]
    assert "fast_path" not in claim_step


@pytest.mark.parametrize(
    "workflow",
    ["{{project_name}}-ephemeral-run.yml", "{{project_name}}-ephemeral-teardown.yml"],
)
def test_no_caller_value_is_interpolated_into_a_remote_command(workflow: str) -> None:
    """The preview name is a value a caller supplies, and one carrying an
    apostrophe would have ended its argument inside the quoted remote command
    and run whatever followed. Values reach the host on stdin."""
    body = _workflow(workflow)
    guarded = [
        line for line in body.splitlines()
        if "frozen_preview_occupancy.py claim" in line
        or "frozen_preview_occupancy.py check-cleanup" in line
    ]
    assert guarded, "expected a guarded remote invocation to inspect"
    for line in guarded:
        command = line[line.index("ssh -o LogLevel=ERROR"):]
        for name in ("PREVIEW_SLUG", "CANDIDATE_SHA", "SLUG"):
            assert f"${name}" not in command, f"{name} reaches the remote command line"
        assert "--preview-root" in command
        assert line.lstrip().startswith("printf '%s"), "values are piped in"


def test_a_branch_slug_in_the_reserved_namespace_is_refused_again_downstream() -> None:
    """The caller resolves it, and the reusable job refuses it anyway rather
    than trusting whoever called it."""
    body = _workflow("{{project_name}}-ephemeral-run.yml")
    assert "assert-unreserved --slug" in body


def test_branch_previews_still_deploy_their_branch_head() -> None:
    """The release path must not have changed what a development preview
    does — a push still deploys that branch's head under its own slug."""
    body = _workflow("{{project_name}}-ephemeral.yml")
    assert "branches-ignore:" in body
    assert '--branch "$BRANCH_NAME"' in body
    assert '--github-sha "$GIT_HEAD_SHA"' in body
