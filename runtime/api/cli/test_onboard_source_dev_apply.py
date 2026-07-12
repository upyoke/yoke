"""The "Develop Yoke itself" onboard apply wires a Yoke source checkout by
running the shared dev-setup engine — an editable install (via ``uv``, since the
product tool venv ships no ``pip``) followed by a source-link pass in a FRESH
subprocess.

The product ``yoke`` process cannot import ``yoke_core`` (it is not a dependency
of ``yoke-cli``), so source-link can never run in-process; the engine does the
editable install first, then shells out to a new interpreter that resolves the
checkout. Review-screen labels + the GitHub push-list live in
``test_onboard_source_dev_review.py``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import dev_setup
from yoke_cli.config import github_git_credentials
from yoke_cli.config import github_git_credential_launcher
from yoke_cli.config import github_git_credential_store
from yoke_cli.config import project_onboard_apply
from yoke_cli.config.project_onboard_support import ProjectOnboardError


def _github_app_config(config: Path, credential: Path, token: str) -> None:
    github_git_credential_store.write_credential_document(credential, {
        "schema_version": 2,
        "refresh_token": "refresh-secret",
        "refresh_expires_at": "2099-12-09T17:00:00+00:00",
    })
    config.write_text(json.dumps({
        "schema_version": 1,
        "active_env": "local",
        "connections": {
            "local": {"transport": "local-postgres", "prod": False},
        },
        "github": {
            "api_url": "https://api.github.com", "web_url": "https://github.com",
            "app_slug": "yoke", "app_id": 123, "client_id": "Iv1.local",
            "profile_source": "local_explicit",
            "authorization": {
                "kind": "github_app_user_authorization",
                "status": "authorized",
                "refresh_credential_ref": str(credential),
            },
        },
    }), encoding="utf-8")
    config.chmod(0o600)


def _yoke_source_checkout(root: Path) -> Path:
    """A tree that ``is_yoke_source_checkout`` accepts."""
    (root / "runtime" / "harness").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n', encoding="utf-8",
    )
    return root


def _finish(root: Path, config: Path, **overrides):
    kwargs = dict(
        operation="onboard.source-dev-admin",
        root=root,
        result={"project": {"id": 1, "slug": "yoke"}},
        github_adoption={},
        config_path=config,
        progress=None,
        github_auth_target="source-dev",
        scaffold_action="project-install-scaffold",
        reuse_github_auth=True,
    )
    kwargs.update(overrides)
    return project_onboard_apply.finish_after_dispatch(**kwargs)


def _isolate_report(monkeypatch) -> None:
    # Capture the chosen install result; skip the checklist/handoff dispatch and
    # the machine-config mapping write, which are not what this seam decides.
    monkeypatch.setattr(
        project_onboard_apply, "applied_report",
        lambda operation, root, project, install, *a, **k: {"install": install},
    )
    monkeypatch.setattr(
        project_onboard_apply, "project_mapping_needs_write", lambda *a, **k: False,
    )


def _forbid_product_install(monkeypatch) -> None:
    def _no_product_install(*args, **kwargs):
        raise AssertionError("product-copy install must not run here")

    monkeypatch.setattr(
        project_onboard_apply.install_runner, "install", _no_product_install,
    )


def _git(root: Path, *args: str, input_text: str | None = None) -> str:
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=env,
    )
    return result.stdout


def test_yoke_source_checkout_apply_runs_dev_setup_engine(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    root = _yoke_source_checkout(tmp_path / "yoke")
    seen: dict[str, Path] = {}

    def _fake_engine(repo_root, **kwargs):
        seen["engine"] = Path(repo_root)
        seen["editable_install"] = kwargs.get("editable_install")
        return {
            "strategy": "source-link",
            "machine_config_newly_registered": False,
            "warnings": [],
        }

    _forbid_product_install(monkeypatch)
    monkeypatch.setattr(
        project_onboard_apply.dev_setup, "install_source_checkout", _fake_engine,
    )
    _isolate_report(monkeypatch)

    config = tmp_path / "config.json"
    report = _finish(root, config)

    assert seen["engine"] == root
    # The editable install is DEFERRED to after the UI, so the in-UI apply runs
    # source-link only and records the checkout for the post-UI step.
    assert seen["editable_install"] is False
    assert project_onboard_apply.pop_pending_dev_install(config) == str(root)
    assert report["install"]["strategy"] == "source-link"
    # project_id is stamped on so the onboarding handoff (checkout-binding) works.
    assert report["install"]["project_id"] == 1


def test_source_dev_apply_configures_github_push_helper(
    tmp_path: Path, monkeypatch
) -> None:
    root = _yoke_source_checkout(tmp_path / "yoke")
    _git(root, "init")
    token = "source-dev-secret"
    token_file = (
        tmp_path / "home" / "secrets" / f"github-app-user-{'a' * 32}.json"
    )
    config = tmp_path / "config.json"
    _github_app_config(config, token_file, token)

    def _fake_engine(_repo_root, **_kwargs):
        return {
            "strategy": "source-link",
            "machine_config_newly_registered": False,
            "warnings": [],
        }

    _forbid_product_install(monkeypatch)
    monkeypatch.setattr(
        project_onboard_apply.dev_setup, "install_source_checkout", _fake_engine,
    )
    _isolate_report(monkeypatch)
    monkeypatch.setattr(
        github_git_credentials, "_helper_site_dir", lambda: tmp_path / "site",
    )

    report = _finish(root, config)

    git_credentials = report["install"]["git_credentials"]
    assert git_credentials["configured"] is True
    assert "credential_source" not in git_credentials
    assert str(token_file) not in json.dumps(report)
    helper = _git(
        root, "config", "--local", "--get",
        github_git_credentials.GITHUB_CREDENTIAL_HELPER_KEY,
    )
    assert str(config) in helper
    assert github_git_credentials.STABLE_HELPER_FILE_NAME in helper
    assert "yoke_cli.config.github_git_credential_helper" not in helper
    bundle = github_git_credential_launcher.selected_bundle(tmp_path / "site")
    for stable_name in (
        github_git_credentials.STABLE_STORE_FILE_NAME,
        github_git_credentials.STABLE_FILE_IO_NAME,
        github_git_credentials.STABLE_ORIGIN_FILE_NAME,
        github_git_credentials.STABLE_TOKEN_CONTRACT_NAME,
    ):
        assert (bundle / stable_name).is_file()
    assert subprocess.run(
        ["git", "config", "--local", "--get-all", "credential.helper"],
        cwd=root, text=True, capture_output=True, check=False,
    ).returncode == 1
    config_text = (root / ".git" / "config").read_text(encoding="utf-8")
    assert token not in config_text
    assert str(token_file) not in config_text


def test_external_checkout_apply_still_uses_product_install(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "external"
    root.mkdir()  # not a Yoke source checkout
    seen: dict[str, Path] = {}

    def _fake_product_install(root_, *, project_id, config_path, operation):
        seen["product"] = Path(root_)
        return {"machine_config_newly_registered": False}

    def _no_engine(*args, **kwargs):
        raise AssertionError("dev-setup engine must not run for an external repo")

    monkeypatch.setattr(
        project_onboard_apply.install_runner, "install", _fake_product_install,
    )
    monkeypatch.setattr(
        project_onboard_apply.dev_setup, "install_source_checkout", _no_engine,
    )
    _isolate_report(monkeypatch)

    _finish(root, tmp_path / "config.json", operation="onboard.project")

    assert seen["product"] == root


def test_source_dev_apply_refuses_non_yoke_folder(
    tmp_path: Path, monkeypatch
) -> None:
    # A source-dev apply that did not land on a real Yoke checkout must refuse,
    # never silently product-install a scaffold and report success.
    root = tmp_path / "not-yoke"
    root.mkdir()  # exists but is not a Yoke source tree

    def _no_engine(*args, **kwargs):
        raise AssertionError("dev-setup engine must not run on a non-Yoke folder")

    _forbid_product_install(monkeypatch)
    monkeypatch.setattr(
        project_onboard_apply.dev_setup, "install_source_checkout", _no_engine,
    )
    _isolate_report(monkeypatch)

    with pytest.raises(ProjectOnboardError):
        _finish(root, tmp_path / "config.json")


def test_source_dev_engine_error_becomes_onboard_error(
    tmp_path: Path, monkeypatch
) -> None:
    # A DevSetupError from the engine (uv missing, editable install failed, …)
    # surfaces as a clean ProjectOnboardError, not a raw traceback.
    root = _yoke_source_checkout(tmp_path / "yoke")

    def _boom(*args, **kwargs):
        raise dev_setup.DevSetupError("editable install failed: no uv")

    _forbid_product_install(monkeypatch)
    monkeypatch.setattr(
        project_onboard_apply.dev_setup, "install_source_checkout", _boom,
    )
    _isolate_report(monkeypatch)

    with pytest.raises(ProjectOnboardError):
        _finish(root, tmp_path / "config.json")


# ---------------------------------------------------------------- engine ----


def test_install_source_checkout_editable_precedes_source_link(
    tmp_path: Path, monkeypatch
) -> None:
    # The editable install MUST run before source-link: source-link imports
    # yoke-core, which only resolves in a subprocess started after the editable
    # `.pth` shim is written.
    root = _yoke_source_checkout(tmp_path / "yoke")
    order: list[str] = []

    def _fake_editable(_root):
        order.append("editable")
        return {"ok": True}

    def _fake_source_link(_root):
        order.append("source-link")
        return {"mode": "source-link", "warnings": []}

    monkeypatch.setattr(dev_setup, "_run_editable_install", _fake_editable)
    monkeypatch.setattr(dev_setup, "_run_source_link_subprocess", _fake_source_link)

    result = dev_setup.install_source_checkout(root)

    assert order == ["editable", "source-link"]
    assert result["strategy"] == dev_setup.MODE_SOURCE_LINK
    assert result["editable_install"] == {"ok": True}
    assert result["source_link"]["mode"] == "source-link"


def test_install_source_checkout_can_skip_editable(
    tmp_path: Path, monkeypatch
) -> None:
    root = _yoke_source_checkout(tmp_path / "yoke")

    def _no_editable(_root):
        raise AssertionError("editable install must be skipped")

    monkeypatch.setattr(dev_setup, "_run_editable_install", _no_editable)
    monkeypatch.setattr(
        dev_setup, "_run_source_link_subprocess", lambda _root: {"warnings": []},
    )

    result = dev_setup.install_source_checkout(root, editable_install=False)

    assert "editable_install" not in result


def test_run_editable_install_prefers_uv(tmp_path: Path, monkeypatch) -> None:
    root = _yoke_source_checkout(tmp_path / "yoke")
    for name in ("yoke-contracts", "yoke-core", "yoke-cli", "yoke-harness"):
        pkg = root / "packages" / name
        pkg.mkdir(parents=True)
        (pkg / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    captured: dict[str, list[str]] = {}

    class _Ok:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(dev_setup, "_find_uv", lambda: "/opt/uv")
    monkeypatch.setattr(
        dev_setup.subprocess, "run",
        lambda command, **kwargs: captured.__setitem__("command", command) or _Ok(),
    )
    monkeypatch.setattr(
        dev_setup.editable_install, "swap_to_config_driven",
        lambda site, *, repo_root, loader_source_text=None: {"ok": True},
    )
    monkeypatch.setattr(
        dev_setup.editable_install, "site_packages_dir", lambda: tmp_path / "sp",
    )

    dev_setup._run_editable_install(root)

    assert captured["command"][:4] == ["/opt/uv", "pip", "install", "--python"]


def test_run_editable_install_reads_loader_before_uv(
    tmp_path: Path, monkeypatch
) -> None:
    # Regression: `uv pip install -e` uninstalls the product wheel this process
    # imported the loader template from, so the template must be read BEFORE the
    # editable install runs — reading it after would hit a now-deleted file.
    root = _yoke_source_checkout(tmp_path / "yoke")
    for name in ("yoke-contracts", "yoke-core", "yoke-cli", "yoke-harness"):
        pkg = root / "packages" / name
        pkg.mkdir(parents=True)
        (pkg / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    template = tmp_path / "_editable_loader_template.py"
    template.write_text("LOADER SOURCE", encoding="utf-8")
    monkeypatch.setattr(
        dev_setup.editable_install, "loader_source",
        lambda: template.read_text(encoding="utf-8"),
    )

    class _Ok:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_uv_run(command, **kwargs):
        template.unlink()  # uv removes the product wheel mid-install
        return _Ok()

    monkeypatch.setattr(dev_setup, "_find_uv", lambda: "/opt/uv")
    monkeypatch.setattr(dev_setup.subprocess, "run", _fake_uv_run)
    captured: dict[str, str | None] = {}
    monkeypatch.setattr(
        dev_setup.editable_install, "swap_to_config_driven",
        lambda site, *, repo_root, loader_source_text=None: captured.update(
            text=loader_source_text
        ) or {"ok": True},
    )
    monkeypatch.setattr(
        dev_setup.editable_install, "site_packages_dir", lambda: tmp_path / "sp",
    )

    dev_setup._run_editable_install(root)

    # Captured before uv deleted the wheel — not read afterward.
    assert captured["text"] == "LOADER SOURCE"


def test_run_source_link_subprocess_invokes_module(
    tmp_path: Path, monkeypatch
) -> None:
    root = _yoke_source_checkout(tmp_path / "yoke")
    captured: dict[str, list[str]] = {}

    class _Ok:
        returncode = 0
        stdout = '{"mode": "source-link", "warnings": []}'
        stderr = ""

    monkeypatch.setattr(
        dev_setup.subprocess, "run",
        lambda command, **kwargs: captured.__setitem__("command", command) or _Ok(),
    )

    result = dev_setup._run_source_link_subprocess(root)

    # Calls the existing install_source_link via `-c` (version-robust), not a
    # dedicated `-m` entrypoint the cloned checkout may not have.
    assert "-c" in captured["command"]
    assert any("install_source_link" in part for part in captured["command"])
    assert result["mode"] == "source-link"


def test_run_source_link_subprocess_raises_on_failure(
    tmp_path: Path, monkeypatch
) -> None:
    root = _yoke_source_checkout(tmp_path / "yoke")

    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(dev_setup.subprocess, "run", lambda command, **kwargs: _Fail())

    with pytest.raises(dev_setup.DevSetupError):
        dev_setup._run_source_link_subprocess(root)
