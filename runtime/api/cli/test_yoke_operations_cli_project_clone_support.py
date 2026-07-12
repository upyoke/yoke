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
from yoke_cli.config.project_git_transport import git_auth_header


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


def test_clone_anonymous_success_does_not_use_token(
    tmp_path: Path, monkeypatch,
) -> None:
    parent = tmp_path / "checkouts"
    parent.mkdir()
    calls: list[dict] = []
    monkeypatch.setattr(
        clone,
        "_run_clone",
        lambda *args, **kwargs: calls.append(kwargs)
        or subprocess.CompletedProcess([], 0, "", ""),
    )

    outcome = clone.clone_with_token_fallback(
        parent,
        "widgets",
        "git@github.com:acme/widgets.git",
        token="ghs_should_not_be_used",
    )

    assert outcome.used_token is False
    assert outcome.origin_url == "https://github.com/acme/widgets.git"
    assert [
        {key: value for key, value in call.items() if key != "target_claim"}
        for call in calls
    ] == [{"github_web_url": None}]


def test_clone_anonymous_fail_token_success_rehomes_origin_cleanly(
    tmp_path: Path, monkeypatch
) -> None:
    parent = tmp_path / "checkouts"
    parent.mkdir()
    token = "ghs_secret_token_value"
    calls: list[dict] = []
    results = iter([
        subprocess.CompletedProcess([], 1, "", "authentication failed"),
        subprocess.CompletedProcess([], 0, "", ""),
    ])
    monkeypatch.setattr(
        clone,
        "_run_clone",
        lambda *args, **kwargs: calls.append(kwargs) or next(results),
    )
    cleaned: list[str] = []
    monkeypatch.setattr(
        clone,
        "run_git",
        lambda _root, *_args: cleaned.append(_args[-1]),
    )

    outcome = clone.clone_with_token_fallback(
        parent, "widgets", "git@github.com:acme/widgets.git", token=token,
    )

    assert outcome.used_token is True
    assert outcome.origin_url == "https://github.com/acme/widgets.git"
    assert [
        {key: value for key, value in call.items() if key != "target_claim"}
        for call in calls
    ] == [
        {"github_web_url": None},
        {"token": token, "github_web_url": None},
    ]
    assert calls[0]["target_claim"] is calls[1]["target_claim"]
    assert cleaned == ["https://github.com/acme/widgets.git", "-f"]


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
    header = git_auth_header(token)
    results = iter([
        subprocess.CompletedProcess([], 1, "", "authentication failed"),
        subprocess.CompletedProcess([], 1, "", f"denied {header}"),
    ])
    monkeypatch.setattr(
        clone,
        "_run_clone",
        lambda *args, **kwargs: next(results),
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
    external = "https://attacker.example/Owner/Repo.git"
    assert clone.https_clone_url(
        external,
        web_url="https://ghe.example",
    ) == external
    with pytest.raises(clone.CloneAccessError, match="configured GitHub origin"):
        clone._run_clone(
            Path("."),
            "Repo",
            external,
            token="short-lived-user-token",
            github_web_url="https://ghe.example",
        )


def test_clone_no_token_access_failure_raises(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "checkouts"
    parent.mkdir()
    monkeypatch.setattr(
        clone,
        "_run_clone",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 1, "", "authentication failed",
        ),
    )

    with pytest.raises(clone.CloneAccessError):
        clone.clone_with_token_fallback(
            parent,
            "widgets",
            "https://github.com/acme/widgets.git",
            token=None,
        )


def test_private_intent_retries_localized_anonymous_denial(
    tmp_path: Path, monkeypatch,
) -> None:
    parent = tmp_path / "checkouts"
    parent.mkdir()
    results = iter([
        subprocess.CompletedProcess([], 1, "", "Zugriff verweigert"),
        subprocess.CompletedProcess([], 0, "", ""),
    ])
    attempts: list[dict] = []
    monkeypatch.setattr(
        clone,
        "_run_clone",
        lambda *args, **kwargs: attempts.append(kwargs) or next(results),
    )
    monkeypatch.setattr(clone, "run_git", lambda *_args, **_kwargs: None)

    outcome = clone.clone_with_token_fallback(
        parent,
        "widgets",
        "https://github.com/acme/widgets.git",
        token_provider=lambda: "ghu_private",
    )

    assert outcome.used_token is True
    assert len(attempts) == 2


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
