"""Prior launcher verification uses its own declaration and never executes it."""

import pytest

from runtime.api.cli.github_git_credential_install_test_support import (
    _configured_repo,
    _git,
)
from yoke_cli.config import github_git_credential_bundle as bundle
from yoke_cli.config import github_git_credential_launcher as launcher
from yoke_cli.config import github_git_credentials as credentials
from yoke_cli.config import github_repo_helper_reconnect as reconnect
from yoke_cli.config import github_prior_runtime_verification as prior
from yoke_contracts import owner_private_path
import sys


@pytest.mark.parametrize("tampered", [False, True])
def test_prior_bundle_with_fewer_files_keeps_hash_verification(
    tmp_path,
    monkeypatch,
    tampered,
):
    repo, config, _credential = _configured_repo(tmp_path, monkeypatch)
    site = tmp_path / "prior-site"
    sources = tuple(
        (path, name)
        for path, name in bundle._bundle_sources()
        if name != launcher.BUNDLE_TIMESTAMPS_NAME
    )
    with monkeypatch.context() as patch:
        patch.setattr(bundle, "_bundle_sources", lambda: sources)
        helper = bundle.install(site)
    source = helper.read_text().replace("    BUNDLE_TIMESTAMPS_NAME,\n", "")
    marker = tmp_path / "executed"
    helper.write_text(source + f"\nopen({str(marker)!r}, 'w').write('bad')\n")
    selected = launcher.selected_bundle(
        site,
        module_names=launcher.prior_launcher_module_names(helper.read_bytes()),
    )
    if tampered:
        (selected / launcher.BUNDLE_ORIGIN_NAME).write_text("tampered")
    command = credentials.helper_command(config_path=config, helper_path=helper)
    _git(repo, "config", "--local", credentials.GITHUB_CREDENTIAL_HELPER_KEY, command)
    monkeypatch.setattr(credentials, "_helper_dir", lambda: tmp_path / "new-site")
    assert credentials._is_yoke_helper(command, config_path=config) is (not tampered)
    assert reconnect._classify_helper_reference(repo, config_path=config) == (
        "ambiguous" if tampered else "match"
    )
    if not tampered:
        report = credentials.configure_repo_helper(repo, config_path=config)
        assert report["configured"] is True
        assert report["changed"] is True
    assert not marker.exists()


@pytest.mark.parametrize(
    "declaration",
    [
        "(__import__('os').system('false'),)",
        "('../escape.py', '_yoke_github_git_credential_helper.py')",
        "('other.py', '_yoke_github_git_credential_helper.py')",
        "('_yoke_github_git_credential_helper.py',)\nBUNDLE_MODULE_NAMES = ()",
    ],
)
def test_prior_launcher_rejects_dynamic_or_unsafe_declarations(declaration):
    with pytest.raises(
        launcher.GitHubCredentialLauncherError, match="declaration is invalid"
    ):
        launcher.prior_launcher_module_names(
            f"BUNDLE_MODULE_NAMES = {declaration}".encode()
        )


@pytest.mark.parametrize('writable_target', ['interpreter', 'helper', None])
def test_prior_runtime_checks_both_file_write_policies(tmp_path, monkeypatch, writable_target):
    helper = bundle.install(tmp_path / 'site')
    python = tmp_path / 'prior-python'
    python.write_text('interpreter', encoding='utf-8')
    python.chmod(0o755)
    monkeypatch.setattr(prior.os, 'access', lambda *_args: True)
    checked = []
    refused = {'interpreter': python.resolve(), 'helper': helper}.get(writable_target)
    def check(path):
        checked.append(path)
        return path != refused
    monkeypatch.setattr(owner_private_path, 'is_others_unwritable_file', check)
    assert prior.verified_prior_runtime_helper(
        python, helper, current_python=tmp_path / 'current-python'
    ) is (writable_target is None)
    assert python.resolve() in checked
    if writable_target != 'interpreter':
        assert helper in checked


def test_current_runtime_bypasses_only_its_own_write_check(tmp_path, monkeypatch):
    helper = bundle.install(tmp_path / 'site')
    from pathlib import Path
    python = Path(sys.executable)
    checked = []
    monkeypatch.setattr(owner_private_path, 'is_others_unwritable_file',
                        lambda path: checked.append(path) or True)
    assert prior.verified_prior_runtime_helper(python, helper, current_python=python)
    assert checked == [helper]
