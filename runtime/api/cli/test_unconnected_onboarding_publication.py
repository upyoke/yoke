"""Real skip-mode onboarding publishes opportunistically or completes locally."""

import json
import os

import pytest

from runtime.api.cli.git_http_test_support import (
    authenticated_remote,
    git,
    own_credential_config,
)
from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    write_https_config,
)
from yoke_cli.config import credentialed_git
from yoke_cli.main import main


@pytest.mark.parametrize("credential", [False, True])
def test_unconnected_onboarding_finishes_with_or_without_git_credentials(
    tmp_path, monkeypatch, capsys, credential
):
    home = tmp_path / "home"
    home.mkdir()
    for key, value in {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "YOKE_MACHINE_HOME": str(tmp_path / "machine-home"),
    }.items():
        monkeypatch.setenv(key, value)
    for key in ("SSH_AUTH_SOCK", "YOKE_MACHINE_CONFIG_FILE", "YOKE_ENV"):
        monkeypatch.delenv(key, raising=False)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    git(checkout, "init", "-b", "main")
    git(checkout, "config", "user.name", "Fixture")
    git(checkout, "config", "user.email", "fixture@example.invalid")
    (checkout / "README.md").write_text("base\n")
    git(checkout, "add", ".")
    git(checkout, "commit", "-m", "base")
    origin = "https://github.com/example/repo.git"
    git(checkout, "remote", "add", "origin", origin)
    with authenticated_remote(tmp_path) as (url, remote, _requests):
        git(checkout, "push", str(remote), "main")
        config = own_credential_config(home, url) if credential else home / "gitconfig"
        with config.open("a") as stream:
            stream.write(f'[url "{url}"]\n\tinsteadOf = {origin}\n')
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
        monkeypatch.setattr(credentialed_git, "contact_url", lambda *_a: origin)
        project = {
            "id": 43,
            "slug": "local",
            "name": "Local",
            "github_repo": "example/repo",
            "default_branch": "main",
            "public_item_prefix": "LOC",
        }
        with ProjectOnboardApi(project=project) as api:
            machine = write_https_config(tmp_path, "fixture-token", api.url)
            rc = main(
                [
                    "onboard",
                    "project",
                    str(checkout),
                    "--slug",
                    "local",
                    "--name",
                    "Local",
                    "--github-repo",
                    "example/repo",
                    "--default-branch",
                    "main",
                    "--public-item-prefix",
                    "LOC",
                    "--github-adoption",
                    "disabled",
                    "--config",
                    str(machine),
                    "--yes",
                    "--json",
                ]
            )
            assert rc == 0
            report = json.loads(capsys.readouterr().out)
            assert report["applied"]
            assert report["github_adoption"]["binding"]["status"] == "skipped"
            assert api.function_calls("projects.github_binding.bind") == []
            assert not json.loads(machine.read_text()).get("github")
            publication = report["install"]["publication"]
            if credential:
                assert publication["status"] == "published", publication
                assert publication["detail"] == "pushed with your own git credentials"
                assert git(remote, "rev-parse", "main") == git(
                    checkout, "rev-parse", "HEAD"
                )
            else:
                assert publication["status"] == "publication_pending"
                assert "your own git credentials did not work" in publication["detail"]
                assert "yoke github connect" in publication["detail"]
                assert not (home / ".ssh").exists()
                assert "helper" not in config.read_text()
