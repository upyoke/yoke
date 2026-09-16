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


def _run_stdin(payload: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_guard()), *args],
        input=payload,
        capture_output=True,
        text=True,
    )


def _claim(root: Path, identity: str, sha: str, slug: str = "") -> subprocess.CompletedProcess:
    return _run_stdin(
        f"{identity}\n{sha}\n{slug}\n", "claim", "--preview-root", str(root)
    )


def _cleanup(root: Path, identity: str = "", slug: str = "") -> subprocess.CompletedProcess:
    return _run_stdin(
        f"{identity}\n{slug}\n", "check-cleanup", "--preview-root", str(root)
    )


def _owner_file(root: Path, identity: str) -> Path:
    return root / frozen_preview_slug(identity) / ".yoke-preview-owner.json"


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
        checked = _claim(tmp_path, IDENTITY, SHA)
        assert checked.returncode == 0
        assert checked.stdout.strip() == "create"

    def test_redeploying_the_same_candidate_reuses_it(self, tmp_path: Path) -> None:
        """The ordinary retry, and what makes a lost dispatch safe to repeat."""
        assert _claim(tmp_path, IDENTITY, SHA).returncode == 0
        checked = _claim(tmp_path, IDENTITY, SHA)
        assert checked.returncode == 0
        assert checked.stdout.strip() == "reuse"

    def test_the_same_identity_on_a_different_candidate_is_refused(
        self, tmp_path: Path
    ) -> None:
        """This is the gap: without it the second deploy silently replaces
        what the first one's URL was cited as evidence of."""
        assert _claim(tmp_path, IDENTITY, SHA).returncode == 0
        refused = _claim(tmp_path, IDENTITY, OTHER_SHA)
        assert refused.returncode == 1
        assert "occupancy_conflict" in refused.stderr
        stored = json.loads(_owner_file(tmp_path, IDENTITY).read_text())
        assert stored["commit_sha"] == SHA

    def test_another_identity_cannot_take_the_occupancy(self, tmp_path: Path) -> None:
        assert _claim(tmp_path, IDENTITY, SHA).returncode == 0
        # Two identities never share an occupancy, so taking one means naming
        # the other's slug — which the identity itself now refuses.
        refused = _claim(tmp_path, OTHER_IDENTITY, SHA, frozen_preview_slug(IDENTITY))
        assert refused.returncode == 1
        assert "ownership_mismatch" in refused.stderr

    def test_an_unreadable_owner_record_refuses_rather_than_assumes(
        self, tmp_path: Path
    ) -> None:
        """Unverified is not unoccupied."""
        owner = _owner_file(tmp_path, IDENTITY)
        owner.parent.mkdir(parents=True)
        owner.write_text("{not json")
        refused = _claim(tmp_path, IDENTITY, SHA)
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
        )
        assert refused.returncode == 1
        assert "reserved_slug" in refused.stderr

    def test_an_ordinary_branch_still_resolves(self) -> None:
        resolved = _run(
            "resolve",
            "--branch", "feature/Some Branch",
            "--github-sha", SHA,
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
        )
        assert refused.returncode == 1
        assert code in refused.stderr


class TestRemovingAnOccupancy:
    def test_a_branch_teardown_cannot_remove_a_frozen_occupancy(
        self, tmp_path: Path
    ) -> None:
        """Refusing costs a stale preview; deleting costs the review."""
        assert _claim(tmp_path, IDENTITY, SHA).returncode == 0
        refused = _cleanup(tmp_path, slug=frozen_preview_slug(IDENTITY))
        assert refused.returncode == 1
        assert "reserved_slug" in refused.stderr

    def test_a_different_identity_cannot_remove_it(self, tmp_path: Path) -> None:
        assert _claim(tmp_path, IDENTITY, SHA).returncode == 0
        refused = _cleanup(
            tmp_path, identity=OTHER_IDENTITY, slug=frozen_preview_slug(IDENTITY)
        )
        assert refused.returncode == 1
        assert "ownership_mismatch" in refused.stderr

    def test_the_owning_dispatch_may_remove_it(self, tmp_path: Path) -> None:
        assert _claim(tmp_path, IDENTITY, SHA).returncode == 0
        assert _cleanup(tmp_path, identity=IDENTITY).returncode == 0

    def test_a_branch_occupancy_needs_no_ownership_proof(self, tmp_path: Path) -> None:
        """Ordinary branch previews are untouched by any of this."""
        assert _cleanup(tmp_path, slug="my-branch").returncode == 0


class TestValuesNeverReachAShell:
    """The correlation is an opaque token a caller supplies.

    It travels to the host inside no command string, so a value carrying a
    quote or a semicolon is data the whole way down. Before this, the remote
    invocation interpolated it between single quotes, and one apostrophe
    ended that argument and ran whatever followed.
    """

    HOSTILE = "x'; touch {marker}; echo '"

    def test_a_metacharacter_token_is_recorded_literally_and_runs_nothing(
        self, tmp_path: Path
    ) -> None:
        marker = tmp_path / "executed"
        identity = self.HOSTILE.format(marker=marker)
        assert _claim(tmp_path, identity, SHA).returncode == 0
        assert not marker.exists(), "the token was evaluated instead of hashed"
        stored = json.loads(_owner_file(tmp_path, identity).read_text())
        assert stored["yoke_dispatch_id"] == identity

    def test_such_a_token_still_owns_its_occupancy(self, tmp_path: Path) -> None:
        """Hashing the whole string, quote included, is what makes the
        occupancy answer to exactly this correlation and no other."""
        identity = self.HOSTILE.format(marker=tmp_path / "executed")
        assert _claim(tmp_path, identity, SHA).returncode == 0
        assert _claim(tmp_path, identity, SHA).stdout.strip() == "reuse"
        assert _claim(tmp_path, identity, OTHER_SHA).returncode == 1

    def test_a_newline_bearing_token_is_refused_rather_than_split(
        self, tmp_path: Path
    ) -> None:
        """A token spanning lines would shift every field after it and claim
        an occupancy nobody named, so the payload is refused rather than
        read."""
        refused = _claim(tmp_path, "one\ntwo", SHA)
        assert refused.returncode == 1
        assert "unsafe_token" in refused.stderr
        assert "cannot be told from the next field" in refused.stderr

    def test_a_short_payload_is_refused_too(self, tmp_path: Path) -> None:
        """The same ambiguity read from the other end."""
        refused = _run_stdin(f"{IDENTITY}\n", "claim", "--preview-root", str(tmp_path))
        assert refused.returncode == 1
        assert "unsafe_token" in refused.stderr


class TestTheSlugMustBeTheOneTheIdentityNames:
    """A caller that could name any slug could claim any occupancy."""

    def test_a_mismatched_slug_is_refused(self, tmp_path: Path) -> None:
        refused = _claim(tmp_path, IDENTITY, SHA, "some-other-occupancy")
        assert refused.returncode == 1
        assert "ownership_mismatch" in refused.stderr
        assert not _owner_file(tmp_path, IDENTITY).exists()

    def test_the_derived_slug_is_accepted(self, tmp_path: Path) -> None:
        claimed = _claim(tmp_path, IDENTITY, SHA, frozen_preview_slug(IDENTITY))
        assert claimed.returncode == 0

    def test_a_cleanup_naming_another_slug_is_refused(self, tmp_path: Path) -> None:
        assert _claim(tmp_path, IDENTITY, SHA).returncode == 0
        refused = _cleanup(tmp_path, identity=IDENTITY, slug="some-other-occupancy")
        assert refused.returncode == 1
        assert "ownership_mismatch" in refused.stderr
