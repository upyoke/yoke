"""Installed Git credential helper runtime and import-isolation coverage."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from runtime.api.cli.test_onboard_source_dev_apply import (
    _git,
    _github_app_config,
)
from yoke_cli.config import github_git_credentials
from yoke_cli.config import github_git_credential_bundle
from yoke_cli.config import github_git_credential_launcher
from yoke_contracts import github_app_tokens


def _write_refresh_sitecustomize(
    root: Path,
    token: str,
    *,
    call_marker: Path | None = None,
) -> None:
    """Make a helper subprocess receive one deterministic OAuth response."""

    root.mkdir(parents=True, exist_ok=True)
    body = json.dumps({
        "access_token": token,
        "expires_in": 28_800,
        "refresh_token": "rotated-refresh-secret",
        "refresh_token_expires_in": 15_552_000,
        "scope": "",
        "token_type": "bearer",
    }).encode("utf-8")
    (root / "sitecustomize.py").write_text(
        "import builtins\n"
        "import urllib.request\n"
        f"_BODY = {body!r}\n"
        "class _Response:\n"
        "    def __init__(self, url): self.url = url\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *args): return False\n"
        "    def read(self, size=-1): return _BODY[:size] if size >= 0 else _BODY\n"
        "    def geturl(self): return self.url\n"
        "class _Opener:\n"
        "    def open(self, request, timeout=None):\n"
        + (
            f"        builtins.open({str(call_marker)!r}, 'w').write('called')\n"
            if call_marker is not None else ""
        )
        + "        return _Response(request.full_url)\n"
        "urllib.request.build_opener = lambda *args, **kwargs: _Opener()\n",
        encoding="utf-8",
    )


def _install_injected_local_product_bundle(
    site: Path,
    source_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: github_app_tokens.LocalProductGitHubAppProfile,
) -> Path:
    """Build the standalone helper with one test-only release profile."""

    original_sources = github_git_credential_bundle._bundle_sources()
    injected_contract = source_root / "github_app_tokens.py"
    contract_source = Path(github_app_tokens.__file__).read_text(encoding="utf-8")
    declaration_start = (
        "BUNDLED_LOCAL_PRODUCT_GITHUB_APP_PROFILE: "
        "LocalProductGitHubAppProfile | None ="
    )
    start = contract_source.index(declaration_start)
    end = contract_source.index("\n\n\ndef local_product_profile_values", start)
    injected = (
        "BUNDLED_LOCAL_PRODUCT_GITHUB_APP_PROFILE: "
        "LocalProductGitHubAppProfile | None = "
        f"LocalProductGitHubAppProfile{tuple(profile)!r}"
    )
    injected_contract.write_text(
        contract_source[:start] + injected + contract_source[end:],
        encoding="utf-8",
    )
    sources = tuple(
        (
            injected_contract,
            target,
        )
        if target == github_git_credential_bundle.STABLE_TOKEN_CONTRACT_NAME
        else (source, target)
        for source, target in original_sources
    )
    monkeypatch.setattr(
        github_git_credential_bundle, "_bundle_sources", lambda: sources,
    )
    return github_git_credentials.install_stable_helper(site)


def test_github_helper_key_uses_configured_ghes_authority() -> None:
    assert github_git_credentials.credential_helper_key(
        "https://github.enterprise.example:8443"
    ) == "credential.https://github.enterprise.example:8443.helper"


def test_github_push_helper_serves_token_without_persisting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    token = "helper-secret"
    token_file = (
        Path(os.environ["YOKE_MACHINE_HOME"])
        / "secrets"
        / f"github-app-user-{'a' * 32}.json"
    )
    config = tmp_path / "config.json"
    _github_app_config(config, token_file, token)
    hooks = tmp_path / "python-hooks"
    _write_refresh_sitecustomize(hooks, token)
    monkeypatch.setenv("PYTHONPATH", str(hooks))
    _git(root, "config", "--local", github_git_credentials.GIT_CREDENTIAL_HELPER_KEY, "")
    helper_path = github_git_credentials.install_stable_helper(tmp_path / "site")
    _git(
        root, "config", "--local",
        github_git_credentials.GITHUB_CREDENTIAL_HELPER_KEY,
        github_git_credentials.helper_command(
            config_path=config, helper_path=helper_path,
        ),
    )

    filled = _git(
        root, "credential", "fill",
        input_text="protocol=https\nhost=github.com\n\n",
    )

    assert "username=x-access-token" in filled
    assert f"password={token}" in filled
    config_text = (root / ".git" / "config").read_text(encoding="utf-8")
    assert token not in config_text
    assert str(token_file) not in config_text


def test_github_push_helper_survives_editable_import_repoint(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    token = "repoint-secret"
    token_file = (
        Path(os.environ["YOKE_MACHINE_HOME"])
        / "secrets"
        / f"github-app-user-{'a' * 32}.json"
    )
    config = tmp_path / "config.json"
    _github_app_config(config, token_file, token)
    helper_path = github_git_credentials.install_stable_helper(tmp_path / "site")
    _git(root, "config", "--local", github_git_credentials.GIT_CREDENTIAL_HELPER_KEY, "")
    _git(
        root, "config", "--local",
        github_git_credentials.GITHUB_CREDENTIAL_HELPER_KEY,
        github_git_credentials.helper_command(
            config_path=config, helper_path=helper_path,
        ),
    )
    repointed = tmp_path / "repointed" / "yoke_cli"
    hostile_config = repointed / "config"
    hostile_config.mkdir(parents=True)
    (repointed / "__init__.py").write_text(
        "# conflicting installed package\n",
        encoding="utf-8",
    )
    (hostile_config / "__init__.py").write_text("", encoding="utf-8")
    (hostile_config / "github_git_credential_store.py").write_text(
        "raise RuntimeError('conflicting installed store must not run')\n",
        encoding="utf-8",
    )
    _write_refresh_sitecustomize(repointed.parent, token)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repointed.parent)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    result = subprocess.run(
        ["git", "credential", "fill"],
        cwd=root,
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=env,
    )

    assert "username=x-access-token" in result.stdout
    assert f"password={token}" in result.stdout
    bundle = github_git_credential_launcher.selected_bundle(tmp_path / "site")
    helper_text = (
        bundle / github_git_credentials.STABLE_HELPER_FILE_NAME
    ).read_text(encoding="utf-8")
    assert "_yoke_github_git_credential_store" in helper_text
    assert (
        bundle / github_git_credentials.STABLE_STORE_FILE_NAME
    ).is_file()


def test_standalone_helper_proves_bundled_local_product_before_oauth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    token = "local-product-secret"
    token_file = (
        Path(os.environ["YOKE_MACHINE_HOME"])
        / "secrets"
        / f"github-app-user-{'a' * 32}.json"
    )
    config = tmp_path / "config.json"
    _github_app_config(config, token_file, token)
    profile = github_app_tokens.LocalProductGitHubAppProfile(
        client_id="Iv1.local",
        app_slug="yoke",
        app_id=123,
        api_url="https://api.github.com",
        web_url="https://github.com",
    )
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["github"]["profile_source"] = "local_product"
    config.write_text(json.dumps(payload), encoding="utf-8")
    helper_path = _install_injected_local_product_bundle(
        tmp_path / "site", tmp_path, monkeypatch, profile,
    )
    _git(root, "config", "--local", github_git_credentials.GIT_CREDENTIAL_HELPER_KEY, "")
    _git(
        root, "config", "--local",
        github_git_credentials.GITHUB_CREDENTIAL_HELPER_KEY,
        github_git_credentials.helper_command(
            config_path=config, helper_path=helper_path,
        ),
    )
    repointed = tmp_path / "repointed" / "yoke_cli"
    hostile_config = repointed / "config"
    hostile_config.mkdir(parents=True)
    (repointed / "__init__.py").write_text("", encoding="utf-8")
    (hostile_config / "__init__.py").write_text("", encoding="utf-8")
    (hostile_config / "github_git_credential_store.py").write_text(
        "raise RuntimeError('editable import must not run')\n", encoding="utf-8",
    )
    oauth_marker = tmp_path / "oauth-called"
    _write_refresh_sitecustomize(
        repointed.parent, token, call_marker=oauth_marker,
    )
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(repointed.parent),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    })

    filled = subprocess.run(
        ["git", "credential", "fill"],
        cwd=root,
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=env,
    )

    assert oauth_marker.is_file()
    assert f"password={token}" in filled.stdout
    oauth_marker.unlink()
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["github"]["app_id"] = 999
    config.write_text(json.dumps(payload), encoding="utf-8")
    rejected = subprocess.run(
        ["git", "credential", "fill"],
        cwd=root,
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )

    assert rejected.returncode != 0
    assert not oauth_marker.exists()
    assert token not in rejected.stdout
    assert token not in rejected.stderr
