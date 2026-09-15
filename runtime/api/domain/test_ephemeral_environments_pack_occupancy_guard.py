"""The Pack's occupancy guard, executed as the program a host would run.

Naming alone does not stop a frozen preview being overwritten. The slug says
where a preview lives; what decides whether *this* deploy may write there is
the record already on the host. These run the shipped guard as a subprocess
against real directories, because the failure being prevented is a deploy
that succeeds while replacing what a reviewer is looking at — nothing about
that is visible from reading the workflow.
"""

from __future__ import annotations

import json
import subprocess
import sys

from pathlib import Path

import pytest

from yoke_core.domain import json_helper
from yoke_core.domain.ephemeral_substrate import frozen_preview_slug

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "packs/ephemeral-environments"

IDENTITY = "deploy:sample:run-20260915-001:preview"
OTHER_IDENTITY = "deploy:sample:run-20260915-002:preview"
SHA = "a" * 40
OTHER_SHA = "b" * 40


def _guard() -> Path:
    latest = json_helper.loads_text((PACK / "pack.json").read_text(encoding="utf-8"))[
        "latest_version"
    ]
    return PACK / "versions" / latest / "files/ops/frozen_preview_occupancy.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_guard()), *args], capture_output=True, text=True
    )


def _claim(preview_dir: Path, identity: str, sha: str) -> subprocess.CompletedProcess:
    return _run(
        "claim",
        "--preview-dir", str(preview_dir),
        "--yoke-dispatch-id", identity,
        "--commit-sha", sha,
    )


def test_the_guard_ships_as_an_installed_file() -> None:
    """A guard the install does not place is a guard no project runs."""
    manifest = json_helper.loads_text((PACK / "pack.json").read_text(encoding="utf-8"))
    targets = {
        entry["target"] for entry in manifest["versions"][manifest["latest_version"]]["files"]
    }
    assert "ops/frozen_preview_occupancy.py" in targets
    assert _guard().is_file()


class TestClaimingAnOccupancy:
    def test_an_unclaimed_slug_is_created(self, tmp_path: Path) -> None:
        checked = _claim(tmp_path / "rel-x", IDENTITY, SHA)
        assert checked.returncode == 0
        assert checked.stdout.strip() == "create"

    def test_redeploying_the_same_candidate_reuses_it(self, tmp_path: Path) -> None:
        """The ordinary retry, and what makes a lost dispatch safe to repeat."""
        preview = tmp_path / "rel-x"
        assert _claim(preview, IDENTITY, SHA).returncode == 0
        checked = _claim(preview, IDENTITY, SHA)
        assert checked.returncode == 0
        assert checked.stdout.strip() == "reuse"

    def test_the_same_identity_on_a_different_candidate_is_refused(
        self, tmp_path: Path
    ) -> None:
        """This is the gap: without it the second deploy silently replaces
        what the first one's URL was cited as evidence of."""
        preview = tmp_path / "rel-x"
        assert _claim(preview, IDENTITY, SHA).returncode == 0
        refused = _claim(preview, IDENTITY, OTHER_SHA)
        assert refused.returncode == 1
        assert "occupancy_conflict" in refused.stderr
        stored = json.loads((preview / ".yoke-preview-owner.json").read_text())
        assert stored["commit_sha"] == SHA

    def test_another_identity_cannot_take_the_occupancy(self, tmp_path: Path) -> None:
        preview = tmp_path / "rel-x"
        assert _claim(preview, IDENTITY, SHA).returncode == 0
        refused = _claim(preview, OTHER_IDENTITY, SHA)
        assert refused.returncode == 1
        assert "ownership_mismatch" in refused.stderr

    def test_an_unreadable_owner_record_refuses_rather_than_assumes(
        self, tmp_path: Path
    ) -> None:
        """Unverified is not unoccupied."""
        preview = tmp_path / "rel-x"
        preview.mkdir()
        (preview / ".yoke-preview-owner.json").write_text("{not json")
        refused = _claim(preview, IDENTITY, SHA)
        assert refused.returncode == 1
        assert "unknown_ownership" in refused.stderr


class TestTheReservedNamespace:
    @pytest.mark.parametrize(
        "branch",
        ["rel-" + "f" * 32, "REL-" + "a" * 32, "rel/" + "0" * 32],
    )
    def test_a_branch_slugifying_into_it_is_refused(self, branch: str) -> None:
        """A branch may be named anything, including the exact shape a frozen
        preview is published under — and that branch would otherwise take over
        its directory, ports and URL."""
        refused = _run(
            "resolve",
            "--branch", branch,
            "--github-sha", SHA,
            "--api-base", "9000",
            "--web-base", "4000",
            "--port-range", "100",
        )
        assert refused.returncode == 1
        assert "reserved_slug" in refused.stderr

    def test_an_ordinary_branch_still_resolves(self) -> None:
        resolved = _run(
            "resolve",
            "--branch", "feature/Some Branch",
            "--github-sha", SHA,
            "--api-base", "9000",
            "--web-base", "4000",
            "--port-range", "100",
        )
        assert resolved.returncode == 0
        assert "occupancy_slug=feature-some-branch" in resolved.stdout
        assert f"candidate_sha={SHA}" in resolved.stdout
        assert "mode=branch" in resolved.stdout

    def test_a_dispatched_preview_resolves_to_the_engine_slug(self) -> None:
        resolved = _run(
            "resolve",
            "--commit-sha", SHA,
            "--yoke-dispatch-id", IDENTITY,
            "--branch", "main",
            "--github-sha", OTHER_SHA,
            "--api-base", "9000",
            "--web-base", "4000",
            "--port-range", "100",
        )
        assert resolved.returncode == 0
        assert f"occupancy_slug={frozen_preview_slug(IDENTITY)}" in resolved.stdout
        assert f"candidate_sha={SHA}" in resolved.stdout

    @pytest.mark.parametrize(
        "args, code",
        [
            (("--commit-sha", SHA), "missing_correlation"),
            (("--yoke-dispatch-id", IDENTITY), "missing_revision"),
            (("--commit-sha", "abc", "--yoke-dispatch-id", IDENTITY), "malformed_revision"),
        ],
    )
    def test_the_two_dispatch_inputs_are_required_together(self, args, code) -> None:
        refused = _run(
            "resolve", *args,
            "--branch", "main",
            "--github-sha", OTHER_SHA,
            "--api-base", "9000",
            "--web-base", "4000",
            "--port-range", "100",
        )
        assert refused.returncode == 1
        assert code in refused.stderr


class TestRemovingAnOccupancy:
    def test_a_branch_teardown_cannot_remove_a_frozen_occupancy(
        self, tmp_path: Path
    ) -> None:
        """Refusing costs a stale preview; deleting costs the review."""
        preview = tmp_path / "rel-x"
        assert _claim(preview, IDENTITY, SHA).returncode == 0
        refused = _run("check-cleanup", "--preview-dir", str(preview))
        assert refused.returncode == 1
        assert "ownership_mismatch" in refused.stderr

    def test_a_different_identity_cannot_remove_it(self, tmp_path: Path) -> None:
        preview = tmp_path / "rel-x"
        assert _claim(preview, IDENTITY, SHA).returncode == 0
        refused = _run(
            "check-cleanup",
            "--preview-dir", str(preview),
            "--yoke-dispatch-id", OTHER_IDENTITY,
        )
        assert refused.returncode == 1
        assert "ownership_mismatch" in refused.stderr

    def test_the_owning_dispatch_may_remove_it(self, tmp_path: Path) -> None:
        preview = tmp_path / "rel-x"
        assert _claim(preview, IDENTITY, SHA).returncode == 0
        allowed = _run(
            "check-cleanup",
            "--preview-dir", str(preview),
            "--yoke-dispatch-id", IDENTITY,
        )
        assert allowed.returncode == 0

    def test_a_branch_occupancy_needs_no_ownership_proof(self, tmp_path: Path) -> None:
        """Ordinary branch previews are untouched by any of this."""
        allowed = _run("check-cleanup", "--preview-dir", str(tmp_path / "my-branch"))
        assert allowed.returncode == 0
