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


def test_the_workflow_hashes_the_identity_without_a_trailing_newline() -> None:
    """``echo`` would append one and change every digest."""
    body = _workflow("{{project_name}}-ephemeral.yml")
    assert "printf '%s' \"$YOKE_DISPATCH_ID\" | sha256sum | cut -c1-32" in body


def test_a_release_preview_slug_is_unreachable_by_any_branch_name() -> None:
    """Which is what stops a branch from taking over a candidate's URL."""
    for identity in IDENTITIES:
        frozen = frozen_preview_slug(identity)
        assert is_frozen_preview_slug(frozen)
        assert slugify_branch(identity) != frozen


def test_both_dispatch_inputs_are_declared_and_required_together() -> None:
    body = _workflow("{{project_name}}-ephemeral.yml")
    assert "commit_sha:" in body and "yoke_dispatch_id:" in body
    assert "commit_sha and yoke_dispatch_id are required together" in body


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
    assert "printf '%s' \"$YOKE_DISPATCH_ID\" | sha256sum | cut -c1-32" in body


def test_branch_previews_still_slugify_their_branch() -> None:
    """The release path must not have changed what a development preview
    does — a push still deploys that branch's head under its own slug."""
    body = _workflow("{{project_name}}-ephemeral.yml")
    assert "branches-ignore:" in body
    assert "tr '[:upper:]' '[:lower:]'" in body
    assert "candidate_sha=${GITHUB_SHA}" in body
