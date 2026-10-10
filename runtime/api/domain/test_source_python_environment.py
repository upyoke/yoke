"""Locked checkout checks reject stale, missing, and redirected environments."""

import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from runtime.api.source_pythonpath_test_helpers import provision_stub_environment
from yoke_core.domain import source_python_environment as environment
from yoke_core.domain.qa_environment_declaration import TestEnvironmentDeclaration
from yoke_core.domain import qa_environment_declaration as declarations
from yoke_contracts.project_defaults import MissingProjectError


def test_disposable_candidate_uses_command_project_without_checkout_mapping(
    tmp_path, monkeypatch
):
    provision_stub_environment(tmp_path)
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(
        "yoke_core.domain.project_selection.default_project_for_directory",
        lambda _directory: None,
    )
    reads = []

    def read_settings(project, *, strict=False):
        reads.append((project, strict))
        return {}

    monkeypatch.setattr(declarations, "_read_settings", read_settings)
    binding = environment.resolve(tmp_path, dict(os.environ, YOKE_PROJECT="fixture"))
    assert reads == [("fixture", True)]
    assert Path(binding.evidence["root"]) == tmp_path


def test_disposable_candidate_without_project_keeps_named_refusal(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(
        "yoke_core.domain.project_selection.default_project_for_directory",
        lambda _directory: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.relay",
        lambda *_args: {"rows": [{"slug": "fixture"}]},
    )
    with pytest.raises(environment.SourceEnvironmentRefusal) as refused:
        environment.resolve(tmp_path, os.environ)
    assert isinstance(refused.value.__cause__, MissingProjectError)
    assert "SOURCE-ENVIRONMENT-DECLARATION" in str(refused.value)
    assert "--project" in str(refused.value)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    provision_stub_environment(tmp_path)
    monkeypatch.setattr(
        environment,
        "load_declaration",
        lambda **_kwargs: TestEnvironmentDeclaration(project="fixture"),
    )
    return tmp_path


def test_fresh_environment_reports_its_identity_and_ignores_ambient_redirect(lane):
    incoming = dict(os.environ, UV_PROJECT_ENVIRONMENT="/missing/main", UV_NO_DEV="1")
    binding = environment.resolve(lane, incoming)
    assert binding.python == str(lane / ".venv/bin/python3")
    assert Path(binding.evidence["prefix"]) == lane / ".venv"
    assert binding.evidence["version"] == sys.version.split()[0]
    assert binding.env["UV_PROJECT_ENVIRONMENT"] == str(lane / ".venv")
    assert "UV_NO_DEV" not in binding.env


@pytest.mark.parametrize("missing", ["uv.lock", ".venv"])
def test_missing_environment_never_runs_ambient_python(lane, missing):
    (lane / missing).rename(lane / (missing + ".absent"))
    with pytest.raises(
        environment.SourceEnvironmentRefusal, match="SOURCE-ENVIRONMENT-.*MISSING"
    ):
        environment.resolve(lane, os.environ)
    assert not (lane / missing).exists()


def test_stale_lock_is_not_rewritten(lane):
    project = lane / "pyproject.toml"
    project.write_text(
        project.read_text().replace('version="0.0.0"', 'version="0.0.1"')
    )
    before = (lane / "uv.lock").read_bytes()
    with pytest.raises(environment.SourceEnvironmentRefusal, match="OUT-OF-DATE"):
        environment.resolve(lane, os.environ)
    assert (lane / "uv.lock").read_bytes() == before


def test_python_requirement_mismatch_refuses_without_downloading(lane):
    project = lane / "pyproject.toml"
    project.write_text(project.read_text().replace(">=3.11", "<3.0"))
    with pytest.raises(environment.SourceEnvironmentRefusal, match="OUT-OF-DATE"):
        environment.resolve(lane, os.environ)


def test_environment_with_undeclared_packages_fails_check(lane):
    site = next((lane / ".venv/lib").glob("python*/site-packages"))
    metadata = site / "main_only-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: main-only\nVersion: 1.0\n"
    )
    with pytest.raises(environment.SourceEnvironmentRefusal, match="OUT-OF-DATE"):
        environment.resolve(lane, os.environ)


def test_declared_groups_are_checked_in_the_same_environment(lane, monkeypatch):
    monkeypatch.setattr(
        environment,
        "load_declaration",
        lambda **_kwargs: TestEnvironmentDeclaration(
            project="fixture", groups=("checks",)
        ),
    )
    project = lane / "pyproject.toml"
    project.write_text(project.read_text() + "[dependency-groups]\nchecks=[]\n")
    subprocess.run(
        ["uv", "lock", "--offline"], cwd=lane, capture_output=True, check=True
    )
    assert environment.resolve(lane, os.environ).evidence["groups"] == ["checks"]


def test_declared_project_cannot_escape_candidate(lane, monkeypatch):
    monkeypatch.setattr(
        environment,
        "load_declaration",
        lambda **_kwargs: TestEnvironmentDeclaration(
            project="fixture", uv_project=".."
        ),
    )
    with pytest.raises(environment.SourceEnvironmentRefusal, match="LOCK-MISSING"):
        environment.resolve(lane, os.environ)


def test_unreachable_declaration_is_a_named_refusal(lane, monkeypatch):
    def unavailable(**_kwargs):
        raise ConnectionError("unreachable")

    monkeypatch.setattr(environment, "load_declaration", unavailable)
    with pytest.raises(environment.SourceEnvironmentRefusal, match="DECLARATION"):
        environment.resolve(lane, os.environ)


def test_python_pin_mismatch_cannot_replace_the_environment(lane):
    (lane / ".python-version").write_text(
        f"{sys.version_info.major}.{sys.version_info.minor + 1}\n"
    )
    before = (lane / ".venv/pyvenv.cfg").read_bytes()
    with pytest.raises(environment.SourceEnvironmentRefusal, match="OUT-OF-DATE"):
        environment.resolve(lane, os.environ)
    assert (lane / ".venv/pyvenv.cfg").read_bytes() == before


@pytest.mark.parametrize(
    "python_request",
    [f"{sys.version_info.major}.{sys.version_info.minor}", sys.version.split()[0]],
)
def test_matching_python_request_keeps_the_candidate_interpreter(lane, python_request):
    (lane / ".python-version").write_text(python_request + "\n")
    assert environment.resolve(lane, os.environ).python == str(
        lane / ".venv/bin/python3"
    )


@pytest.mark.parametrize(
    "path,missing", [("$.payload.cap_type", True), ("$.payload.project", False)]
)
def test_only_absent_capability_can_use_default_groups(
    tmp_path, monkeypatch, path, missing
):
    monkeypatch.setattr(
        declarations, "required_local_project", lambda *_args: "fixture"
    )
    response = SimpleNamespace(
        success=False, error=SimpleNamespace(code="not_found", jsonpath=path)
    )
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        lambda **_kwargs: response,
    )
    if missing:
        assert (
            declarations.load_declaration(checkout=tmp_path, strict=True).groups == ()
        )
    else:
        with pytest.raises(RuntimeError):
            declarations.load_declaration(checkout=tmp_path, strict=True)
