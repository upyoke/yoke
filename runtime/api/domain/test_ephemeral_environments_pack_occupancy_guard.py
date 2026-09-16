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

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "packs/ephemeral-environments"

PREVIEW = "run-20260915-001"
OTHER_PREVIEW = "run-20260915-002"
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


def _claim(
    root: Path, preview: str, sha: str, slug: str = ""
) -> subprocess.CompletedProcess:
    return _run_stdin(
        f"{preview}\n{sha}\n{slug}\n", "claim", "--preview-root", str(root)
    )


def _cleanup(
    root: Path, preview: str = "", slug: str = ""
) -> subprocess.CompletedProcess:
    return _run_stdin(
        f"{preview}\n{slug}\n", "check-cleanup", "--preview-root", str(root)
    )


def _owner_file(root: Path, preview: str) -> Path:
    return root / preview / ".yoke-preview-owner.json"


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
        checked = _claim(tmp_path, PREVIEW, SHA)
        assert checked.returncode == 0
        assert checked.stdout.strip() == "create"

    def test_redeploying_the_same_candidate_reuses_it(self, tmp_path: Path) -> None:
        """The ordinary retry, and what makes a lost dispatch safe to repeat.

        The preview's name is its run, not the dispatch, so a retrigger under
        a fresh dispatch scope lands here rather than on a second host.
        """
        assert _claim(tmp_path, PREVIEW, SHA).returncode == 0
        checked = _claim(tmp_path, PREVIEW, SHA)
        assert checked.returncode == 0
        assert checked.stdout.strip() == "reuse"

    def test_the_same_preview_on_a_different_candidate_is_refused(
        self, tmp_path: Path
    ) -> None:
        """This is the gap: without it the second deploy silently replaces
        what the first one's URL was cited as evidence of."""
        assert _claim(tmp_path, PREVIEW, SHA).returncode == 0
        refused = _claim(tmp_path, PREVIEW, OTHER_SHA)
        assert refused.returncode == 1
        assert "occupancy_conflict" in refused.stderr
        stored = json.loads(_owner_file(tmp_path, PREVIEW).read_text())
        assert stored["commit_sha"] == SHA

    def test_another_preview_cannot_take_the_occupancy(self, tmp_path: Path) -> None:
        assert _claim(tmp_path, PREVIEW, SHA).returncode == 0
        # Two previews never share an occupancy, so taking one means naming
        # the other's slug — which the preview's own name now refuses.
        refused = _claim(tmp_path, OTHER_PREVIEW, SHA, PREVIEW)
        assert refused.returncode == 1
        assert "ownership_mismatch" in refused.stderr

    def test_an_unreadable_owner_record_refuses_rather_than_assumes(
        self, tmp_path: Path
    ) -> None:
        """Unverified is not unoccupied."""
        owner = _owner_file(tmp_path, PREVIEW)
        owner.parent.mkdir(parents=True)
        owner.write_text("{not json")
        refused = _claim(tmp_path, PREVIEW, SHA)
        assert refused.returncode == 1
        assert "unknown_ownership" in refused.stderr

    def test_a_retired_record_names_its_retirement(self, tmp_path: Path) -> None:
        # An ownership-verified teardown for it still exists, in the Pack
        # version that published it; not naming that path sends an operator
        # to delete it by hand.
        owner = _owner_file(tmp_path, PREVIEW)
        owner.parent.mkdir(parents=True)
        owner.write_text(json.dumps({"yoke_dispatch_id": "yd-1", "commit_sha": SHA}))
        refused = _claim(tmp_path, PREVIEW, SHA)
        assert refused.returncode == 1
        assert "retired_ownership" in refused.stderr
        assert "Pack version that published it" in refused.stderr
        assert owner.exists()


class TestTheReservedNamespace:
    @pytest.mark.parametrize(
        "branch",
        ["run-20260915-001", "RUN-20260915-001", "run/20260915/001"],
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

    def test_a_dispatched_preview_publishes_the_name_it_was_given(self) -> None:
        resolved = _run(
            "resolve",
            "--commit-sha", SHA,
            "--preview-slug", PREVIEW,
            "--branch", "main",
            "--github-sha", OTHER_SHA,
        )
        assert resolved.returncode == 0
        assert f"occupancy_slug={PREVIEW}" in resolved.stdout
        assert f"candidate_sha={SHA}" in resolved.stdout

    @pytest.mark.parametrize(
        "args, code",
        [
            (("--commit-sha", SHA), "missing_preview_slug"),
            (("--preview-slug", PREVIEW), "missing_revision"),
            (("--commit-sha", "abc", "--preview-slug", PREVIEW), "malformed_revision"),
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
        assert _claim(tmp_path, PREVIEW, SHA).returncode == 0
        refused = _cleanup(tmp_path, slug=PREVIEW)
        assert refused.returncode == 1
        assert "reserved_slug" in refused.stderr

    def test_a_different_preview_cannot_remove_it(self, tmp_path: Path) -> None:
        assert _claim(tmp_path, PREVIEW, SHA).returncode == 0
        refused = _cleanup(tmp_path, preview=OTHER_PREVIEW, slug=PREVIEW)
        assert refused.returncode == 1
        assert "ownership_mismatch" in refused.stderr

    def test_the_owning_preview_may_remove_it(self, tmp_path: Path) -> None:
        assert _claim(tmp_path, PREVIEW, SHA).returncode == 0
        assert _cleanup(tmp_path, preview=PREVIEW).returncode == 0

    def test_a_branch_occupancy_needs_no_ownership_proof(self, tmp_path: Path) -> None:
        """Ordinary branch previews are untouched by any of this."""
        assert _cleanup(tmp_path, slug="my-branch").returncode == 0


class TestValuesNeverReachAShell:
    """The preview name is a value a caller supplies.

    It travels to the host inside no command string, so a value carrying a
    quote or a semicolon is data the whole way down. Before this, the remote
    invocation interpolated it between single quotes, and one apostrophe
    ended that argument and ran whatever followed. The reserved shape refuses
    such a value outright now, which is the stronger answer — but the payload
    framing still has to hold, because the refusal happens after the read.
    """

    HOSTILE = "x'; touch {marker}; echo '"

    def test_a_metacharacter_name_is_refused_and_runs_nothing(
        self, tmp_path: Path
    ) -> None:
        marker = tmp_path / "executed"
        refused = _claim(tmp_path, self.HOSTILE.format(marker=marker), SHA)
        assert refused.returncode == 1
        assert "unreserved_preview_slug" in refused.stderr
        assert not marker.exists(), "the name was evaluated instead of checked"

    def test_a_newline_bearing_name_is_refused_rather_than_split(
        self, tmp_path: Path
    ) -> None:
        """A value spanning lines would shift every field after it and claim
        an occupancy nobody named, so the payload is refused rather than
        read."""
        refused = _claim(tmp_path, "one\ntwo", SHA)
        assert refused.returncode == 1
        assert "unsafe_token" in refused.stderr
        assert "cannot be told from the next field" in refused.stderr

    def test_a_short_payload_is_refused_too(self, tmp_path: Path) -> None:
        """The same ambiguity read from the other end."""
        refused = _run_stdin(f"{PREVIEW}\n", "claim", "--preview-root", str(tmp_path))
        assert refused.returncode == 1
        assert "unsafe_token" in refused.stderr


class TestTheSlugMustBeTheOneThePreviewNames:
    """A caller that could name any slug could claim any occupancy."""

    def test_a_mismatched_slug_is_refused(self, tmp_path: Path) -> None:
        refused = _claim(tmp_path, PREVIEW, SHA, "some-other-occupancy")
        assert refused.returncode == 1
        assert "ownership_mismatch" in refused.stderr
        assert not _owner_file(tmp_path, PREVIEW).exists()

    def test_the_preview_s_own_slug_is_accepted(self, tmp_path: Path) -> None:
        claimed = _claim(tmp_path, PREVIEW, SHA, PREVIEW)
        assert claimed.returncode == 0

    def test_a_cleanup_naming_another_slug_is_refused(self, tmp_path: Path) -> None:
        assert _claim(tmp_path, PREVIEW, SHA).returncode == 0
        refused = _cleanup(tmp_path, preview=PREVIEW, slug="some-other-occupancy")
        assert refused.returncode == 1
        assert "ownership_mismatch" in refused.stderr


class TestPreviewsPublishedBeforeRunNaming:
    """They are still on the host, and a branch must not be able to take one.

    The reserved shape moved when previews became run-named, which would
    otherwise have opened the earlier one to a branch of that name — and a
    branch deploy never reads the owner record.
    """

    RETAINED = "rel-fec2595bb0bf58eca94a56710d1a087e"

    def test_a_branch_cannot_resolve_onto_a_retained_occupancy(self) -> None:
        refused = _run("resolve", "--branch", self.RETAINED, "--github-sha", SHA)
        assert refused.returncode == 1
        assert "reserved_slug" in refused.stderr

    def test_the_downstream_guard_refuses_it_too(self) -> None:
        # The reusable job re-checks rather than trusting its caller.
        refused = _run("assert-unreserved", "--slug", self.RETAINED)
        assert refused.returncode == 1
        assert "reserved_slug" in refused.stderr

    def test_a_branch_teardown_cannot_remove_one(self, tmp_path: Path) -> None:
        owner = _owner_file(tmp_path, self.RETAINED)
        owner.parent.mkdir(parents=True)
        owner.write_text(json.dumps({"yoke_dispatch_id": "yd-1", "commit_sha": SHA}))
        refused = _cleanup(tmp_path, slug=self.RETAINED)
        assert refused.returncode == 1
        assert "reserved_slug" in refused.stderr
        assert owner.exists()

    def test_nothing_new_is_published_under_that_shape(self) -> None:
        """Reserved is not publishable: the run shape is the only name a
        release preview may be created under now."""
        refused = _run(
            "resolve", "--commit-sha", SHA, "--preview-slug", self.RETAINED
        )
        assert refused.returncode == 1
        assert "unreserved_preview_slug" in refused.stderr


class TestTwoUniversesSharingAPreviewDomain:
    """Run ids are unique within a universe, so a collision needs two of them.

    `deployment_runs.id` is a universe-wide primary key rather than a
    per-project one, so two projects sharing a preview domain cannot collide.
    Two separate installs sharing a host can, and the occupancy record is what
    refuses — no name could have told them apart.
    """

    def test_the_second_universes_candidate_is_refused(self, tmp_path: Path) -> None:
        assert _claim(tmp_path, PREVIEW, SHA).returncode == 0
        refused = _claim(tmp_path, PREVIEW, OTHER_SHA)
        assert refused.returncode == 1
        assert "occupancy_conflict" in refused.stderr
        assert json.loads(_owner_file(tmp_path, PREVIEW).read_text())[
            "commit_sha"
        ] == SHA

    def test_the_same_candidate_is_the_ordinary_reuse(self, tmp_path: Path) -> None:
        # One commit under one name is one preview, whoever deployed it.
        assert _claim(tmp_path, PREVIEW, SHA).returncode == 0
        assert _claim(tmp_path, PREVIEW, SHA).stdout.strip() == "reuse"
