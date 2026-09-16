"""A landing and a session start advance a checkout only when it is safe.

Both surfaces delegate to the shared upstream-freshness primitive, so these
cases exercise real repositories rather than a canned command sequence: the
question is what happens to the checkout, not which git verbs run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from yoke_core.engines.main_checkout_sync import (
    NOT_SYNCED,
    fast_forward_main_checkout,
    sync_main_checkout_at_session_start,
)

DEFAULT_BRANCH = "trunk"


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def _commit(repo: Path, name: str, body: str) -> str:
    (repo / name).write_text(body)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def landed(tmp_path: Path):
    """A checkout whose remote has moved on, as it has after a landing."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "init", "-q", "--bare", f"--initial-branch={DEFAULT_BRANCH}", str(origin)],
        check=True,
    )
    subprocess.run(
        ["git", "init", "-q", f"--initial-branch={DEFAULT_BRANCH}", str(seed)], check=True
    )
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test")
    _commit(seed, "README.md", "seed\n")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "-u", "origin", DEFAULT_BRANCH)
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)
    _git(checkout, "config", "user.email", "test@example.com")
    _git(checkout, "config", "user.name", "Test")
    landed_sha = _commit(seed, "landed.txt", "the merge\n")
    _git(seed, "push", "-q", "origin", DEFAULT_BRANCH)
    return checkout, landed_sha


def test_clean_checkout_advances_to_the_landed_commit(landed):
    checkout, landed_sha = landed

    advisory = fast_forward_main_checkout(str(checkout), DEFAULT_BRANCH)

    assert advisory == ""
    assert _git(checkout, "rev-parse", DEFAULT_BRANCH) == landed_sha


def test_unrelated_local_edit_is_kept_and_the_checkout_still_advances(landed):
    checkout, landed_sha = landed
    (checkout / "scratch.txt").write_text("mine\n")

    advisory = fast_forward_main_checkout(str(checkout), DEFAULT_BRANCH)

    assert advisory == ""
    assert _git(checkout, "rev-parse", DEFAULT_BRANCH) == landed_sha
    assert (checkout / "scratch.txt").read_text() == "mine\n"


def test_edit_that_blocks_the_update_is_a_named_advisory(landed, tmp_path):
    checkout, _landed_sha = landed
    before = _git(checkout, "rev-parse", DEFAULT_BRANCH)
    (checkout / "landed.txt").write_text("conflicting local edit\n")

    advisory = fast_forward_main_checkout(str(checkout), DEFAULT_BRANCH)

    assert advisory.startswith(NOT_SYNCED)
    assert "commit or stash" in advisory
    assert _git(checkout, "rev-parse", DEFAULT_BRANCH) == before
    assert (checkout / "landed.txt").read_text() == "conflicting local edit\n"


def test_off_branch_checkout_still_advances_the_branch_it_left(landed):
    checkout, landed_sha = landed
    _git(checkout, "checkout", "-q", "-b", "lane")

    advisory = fast_forward_main_checkout(str(checkout), DEFAULT_BRANCH)

    assert advisory == ""
    assert _git(checkout, "rev-parse", DEFAULT_BRANCH) == landed_sha
    assert _git(checkout, "branch", "--show-current") == "lane"


def test_local_commits_are_reported_and_never_replayed(landed):
    checkout, _landed_sha = landed
    local_sha = _commit(checkout, "local.txt", "mine\n")

    advisory = fast_forward_main_checkout(str(checkout), DEFAULT_BRANCH)

    assert advisory.startswith(NOT_SYNCED)
    assert "rebase" in advisory
    assert _git(checkout, "rev-parse", DEFAULT_BRANCH) == local_sha


def test_missing_checkout_root_is_a_named_advisory():
    assert fast_forward_main_checkout("", DEFAULT_BRANCH) == (
        f"{NOT_SYNCED}: checkout root is missing"
    )


def test_unreadable_remote_is_a_named_advisory_not_a_silent_pass(landed):
    checkout, _landed_sha = landed
    _git(checkout, "remote", "set-url", "origin", str(checkout / "gone.git"))

    advisory = fast_forward_main_checkout(str(checkout), DEFAULT_BRANCH)

    assert advisory.startswith(NOT_SYNCED)
    assert "could not fetch" in advisory


def test_session_start_syncs_the_branch_the_remote_declares(landed):
    checkout, landed_sha = landed

    advisory = sync_main_checkout_at_session_start(str(checkout))

    assert advisory == ""
    assert _git(checkout, "rev-parse", DEFAULT_BRANCH) == landed_sha
