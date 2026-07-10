"""Clone-side git helpers: token fallback, URL normalization, re-home, fork.

Every scenario runs against local temp git repos (a bare repo stands in for the
GitHub source/remote); no network, no real git@github.com push. The token
fallback's security invariants are asserted directly: the token never lands in
the cloned repo's .git/config and never in the stored origin URL.
"""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import project_clone_support as clone


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return result.stdout.strip()


def _seed_bare_source(
    tmp_path: Path, name: str = "source", *, branch: str = "main"
) -> Path:
    """A bare repo with one commit, standing in for the GitHub source.

    ``branch`` is the source repo's default branch. Clones inherit it as their
    checked-out local branch, so a non-``main`` value exercises the re-home push
    against a repo whose current branch is not ``main``.
    """
    work = tmp_path / f"{name}-work"
    work.mkdir()
    _git(work, "init", "--initial-branch", branch)
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("# source\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "seed")
    bare = tmp_path / f"{name}.git"
    _git(tmp_path, "clone", "--bare", str(work), str(bare))
    return bare


# ── URL normalization ───────────────────────────────────────────────────


def test_https_clone_url_normalizes_ssh() -> None:
    assert clone.https_clone_url("git@github.com:acme/widgets.git") == (
        "https://github.com/acme/widgets.git"
    )
    assert clone.https_clone_url("git@github.com:acme/widgets") == (
        "https://github.com/acme/widgets.git"
    )


def test_https_clone_url_passes_https_through() -> None:
    url = "https://github.com/acme/widgets.git"
    assert clone.https_clone_url(url) == url


def test_source_owner_repo_parses_both_forms() -> None:
    assert clone.source_owner_repo("git@github.com:acme/widgets.git") == (
        "acme", "widgets",
    )
    assert clone.source_owner_repo("https://github.com/acme/widgets") == (
        "acme", "widgets",
    )


# ── token fallback ──────────────────────────────────────────────────────


def test_clone_ambient_success_does_not_use_token(tmp_path: Path) -> None:
    bare = _seed_bare_source(tmp_path)
    parent = tmp_path / "checkouts"
    parent.mkdir()

    outcome = clone.clone_with_token_fallback(
        parent, "widgets", str(bare), token="ghs_should_not_be_used",
    )

    assert outcome.used_token is False
    assert outcome.origin_url == str(bare)
    target = parent / "widgets"
    assert (target / "README.md").is_file()


def test_clone_ambient_fail_token_success_rehomes_origin_cleanly(
    tmp_path: Path, monkeypatch
) -> None:
    bare = _seed_bare_source(tmp_path)
    parent = tmp_path / "checkouts"
    parent.mkdir()
    token = "ghs_secret_token_value"
    seen_commands: list[list[str]] = []
    real_run = clone.subprocess.run

    def capture(command, *args, **kwargs):
        seen_commands.append(list(command))
        return real_run(command, *args, **kwargs)

    # Ambient clones a bogus local path (fails fast, no network, no prompt); the
    # fallback's normalized HTTPS URL is redirected to the real bare source.
    monkeypatch.setattr(clone, "_looks_like_access_failure", lambda _stderr: True)
    monkeypatch.setattr(clone, "https_clone_url", lambda _url, **_: str(bare))
    monkeypatch.setattr(
        clone, "git_auth_config", lambda *_args, **_kwargs: "http.test.extraheader=x",
    )
    monkeypatch.setattr(clone.subprocess, "run", capture)

    outcome = clone.clone_with_token_fallback(
        parent, "widgets", "git@github.com:acme/widgets.git", token=token,
    )

    assert outcome.used_token is True
    assert outcome.origin_url == str(bare)
    target = parent / "widgets"
    # SECURITY: the token must not persist anywhere in the cloned repo.
    config_text = (target / ".git" / "config").read_text(encoding="utf-8")
    assert token not in config_text
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    assert encoded not in config_text
    assert "extraheader" not in config_text
    # The stored origin is the clean URL with no embedded credential.
    origin = _git(target, "remote", "get-url", "origin")
    assert origin == str(bare)
    assert token not in origin
    assert all(token not in " ".join(command) for command in seen_commands)
    assert all("extraheader" not in " ".join(command) for command in seen_commands)


def test_clone_plan_repr_hides_all_tokens() -> None:
    plan = clone.ClonePlan(
        fallback_token="fallback-secret",
        publish=clone.PublishRequest(
            owner="octocat", name="app", user_login="octocat",
            token="publish-secret",
        ),
    )

    assert "fallback-secret" not in repr(plan)
    assert "publish-secret" not in repr(plan)


def test_clone_token_fail_raises_clear_error_without_leaking_token(
    tmp_path: Path, monkeypatch
) -> None:
    parent = tmp_path / "checkouts"
    parent.mkdir()
    token = "ghs_secret_token_value"
    bogus = tmp_path / "nonexistent.git"

    monkeypatch.setattr(clone, "_looks_like_access_failure", lambda _stderr: True)
    # Even the fallback clones a path that does not exist -> full failure.
    monkeypatch.setattr(clone, "https_clone_url", lambda _url, **_: str(bogus))
    monkeypatch.setattr(
        clone, "git_auth_config", lambda *_args, **_kwargs: "http.test.extraheader=x",
    )

    with pytest.raises(clone.CloneAccessError) as exc:
        clone.clone_with_token_fallback(
            parent, "widgets", "git@github.com:acme/widgets.git", token=token,
        )

    message = str(exc.value)
    assert "lacks access" in message or "not found" in message
    # The encoded token (and the raw token) must never reach the error text.
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    assert token not in message
    assert encoded not in message


def test_ghes_clone_references_use_configured_web_origin() -> None:
    web_url = "https://ghe.example"
    assert clone.https_clone_url(
        "git@ghe.example:Owner/Repo.git", web_url=web_url,
    ) == "https://ghe.example/Owner/Repo.git"
    assert clone.source_owner_repo(
        "https://ghe.example/Owner/Repo.git", web_url=web_url,
    ) == ("Owner", "Repo")


def test_clone_token_transport_rejects_unrelated_origin() -> None:
    with pytest.raises(clone.CloneAccessError, match="configured web origin"):
        clone.https_clone_url(
            "https://attacker.example/Owner/Repo.git",
            web_url="https://ghe.example",
        )


def test_clone_no_token_access_failure_raises(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "checkouts"
    parent.mkdir()
    monkeypatch.setattr(clone, "_looks_like_access_failure", lambda _stderr: True)

    with pytest.raises(clone.CloneAccessError):
        clone.clone_with_token_fallback(
            parent, "widgets", str(tmp_path / "nope.git"), token=None,
        )


# ── re-home / fork remote choreography ──────────────────────────────────


def _clone_into(tmp_path: Path, bare: Path, name: str) -> Path:
    parent = tmp_path / "checkouts"
    parent.mkdir(exist_ok=True)
    _git(parent, "clone", str(bare), name)
    target = parent / name
    _git(target, "config", "user.email", "t@example.com")
    _git(target, "config", "user.name", "Test")
    return target


def test_rehome_keeps_upstream_and_pushes_to_new_origin(tmp_path: Path) -> None:
    source = _seed_bare_source(tmp_path, "source")
    new_origin = tmp_path / "mine.git"
    _git(tmp_path, "init", "--bare", str(new_origin))
    target = _clone_into(tmp_path, source, "widgets")

    clone.rehome_to_new_origin(
        target, new_origin_url=str(new_origin),
        default_branch="main", keep_upstream=True,
    )

    assert _git(target, "remote", "get-url", "origin") == str(new_origin)
    assert _git(target, "remote", "get-url", "upstream") == str(source)
    pushed = _git(new_origin, "branch", "--list")
    assert "main" in pushed


def test_rehome_pushes_the_clones_actual_branch_not_main(tmp_path: Path) -> None:
    # The source's default branch is `master`, so the clone checks out `master`
    # — there is no local `main` ref. A re-home that hardcodes `push -u origin
    # main` fails here with `src refspec main does not match any`; the fix
    # detects and pushes the live branch.
    source = _seed_bare_source(tmp_path, "source", branch="master")
    new_origin = tmp_path / "mine.git"
    _git(tmp_path, "init", "--bare", str(new_origin))
    target = _clone_into(tmp_path, source, "widgets")
    assert _git(target, "rev-parse", "--abbrev-ref", "HEAD") == "master"

    # Pass the (wrong) caller hint default_branch="main" to prove the push
    # follows the detected branch, not the hint.
    pushed_branch = clone.rehome_to_new_origin(
        target, new_origin_url=str(new_origin),
        default_branch="main", keep_upstream=True,
    )

    assert pushed_branch == "master"
    assert _git(target, "remote", "get-url", "origin") == str(new_origin)
    # The new origin received `master`, and never a stray `main`.
    pushed = _git(new_origin, "branch", "--list").replace("*", "").split()
    assert pushed == ["master"]


def test_rehome_clean_copy_drops_the_source(tmp_path: Path) -> None:
    source = _seed_bare_source(tmp_path, "source")
    new_origin = tmp_path / "mine.git"
    _git(tmp_path, "init", "--bare", str(new_origin))
    target = _clone_into(tmp_path, source, "widgets")

    clone.rehome_to_new_origin(
        target, new_origin_url=str(new_origin),
        default_branch="main", keep_upstream=False,
    )

    assert _git(target, "remote", "get-url", "origin") == str(new_origin)
    remotes = _git(target, "remote").split()
    assert "upstream" not in remotes


def test_set_fork_remotes_points_origin_at_fork_keeps_source_upstream(
    tmp_path: Path
) -> None:
    source = _seed_bare_source(tmp_path, "source")
    fork = tmp_path / "fork.git"
    _git(tmp_path, "init", "--bare", str(fork))
    target = _clone_into(tmp_path, source, "widgets")

    clone.set_fork_remotes(target, fork_url=str(fork))

    assert _git(target, "remote", "get-url", "origin") == str(fork)
    assert _git(target, "remote", "get-url", "upstream") == str(source)


# ── approved progress copy ──────────────────────────────────────────────


def test_clone_progress_lines_clean_clone() -> None:
    lines = clone.clone_progress_lines(
        "acme/widgets", clone.CloneOutcome(used_token=False, origin_url="x"),
    )
    assert lines == ["  Cloning acme/widgets…", "  ✓ Cloned."]


def test_clone_progress_lines_token_fallback_is_informational() -> None:
    lines = clone.clone_progress_lines(
        "acme/widgets", clone.CloneOutcome(used_token=True, origin_url="x"),
    )
    assert lines == [
        "  Cloning acme/widgets…",
        "  Your git setup couldn't reach it — used connected GitHub App access.",
        "  ✓ Cloned.",
    ]
