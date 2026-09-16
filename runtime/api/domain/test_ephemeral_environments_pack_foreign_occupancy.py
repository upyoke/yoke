"""Claims that meet an occupancy this guard did not create.

Two of those exist on a real host and neither is a defect: a preview
published before release previews were named for their run, and one
published by a different Yoke install sharing the preview domain. Both are
decided by the record on disk rather than by the name, because a name cannot
tell them apart — so both are executed here against the shipped guard.
"""

from __future__ import annotations

import json
import subprocess
import sys

from pathlib import Path

from yoke_core.domain import json_helper

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "packs/ephemeral-environments"

PREVIEW = "run-20260915-001"
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
