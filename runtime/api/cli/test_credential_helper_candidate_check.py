"""Release helper checks never mutate the live install or Git configuration."""

import json
import sys

import pytest

from runtime.api.cli.cli_release_runtime_test_support import candidate
from runtime.api.cli.github_git_credential_install_test_support import (
    _configured_repo,
    _git,
)
from yoke_cli.commands.adapters.github_credential_helper import (
    github_credential_helper_refresh,
)
from yoke_cli.config import cli_release_runtime as runtime
from yoke_cli.config import github_git_credentials as credentials
from yoke_cli.config import github_credential_helper_check as check
from yoke_cli.config import machine_config


def _registered_repo(tmp_path, monkeypatch):
    repo, config, _ = _configured_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(
        machine_config, "all_registered_checkouts", lambda *_a, **_k: [repo]
    )
    return repo, config


def test_missing_release_shim_refuses_refresh_without_writing_git(
    tmp_path, monkeypatch, capsys
):
    repo, config = _registered_repo(tmp_path, monkeypatch)
    root = tmp_path / "yoke-cli-releases"
    python = root / "releases/old/tools/yoke-cli/bin/python3"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    monkeypatch.setattr(credentials.sys, "executable", str(python))
    monkeypatch.setattr(credentials.sys, "prefix", str(python.parent.parent))
    # The saved reference is owned even though the stable shim was lost.
    helper = root / "github-credential-helper" / credentials.STABLE_HELPER_FILE_NAME
    from yoke_contracts.git_credential_command import helper_command

    _git(
        repo,
        "config",
        credentials.GITHUB_CREDENTIAL_HELPER_KEY,
        helper_command(root / "python", helper, config),
    )
    before = (repo / ".git/config").read_bytes()
    assert github_credential_helper_refresh(["--config", str(config), "--json"]) == 1
    receipt = json.loads(capsys.readouterr().out)
    assert "github_helper_interpreter_unavailable" in receipt["error"]
    assert "yoke update" in receipt["error"]
    assert (repo / ".git/config").read_bytes() == before
    assert not helper.exists()


def test_check_only_validates_release_python_without_stable_shim(
    tmp_path, monkeypatch, capsys
):
    repo, config = _registered_repo(tmp_path, monkeypatch)
    root = tmp_path / "yoke-cli-releases"
    python = root / "releases/new/tools/yoke-cli/bin/python3"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    monkeypatch.setattr(credentials.sys, "executable", str(python))
    monkeypatch.setattr(credentials.sys, "prefix", str(python.parent.parent))
    # A stale prior-release helper is classified but never rewritten by a probe.
    helper = root / "releases/old/lib/python3.10" / credentials.STABLE_HELPER_FILE_NAME
    from yoke_contracts.git_credential_command import helper_command

    _git(
        repo,
        "config",
        credentials.GITHUB_CREDENTIAL_HELPER_KEY,
        helper_command(root / "releases/old/bin/python", helper, config),
    )
    before = (repo / ".git/config").read_bytes()
    assert (
        github_credential_helper_refresh(
            ["--config", str(config), "--check-only", "--json"]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"checked": True}
    assert not (root / "python").exists()
    assert not (root / "github-credential-helper").exists()
    assert (repo / ".git/config").read_bytes() == before


def test_broken_bundle_source_fails_candidate_check(tmp_path, monkeypatch):
    monkeypatch.setattr(
        check.bundle, "_bundle_sources", lambda: [(tmp_path / "missing", "helper.py")]
    )
    result = check.check_candidate()
    assert result["checked"] is False
    assert "github_helper_candidate_invalid" in result["error"]
    assert "yoke update" in result["error"]


@pytest.mark.windows
def test_probe_uses_only_check_mode_and_preserves_publication(tmp_path):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    old = candidate(root, "old")
    runtime.activate(root, old, bin_dir, "old")
    new = candidate(root, "new")
    # Candidate refuses any mutating credential refresh; a missing check receipt fails.
    site = next(
        path
        for pattern in ("lib/python*/site-packages", "Lib/site-packages")
        for path in (new / "tools/yoke-cli").glob(pattern)
    )
    main = site / "yoke_cli/main.py"
    main.write_text(
        main.read_text().replace(
            "print(json.dumps({'checked': True}))",
            "assert '--check-only' in argv; print(json.dumps({'error': 'broken bundle'}))",
        )
    )
    paths = [root / "current", root / "launcher", root / "python", bin_dir / "yoke"]
    before = {path: path.read_bytes() for path in paths}
    with pytest.raises(RuntimeError, match="cli_candidate_helper_check_failed"):
        runtime.activate(root, new, bin_dir, "new")
    assert {path: path.read_bytes() for path in paths} == before
