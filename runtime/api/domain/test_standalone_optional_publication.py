"""Disconnected publication succeeds with a helper and keeps App checks off."""

from runtime.api.cli.git_http_test_support import (
    authenticated_remote,
    git,
    own_credential_config,
)
from runtime.api.engines.local_merge_test_support import (
    make_local_checkout,
    assert_landed_clean,
)
from yoke_cli.config import credentialed_git
from yoke_core.domain import standalone_item_merge as boundary


def test_disconnected_merge_publishes_with_own_credentials_without_app_checks(
    monkeypatch, tmp_path
):
    run_own = credentialed_git._run_own_credentials
    repo, lane, _ctx = make_local_checkout(monkeypatch, tmp_path, "unfetched-remote")
    source = git(lane, "rev-parse", "HEAD")
    with authenticated_remote(tmp_path) as (url, remote, requests):
        git(repo, "push", str(remote), "main")
        config = own_credential_config(tmp_path, url)
        with config.open("a") as stream:
            stream.write(
                f'[url "{url}"]\n\tinsteadOf = https://github.com/example/local.git\n'
            )
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
        monkeypatch.setattr(
            credentialed_git,
            "contact_url",
            lambda *_a: "https://github.com/example/local.git",
        )
        monkeypatch.setattr(credentialed_git, "_run_own_credentials", run_own)
        outcome = boundary.merge_standalone_branch(
            item_id=7,
            branch="finished",
            commit_sha=source,
            target="main",
            repo_root=str(repo),
            project="local-project",
            local_merge=True,
        )
        assert outcome.ok, outcome.error
        assert outcome.pushed
        assert outcome.error == ""
        assert "pushed with your own git credentials" in outcome.output
        assert "pushed with your own git credentials" in outcome.publication_message
        assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "main")
        assert any(requests)
        assert_landed_clean(repo, lane, source)
