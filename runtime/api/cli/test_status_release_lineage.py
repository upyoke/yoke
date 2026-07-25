"""`yoke status` says whether this checkout carries unreleased commits.

A deploy binds a release to an exact commit, so merged work is not live until a
release tag reaches it. Status previously showed a matching engine version on
both sides while the newest tag sat behind main, so merged work looked shipped
when it was not.
"""

from __future__ import annotations

import subprocess

from yoke_cli.config import status_release_lineage as lineage


def _git(root, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True,
    )


def _repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "T")
    return tmp_path


def _commit(root, message: str) -> None:
    (root / "f.txt").write_text(message, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


def test_reports_the_tag_when_nothing_is_unreleased(tmp_path) -> None:
    root = _repo(tmp_path)
    _commit(root, "one")
    _git(root, "tag", "v1.0.0")

    detected = lineage.detect(root)

    assert detected == {"newest_tag": "v1.0.0", "unreleased_commits": 0}
    assert lineage.label(detected) == "v1.0.0 (nothing unreleased)"


def test_names_commits_the_newest_release_has_not_shipped(tmp_path) -> None:
    # The observed failure: a merged install fix sat past the newest tag while
    # every version surface reported healthy.
    root = _repo(tmp_path)
    _commit(root, "released")
    _git(root, "tag", "v1.0.0")
    _commit(root, "merged but unreleased")
    _commit(root, "also unreleased")

    detected = lineage.detect(root)

    assert detected == {"newest_tag": "v1.0.0", "unreleased_commits": 2}
    label = lineage.label(detected)
    assert "v1.0.0 + 2 unreleased commits" in label
    assert "not deployed" in label


def test_singular_reads_correctly_for_one_commit(tmp_path) -> None:
    root = _repo(tmp_path)
    _commit(root, "released")
    _git(root, "tag", "v1.0.0")
    _commit(root, "one unreleased")

    assert "1 unreleased commit —" in lineage.label(lineage.detect(root))


def test_stays_silent_for_a_repo_with_no_tags(tmp_path) -> None:
    # A managed project has no release lineage of its own to report.
    root = _repo(tmp_path)
    _commit(root, "only commit")

    assert lineage.detect(root) is None
    assert lineage.label(None) is None


def test_stays_silent_outside_a_git_checkout(tmp_path) -> None:
    assert lineage.detect(tmp_path / "not-a-repo") is None


def test_uses_the_newest_tag_not_the_first(tmp_path) -> None:
    root = _repo(tmp_path)
    _commit(root, "one")
    _git(root, "tag", "v1.0.0")
    _commit(root, "two")
    _git(root, "tag", "v2.0.0")
    _commit(root, "after the newest")

    assert lineage.detect(root)["newest_tag"] == "v2.0.0"
