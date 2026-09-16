"""The Pack's published preview naming must equal the engine's.

Yoke derives a release preview's URL before the deploy workflow reports
one — that is the only way the receipt can ask the preview which commit it
serves. So the two derivations are one contract with two implementations,
and nothing at runtime would catch them drifting: the dispatch would
succeed, the preview would stand up somewhere, and the probe would read a
host serving something else, or nothing.

These run the Pack's own shell against the engine's Python.
"""

from __future__ import annotations

import shutil
import subprocess

from pathlib import Path

import pytest

from yoke_core.domain import json_helper
from yoke_core.domain.ephemeral_substrate import (
    frozen_preview_slug,
    is_frozen_preview_slug,
    slugify_branch,
)

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "packs/ephemeral-environments"

#: The version that introduced frozen release previews. Later versions
#: inherit the contract, so the floor is pinned and the assertions follow
#: whichever version the manifest currently publishes as latest.
RELEASE_PREVIEW_FLOOR = "1.2.0"

IDENTITIES = [
    "deploy:sample:run-20260915-001:preview",
    "deploy:sample:run-20260915-001:release-preview",
    "deploy:other:run-20261231-099:preview",
    "a",
]


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _latest() -> str:
    manifest = json_helper.loads_text((PACK / "pack.json").read_text(encoding="utf-8"))
    return manifest["latest_version"]


def _workflow(name: str) -> str:
    return (
        PACK / "versions" / _latest() / "files/.github/workflows" / name
    ).read_text(encoding="utf-8")


def test_the_published_version_still_carries_release_previews() -> None:
    assert _version_key(_latest()) >= _version_key(RELEASE_PREVIEW_FLOOR)


def _digest_pipeline() -> str:
    """The Pack's own digest pipeline, on whatever tool this machine has.

    The workflow runs on Linux and says ``sha256sum``; a developer machine
    may only ship ``shasum``. Both compute the same digest, so substituting
    the tool keeps this an execution of the Pack's algorithm rather than a
    reading of it — and the literal form the workflow uses is asserted
    separately, so a drift in either is still caught.
    """
    if shutil.which("sha256sum"):
        return 'printf %s "$1" | sha256sum | cut -c1-32'
    if shutil.which("shasum"):
        return 'printf %s "$1" | shasum -a 256 | cut -c1-32'
    pytest.skip("no sha256 tool available to execute the Pack's derivation")


@pytest.mark.parametrize("identity", IDENTITIES)
def test_the_pack_shell_derives_the_engine_slug(identity: str) -> None:
    """Executed, not pattern-matched: a regex over the workflow would pass
    against a derivation that computes a different digest."""
    completed = subprocess.run(
        ["sh", "-c", _digest_pipeline(), "sh", identity],
        capture_output=True,
        text=True,
        check=True,
    )
    digest = completed.stdout.strip()
    assert len(digest) == 32, f"digest pipeline produced {digest!r}"
    assert f"rel-{digest}" == frozen_preview_slug(identity)


def test_the_workflow_hashes_the_identity_through_the_shipped_guard() -> None:
    """One derivation, in a file the install places and the tests execute —
    inline shell in three workflows would be three chances to drift."""
    body = _workflow("{{project_name}}-ephemeral.yml")
    assert "ops/frozen_preview_occupancy.py resolve" in body
    # Ports are a pure function of the slug and were always derived here; the
    # identity is what must be hashed in exactly one place.
    assert "YOKE_DISPATCH_ID" not in body[body.index("Compute port offsets"):]


def test_a_release_preview_slug_is_unreachable_by_any_branch_name() -> None:
    """Which is what stops a branch from taking over a candidate's URL."""
    for identity in IDENTITIES:
        frozen = frozen_preview_slug(identity)
        assert is_frozen_preview_slug(frozen)
        assert slugify_branch(identity) != frozen


def test_both_dispatch_inputs_are_declared_and_reach_the_guard() -> None:
    """The requirement itself is enforced in the guard and executed there;
    what this pins is that the workflow declares both and hands both over."""
    body = _workflow("{{project_name}}-ephemeral.yml")
    assert "commit_sha:" in body and "yoke_dispatch_id:" in body
    assert '--commit-sha "$COMMIT_SHA"' in body
    assert '--yoke-dispatch-id "$YOKE_DISPATCH_ID"' in body


def test_the_frozen_candidate_is_what_gets_checked_out() -> None:
    """Otherwise the preview serves whatever the ref points at by the time
    the job runs, and the receipt's proof is about a different commit."""
    entry = _workflow("{{project_name}}-ephemeral.yml")
    run = _workflow("{{project_name}}-ephemeral-run.yml")
    assert "candidate_sha: ${{ needs.prepare.outputs.candidate_sha }}" in entry
    assert "candidate_sha:" in run
    assert "ref: ${{ inputs.candidate_sha }}" in run


def test_a_release_preview_is_never_cancelled_in_flight() -> None:
    """Two dispatches under one identity carry the same frozen candidate, so
    the later has nothing different to deploy while the earlier may already
    be serving a review."""
    body = _workflow("{{project_name}}-ephemeral.yml")
    assert "cancel-in-progress: ${{ github.event.inputs.yoke_dispatch_id == '' }}" in body


def test_teardown_addresses_a_release_preview_by_its_identity() -> None:
    body = _workflow("{{project_name}}-ephemeral-teardown.yml")
    assert "yoke_dispatch_id:" in body
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
    """The correlation is an opaque token a caller supplies, and one carrying
    an apostrophe would have ended its argument inside the quoted remote
    command and run whatever followed. Values reach the host on stdin."""
    body = _workflow(workflow)
    guarded = [
        line for line in body.splitlines()
        if "frozen_preview_occupancy.py claim" in line
        or "frozen_preview_occupancy.py check-cleanup" in line
    ]
    assert guarded, "expected a guarded remote invocation to inspect"
    for line in guarded:
        command = line[line.index("ssh -o LogLevel=ERROR"):]
        for name in ("YOKE_DISPATCH_ID", "CANDIDATE_SHA", "SLUG"):
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
