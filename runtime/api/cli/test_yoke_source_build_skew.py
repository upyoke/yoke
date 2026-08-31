"""Relating a source checkout to the build a server reports.

The version handshake cannot answer this: distribution versions move per
release, a checkout moves per commit, and a checkout has no distribution
version at all. Every case here is about giving a real answer or an
honest unknown — never an unearned "in sync".
"""

from __future__ import annotations

import subprocess

import pytest

from yoke_cli.transport import source_build_skew as skew


def _git(repo, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    """A throwaway checkout with one commit."""
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "f.txt").write_text("one\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "one")
    return root


def _commit(repo, text: str) -> str:
    (repo / "f.txt").write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", text.strip())
    return _git(repo, "rev-parse", "HEAD")


def test_matching_head_and_build_is_equal(repo):
    head = _git(repo, "rev-parse", "HEAD")
    result = skew.compare_to_server_build(str(repo), head)
    assert result.relationship == skew.EQUAL
    assert not result.differs
    assert "matches" in skew.describe(result)


def test_a_checkout_past_the_build_is_ahead_by_the_commit_count(repo):
    """The observed case: local work merged after the release was cut."""
    build = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "two\n")
    _commit(repo, "three\n")
    result = skew.compare_to_server_build(str(repo), build)
    assert result.relationship == skew.AHEAD
    assert result.ahead_by == 2
    assert result.differs
    described = skew.describe(result)
    assert "2 commit(s) ahead" in described
    assert "deploy" in described


def test_a_checkout_behind_the_build_says_pull(repo):
    _commit(repo, "two\n")
    build = _git(repo, "rev-parse", "HEAD")
    _git(repo, "reset", "--soft", "HEAD~1")
    _git(repo, "checkout", "-q", "HEAD")
    result = skew.compare_to_server_build(str(repo), build)
    assert result.relationship == skew.BEHIND
    assert result.behind_by == 1
    assert "pull" in skew.describe(result)


def test_divergence_reports_both_distances(repo):
    base = _git(repo, "rev-parse", "HEAD")
    build = _commit(repo, "server side\n")
    _git(repo, "checkout", "-q", "-b", "local", base)
    _commit(repo, "local side\n")
    result = skew.compare_to_server_build(str(repo), build)
    assert result.relationship == skew.DIVERGED
    assert result.ahead_by == 1 and result.behind_by == 1
    assert "diverged" in skew.describe(result)


def test_an_empty_server_build_is_unknown_not_equal(repo):
    """Missing information must never render as agreement."""
    result = skew.compare_to_server_build(str(repo), "")
    assert result.relationship == skew.UNKNOWN
    assert not result.differs
    assert "no build" in result.reason


def test_a_build_this_checkout_has_never_fetched_is_unknown(repo):
    """Distinct from being behind it: the comparison cannot be made."""
    absent = "0" * 40
    result = skew.compare_to_server_build(str(repo), absent)
    assert result.relationship == skew.UNKNOWN
    assert "not present in this checkout" in result.reason


def test_a_non_checkout_is_unknown_and_names_the_path(tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    result = skew.compare_to_server_build(str(plain), "0" * 40)
    assert result.relationship == skew.UNKNOWN
    assert str(plain) in result.reason
    assert "cannot tell" in skew.describe(result)


def test_a_release_tag_resolves_and_stays_readable(repo):
    """The handshake passes a tag, not a sha — it must not be truncated.

    Abbreviating a tag to twelve characters would print half a version.
    """
    build = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "v9.9.9+launch.1", "-m", "release", build)
    _commit(repo, "after release\n")
    result = skew.compare_to_server_build(str(repo), "v9.9.9+launch.1")
    assert result.relationship == skew.AHEAD
    assert "v9.9.9+launch.1" in skew.describe(result)


def test_a_sha_is_abbreviated_for_reading(repo):
    build = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "after\n")
    described = skew.describe(skew.compare_to_server_build(str(repo), build))
    assert build[:12] in described
    assert build not in described


def test_fetched_origin_ahead_of_local_main_reports_the_gap(repo):
    local = _git(repo, "rev-parse", "HEAD")
    origin = _commit(repo, "landed remotely\n")
    _git(repo, "update-ref", "refs/remotes/origin/main", origin)
    _git(
        repo,
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        "refs/remotes/origin/main",
    )
    _git(repo, "reset", "--hard", local)

    result = skew.compare_main_to_origin(str(repo))

    assert result.relationship == skew.BEHIND
    assert result.behind_by == 1
    assert result.behind
    assert skew.describe_origin(result) == (
        "checkout is 1 commit(s) behind origin/main — run `git pull --ff-only`"
    )


def test_current_main_has_no_origin_gap(repo):
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", head)
    _git(
        repo,
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        "refs/remotes/origin/main",
    )

    result = skew.compare_main_to_origin(str(repo))

    assert result.relationship == skew.EQUAL
    assert not result.behind


def test_same_checkout_head_and_build_reuse_the_history_walk(repo, monkeypatch):
    """A second compare for the same HEAD must not cat-file the build again."""
    seen: list[tuple[str, ...]] = []
    inner = skew._git

    def wrapped(root, *args: str):
        seen.append(args)
        return inner(root, *args)

    monkeypatch.setattr(skew, "_git", wrapped)
    skew._compare_to_server_build_cached.cache_clear()
    head = _git(repo, "rev-parse", "HEAD")
    first = skew.compare_to_server_build(str(repo), head)
    second = skew.compare_to_server_build(str(repo), head)
    assert first.relationship == skew.EQUAL
    assert second.relationship == first.relationship
    assert [a for a in seen if a[:1] == ("cat-file",)] == [
        ("cat-file", "-e", f"{head}^{{commit}}"),
    ]
