"""The UI server publishes the commit it is serving, or nothing.

A screenshot is only evidence about a candidate if the candidate can be
named from the screenshot's own surface. The server answers that from the
checkout its module was loaded out of — the tree the assets are read from
— and refuses to certify a working tree that carries uncommitted changes
as those committed contents.
"""

from __future__ import annotations

import subprocess

import pytest

from yoke_core.ui import served_source_identity as identity


@pytest.fixture()
def repository(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)
    (root / "served.txt").write_text("asset\n")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "first"], check=True
    )
    return root


def _head(root) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_a_clean_checkout_publishes_its_commit(repository):
    assert identity.served_build(repository) == _head(repository)


def test_a_modified_tree_is_not_certified_as_its_commit(repository):
    """The failure this prevents: a screenshot of uncommitted work
    presented as evidence about a commit that does not contain it."""
    (repository / "served.txt").write_text("edited after the commit\n")

    published = identity.served_build(repository)
    assert published == f"{_head(repository)}{identity.DIRTY_SUFFIX}"
    assert published != _head(repository)


def test_an_untracked_file_also_stops_certification(repository):
    (repository / "extra.txt").write_text("not committed\n")

    assert identity.served_build(repository).endswith(identity.DIRTY_SUFFIX)


def test_a_staged_change_also_stops_certification(repository):
    (repository / "served.txt").write_text("staged\n")
    subprocess.run(["git", "-C", str(repository), "add", "-A"], check=True)

    assert identity.served_build(repository).endswith(identity.DIRTY_SUFFIX)


@pytest.mark.parametrize("root", [None, ""])
def test_no_checkout_publishes_nothing(root):
    """A packaged wheel has no serving checkout, so it names no commit —
    saying nothing is honest where inventing one is not."""
    assert identity.served_build(root) == ""


def test_a_directory_that_is_not_a_repository_publishes_nothing(tmp_path):
    assert identity.served_build(tmp_path) == ""


def test_the_packet_the_server_publishes_carries_the_serving_commit():
    """The server reads its own module origin, so the commit it publishes
    is the checkout serving the assets rather than an ambient install."""
    import json

    from yoke_core.ui.server import _local_host_identity_json

    fields = json.loads(_local_host_identity_json())
    runtime = fields["runtimeIdentity"]
    if runtime.get("installKind") != "source_checkout":
        pytest.skip("this test run is not served from a source checkout")
    build = runtime.get("build", "")
    assert build, "a source checkout must publish the commit it serves"
    assert len(build.split(identity.DIRTY_SUFFIX)[0]) == 40
