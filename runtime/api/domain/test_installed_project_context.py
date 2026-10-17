"""Installed release guidance, HTTPS bundle delivery and managed-file recovery."""

import json
from pathlib import Path

import pytest

from runtime.api.cli import project_onboarding_test_helpers as https_fixture
from runtime.api.cli import project_onboarding_api_handler as https_handler
from runtime.api.tools.source_project_bundle import build_source_bundle
from yoke_cli.project_install import instruction_discovery, install_recovery
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install.files import ProjectInstallError, sha256_text
from yoke_cli.project_install.transport import resolve_bundle
from yoke_contracts.project_contract.install_bundle import BUNDLE_SCHEMA
from yoke_core.domain.install_bundle_sources import (
    HARNESS_MANIFEST_SOURCES,
    InstallBundleTreeError,
    harness_manifest_files,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def bundle(monkeypatch):
    monkeypatch.setattr(instruction_discovery.shutil, "which", lambda _: None)
    return build_source_bundle(ROOT, project_id=41, project_slug="demo")


def test_https_install_and_refresh_need_no_source_in_target(
    tmp_path,
    monkeypatch,
    bundle,
):
    monkeypatch.setattr(https_handler, "install_bundle", lambda _: bundle)
    target = tmp_path / "unrelated-project"
    target.mkdir()
    (target / "README.md").write_text("This project's own documentation.\n")
    with https_fixture.ProjectOnboardApi() as api:
        config = https_fixture.write_https_config(tmp_path, "test-token", api.url)
        resolved, source = resolve_bundle(41, explicit_env="prod", config_path=config)
        assert source == api.url
        apply_bundle(target, resolved, source=source)
        assert api.requests_for("GET", "/v1/projects/41/install-bundle")
    assert not (target / "runtime").exists()
    help_text = (target / ".agents/skills/yoke/help/SKILL.md").read_text()
    assert ".yoke/docs/index.md" in help_text
    assert "see README.md" not in help_text
    assert (target / ".yoke/docs/index.md").is_file()
    manifest = json.loads((target / ".yoke/install-manifest.json").read_text())
    for entry, source_rel in zip(
        harness_manifest_files(ROOT), HARNESS_MANIFEST_SOURCES
    ):
        installed = target / entry["path"]
        assert installed.read_bytes() == (ROOT / source_rel).read_bytes()
        assert manifest["files"][entry["path"]] == sha256_text(entry["content"])
    rel = ".yoke/harness/codex/manifest.json"
    (target / rel).unlink()
    report = apply_bundle(target, bundle, operation="refresh")
    assert rel in report["install_drift"]["missing"]
    assert apply_bundle(target, bundle, operation="refresh")["files_written"] == []
    assert (target / "README.md").read_text() == "This project's own documentation.\n"


def test_manifest_local_edit_refuses_without_overwriting(tmp_path, bundle):
    apply_bundle(tmp_path, bundle)
    path = tmp_path / ".yoke/harness/claude/manifest.json"
    path.write_text('{"local": "edit"}\n')
    with pytest.raises(ProjectInstallError, match="install_drift_local_edits"):
        apply_bundle(tmp_path, bundle, operation="refresh")
    assert json.loads(path.read_text()) == {"local": "edit"}
    assert not install_recovery.pending(tmp_path)


def test_interrupted_manifest_refresh_resumes_the_existing_record(
    tmp_path,
    monkeypatch,
    bundle,
):
    apply_bundle(tmp_path, bundle)
    newer = dict(bundle, files=[dict(entry) for entry in bundle["files"]])
    for entry in newer["files"]:
        if entry["path"].startswith(".yoke/harness/"):
            value = json.loads(entry["content"])
            value["release_test"] = True
            entry["content"] = json.dumps(value) + "\n"
    original = install_recovery.atomic_text
    seen = 0

    def interrupted(path, text):
        nonlocal seen
        if "/.yoke/harness/" in str(path):
            seen += 1
            if seen == 2:
                raise OSError("simulated manifest write interruption")
        original(path, text)

    monkeypatch.setattr(install_recovery, "atomic_text", interrupted)
    with pytest.raises(OSError, match="simulated manifest write interruption"):
        apply_bundle(tmp_path, newer, operation="refresh")
    assert install_recovery.pending(tmp_path)
    monkeypatch.setattr(install_recovery, "atomic_text", original)
    report = apply_bundle(tmp_path, newer, operation="refresh")
    assert report["install_drift"]["interrupted"]
    assert not install_recovery.pending(tmp_path)
    assert apply_bundle(tmp_path, newer, operation="refresh")["files_written"] == []


def test_old_serving_bundle_refuses_before_any_project_write(tmp_path, bundle):
    bundle["bundle_schema"] = BUNDLE_SCHEMA - 1
    with pytest.raises(
        ProjectInstallError, match="installed_manifest_bundle_unavailable"
    ) as error:
        apply_bundle(tmp_path, bundle)
    assert "control-plane operator" in str(error.value)
    assert "yoke project refresh" in str(error.value)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["missing", "invalid_encoding"])
def test_missing_release_manifest_has_named_recovery(tmp_path, failure):
    path = tmp_path / HARNESS_MANIFEST_SOURCES[0]
    if failure == "invalid_encoding":
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\xff")
    with pytest.raises(InstallBundleTreeError, match="Restore this release"):
        harness_manifest_files(tmp_path)


def test_installed_rules_share_manifest_and_registered_context_homes(bundle):
    files = {entry["path"]: entry["content"] for entry in bundle["files"]}
    for path in (
        ".claude/rules/session.md",
        ".agents/skills/yoke/steer/loop.md",
        ".yoke/docs/agents/rules/lanes-and-claims.md",
    ):
        assert ".yoke/harness/<harness-dir>/manifest.json" in files[path]
        assert "runtime/harness/<harness-dir>/manifest.json" not in files[path]
        assert "runtime/harness/manifest-schema.md" not in files[path]
    conduct = files[".agents/skills/yoke/conduct/dispatch-context-project.md"]
    context = files[".agents/skills/yoke/implement/implementing/project-context.md"]
    assert "yoke project-structure get" in conduct
    assert "--family context_routing --json" in conduct
    assert "python3 -m yoke_core.domain.context_routing" not in conduct
    assert "../implement/implementing/project-context.md" in conduct
    assert "entry_key" in context and "payload.docs" in context
    assert "No context entries is an advisory" in context
    assert "A failed read stops" in context
    assert "Missing configured files" in context
