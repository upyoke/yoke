"""Checkout GitHub sign-in convergence across remote types and install dates."""

import json

import pytest

from runtime.api.cli.test_github_git_credential_install import _configured_repo, _git
from yoke_cli.config import github_git_credentials, github_project_setup
from yoke_cli.config.project_publication_destination import LEGACY_READ_ONLY_PUSH_URL
from yoke_cli.project_install import runner


@pytest.mark.parametrize(
    "origin",
    [
        "git@github.com:octo/repo.git",
        "ssh://git@github.com/octo/repo.git",
        "https://github.com/octo/repo.git",
    ],
)
def test_checkout_converges_to_https_and_verified_helper(tmp_path, monkeypatch, origin):
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    _git(repo, "remote", "add", "origin", origin)
    _git(repo, "config", "remote.origin.pushurl", origin)
    monkeypatch.setattr(
        github_git_credentials, "_helper_site_dir", lambda: tmp_path / "site"
    )
    report = github_project_setup.converge(repo, config_path=config)
    assert report["configured"] is True
    assert "credential-helper" in report["changes"]
    assert _git(repo, "remote", "get-url", "origin").stdout.strip() == (
        "https://github.com/octo/repo.git"
    )
    assert _git(repo, "remote", "get-url", "--push", "origin").stdout.strip() == (
        "https://github.com/octo/repo.git"
    )
    second = github_project_setup.converge(repo, config_path=config)
    assert second["changes"] == []
    assert second["changed"] is False


def test_different_push_target_refuses_before_any_rewrite(tmp_path, monkeypatch):
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    _git(repo, "remote", "add", "origin", "git@github.com:octo/repo.git")
    _git(repo, "config", "remote.origin.pushurl", "git@github.com:octo/other.git")
    before = (repo / ".git/config").read_bytes()
    with pytest.raises(
        github_project_setup.GitHubProjectSetupError, match="push-target-mismatch"
    ):
        github_project_setup.converge(repo, config_path=config)
    assert (repo / ".git/config").read_bytes() == before


@pytest.mark.parametrize("extra_push_url", [None, "git@github.com:octo/repo.git"])
def test_read_only_checkout_converges_helper_without_enabling_push(
    tmp_path, monkeypatch, extra_push_url
):
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    _git(repo, "remote", "add", "origin", "git@github.com:octo/repo.git")
    from runtime.api.cli.test_project_publication_settings import seed_project

    seed_project(repo, config)
    _git(repo, "config", "remote.origin.pushurl", LEGACY_READ_ONLY_PUSH_URL)
    expected_push_urls = ["git@github.com:octo/repo.git"]
    if extra_push_url:
        _git(repo, "config", "--add", "remote.origin.pushurl", extra_push_url)
        expected_push_urls = [extra_push_url]
    monkeypatch.setattr(
        github_git_credentials, "_helper_site_dir", lambda: tmp_path / "site"
    )

    report = github_project_setup.converge(repo, config_path=config)

    assert report["configured"] is True
    assert report["changes"] == ["credential-helper"]
    assert _git(repo, "remote", "get-url", "origin").stdout.strip() == (
        "git@github.com:octo/repo.git"
    )
    assert _git(
        repo, "remote", "get-url", "--push", "--all", "origin"
    ).stdout.splitlines() == expected_push_urls
    assert github_project_setup.converge(repo, config_path=config)["changed"] is False


@pytest.mark.parametrize(
    "push_url", ["git@github.com:octo/other.git", "disabled://unowned-policy"]
)
def test_read_only_sentinel_does_not_bypass_other_push_url_validation(
    tmp_path, monkeypatch, push_url
):
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    _git(repo, "remote", "add", "origin", "git@github.com:octo/repo.git")
    from runtime.api.cli.test_project_publication_settings import seed_project

    seed_project(repo, config)
    _git(repo, "config", "remote.origin.pushurl", LEGACY_READ_ONLY_PUSH_URL)
    _git(repo, "config", "--add", "remote.origin.pushurl", push_url)
    before = (repo / ".git/config").read_bytes()

    with pytest.raises(github_project_setup.GitHubProjectSetupError):
        github_project_setup.converge(repo, config_path=config)

    assert (repo / ".git/config").read_bytes() == before


def test_missing_authorization_teaches_connect_and_preserves_origin(
    tmp_path, monkeypatch
):
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    _git(repo, "remote", "add", "origin", "git@github.com:octo/repo.git")
    payload = json.loads(config.read_text())
    payload["github"].pop("authorization")
    config.write_text(json.dumps(payload))
    report = github_project_setup.converge(repo, config_path=config)
    assert report["configured"] is False
    assert "yoke github connect" in report["recovery"]
    assert _git(repo, "remote", "get-url", "origin").stdout.strip().startswith("git@")


@pytest.mark.parametrize("operation", ["install", "refresh"])
@pytest.mark.parametrize("read_only", [False, True])
def test_install_and_refresh_converge_before_upstream_and_publication(
    tmp_path,
    monkeypatch,
    operation,
    read_only,
):
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    _git(repo, "remote", "add", "origin", "git@github.com:octo/repo.git")
    if read_only:
        from runtime.api.cli.test_project_publication_settings import seed_project

        seed_project(repo, config)
        _git(repo, "config", "remote.origin.pushurl", LEGACY_READ_ONLY_PUSH_URL)
    monkeypatch.setattr(
        github_git_credentials, "_helper_site_dir", lambda: tmp_path / "site"
    )
    monkeypatch.setattr(runner, "_resolve_project_id", lambda *args: (7, False))
    monkeypatch.setattr(
        runner, "_resolve_bundle", lambda *a, **kw: ({"default_branch": "main"}, "test")
    )
    monkeypatch.setattr(runner, "validate_bundle_for_project", lambda *args: None)
    monkeypatch.setattr(
        runner.git_hooks_layer, "assert_pre_commit_runtime_available", lambda: None
    )
    monkeypatch.setattr(
        runner.checkout_gate,
        "assert_ready_for_write",
        lambda *a, **kw: {"branch": "main"},
    )
    monkeypatch.setattr(runner, "preflight_apply", lambda *args: None)
    monkeypatch.setattr(runner, "_register_in_machine_config", lambda *args: False)
    monkeypatch.setattr(
        runner.repository_layer, "write_repository_layer", lambda *a, **kw: {}
    )
    monkeypatch.setattr(runner, "sync_local_snapshot_for_write", lambda **kw: {})
    monkeypatch.setattr(
        runner.checkout_gate, "commit_touched_paths", lambda *a, **kw: {}
    )

    def check_https(*args, **kwargs):
        if read_only:
            assert _git(
                repo, "remote", "get-url", "--push", "origin"
            ).stdout.strip() == "git@github.com:octo/repo.git"
        assert (
            _git(repo, "remote", "get-url", "origin")
            .stdout.strip()
            .startswith("git@" if read_only else "https://")
        )
        assert _git(
            repo,
            "config",
            "--local",
            "--get-all",
            github_git_credentials.GITHUB_CREDENTIAL_HELPER_KEY,
        ).stdout
        return {}

    monkeypatch.setattr(runner, "_bring_branch_current", check_https)
    monkeypatch.setattr(runner.publication, "publish_installed_layer", check_https)
    report = getattr(runner, operation)(repo, config_path=config)
    assert report["git_credentials"]["changes"] == (
        ["credential-helper"] if read_only else ["credential-helper", "origin-url"]
    )


@pytest.mark.parametrize(
    "origin",
    ["https://github.com/octo/repo.git?bad=1", "ftp://github.com/octo/repo.git"],
)
def test_invalid_github_origin_refuses_without_rewrite(tmp_path, monkeypatch, origin):
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    _git(repo, "remote", "add", "origin", origin)
    before = (repo / ".git/config").read_bytes()
    with pytest.raises(
        github_project_setup.GitHubProjectSetupError, match="github-origin-invalid"
    ):
        github_project_setup.converge(repo, config_path=config)
    assert (repo / ".git/config").read_bytes() == before


def test_other_origin_is_reported_as_skipped(tmp_path, monkeypatch):
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    _git(repo, "remote", "add", "origin", "https://elsewhere.example/octo/repo.git")
    assert github_project_setup.converge(repo, config_path=config) == {
        "configured": False,
        "reason": "origin-outside-configured-github",
    }


@pytest.mark.parametrize("refuse", [False, True])
def test_source_activation_uses_selected_config_and_teaches_refusal(
    tmp_path,
    monkeypatch,
    capsys,
    refuse,
):
    from yoke_cli.config import source_checkout_activation as activation
    from yoke_core.domain import project_install_source_link as source_link

    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    _git(repo, "remote", "add", "origin", "git@github.com:octo/repo.git")
    if refuse:
        _git(repo, "config", "remote.origin.pushurl", "git@github.com:octo/other.git")
    monkeypatch.setattr(
        github_git_credentials, "_helper_site_dir", lambda: tmp_path / "site"
    )
    monkeypatch.setattr(
        source_link,
        "install_source_link",
        lambda root, **kw: {
            "git_credentials": github_project_setup.converge(
                root, config_path=kw["config_path"]
            ),
        },
    )
    import sys

    monkeypatch.setattr(
        sys, "argv", ["source-link", str(repo), "dev.setup", str(config)]
    )
    if refuse:
        with pytest.raises(SystemExit) as exit_result:
            exec(activation._SOURCE_LINK_SNIPPET, {})
        assert exit_result.value.code == 1
        captured = capsys.readouterr()
        assert "github-push-target-mismatch" in captured.err
        assert "Traceback" not in captured.err
        assert captured.out == ""
    else:
        exec(activation._SOURCE_LINK_SNIPPET, {})
        report = json.loads(capsys.readouterr().out)
        assert report["git_credentials"]["configured"] is True
        from yoke_cli.config import dev_setup

        human = dev_setup.render_human(
            {
                "checkout": {"path": str(repo)},
                "applied": True,
                "plan": {"steps": []},
                "source_link": report,
            }
        )
        assert "GitHub sign-in:" in human
        assert "origin-url" in human


def test_unconfigured_github_skips_folder_git_inspection(tmp_path, monkeypatch):
    repo = tmp_path / "folder-project"
    (repo / ".git/hooks").mkdir(parents=True)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"schema_version": 1}))

    def unexpected_git_read(*args, **kwargs):
        raise AssertionError("GitHub setup must not inspect Git when unconfigured")

    monkeypatch.setattr(
        github_project_setup.github_repo_config, "values", unexpected_git_read
    )
    report = github_project_setup.converge(repo, config_path=config)
    assert report["configured"] is False
    assert report["reason"] == "machine-github-not-configured"
    assert "yoke github connect" in report["recovery"]
