"""Project-declared Pulumi stack kinds resolve by naming convention."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import project_renderer_pulumi_stack_config as config_module
from yoke_core.domain.project_renderer_pulumi import render_pulumi_artifacts
from yoke_core.domain.project_renderer_pulumi_scoped import (
    render_scoped_pulumi_config,
)
from yoke_core.domain.project_renderer_pulumi_stack_config import (
    build_pulumi_stack_config,
)
from yoke_core.domain.project_renderer_pulumi_stack_types import (
    PROJECT_STACK_RENDER_KEYS,
    STACK_TYPE_SPECS,
    ProjectStackFilesMissing,
    gather_pulumi_stacks,
    stack_type_files,
)
from yoke_core.tools.pulumi_exec import PulumiExecError, execute_pulumi_command
from runtime.api.tools.pulumi_exec_support_test_support import (
    _Child,
    _init_settings,
    _install_pulumi_project_files,
)

_PROVIDER = "awskms://alias/externalwebapp-pulumi-state?region=us-east-1"
_TEMPLATE = (
    "config:\n"
    "  aws:region: {{aws_region}}\n"
    "  relay:account: '{{aws_account_id}}'\n"
    "  relay:namespace: {{deploy_namespace}}\n"
    "  relay:kms: {{kms_key_alias}}\n"
    "  relay:repo: '{{github_repo_slug}}'\n"
)


def _relay_settings(stacks=("public-relay",), stack_state=None):
    return _init_settings(stacks=list(stacks), stack_state=stack_state)


def _write_relay_files(root: Path, *, program=True, template=True) -> Path:
    infra = root / "infra"
    infra.mkdir(parents=True, exist_ok=True)
    (infra / "Pulumi.yaml").write_text("name: webapp-infra\n")
    (infra / "__main__.py").write_text("import webapp_public_relay_stack\n")
    if program:
        (infra / "webapp_public_relay_stack.py").write_text("# relay\n")
    if template:
        (infra / "Pulumi.public-relay-stack.yaml.tmpl").write_text(_TEMPLATE)
    return root


def test_convention_names_program_and_template():
    assert stack_type_files("public-relay") == (
        "webapp_public_relay_stack.py",
        "Pulumi.public-relay-stack.yaml.tmpl",
    )
    for kind, files in STACK_TYPE_SPECS.items():
        assert stack_type_files(kind) == files


def test_gather_accepts_project_kind_beside_builtins(tmp_path):
    settings = _relay_settings(stacks=("registry", "public-relay"))
    assert gather_pulumi_stacks("externalwebapp", tmp_path, settings) == [
        "registry",
        "public-relay",
    ]


@pytest.mark.parametrize(
    "kind", ["Relay", "public_relay", "-relay", "relay-", "2relay", "environment"]
)
def test_gather_refuses_invalid_slug(tmp_path, kind):
    settings = _relay_settings(stacks=(kind,))
    with pytest.raises(ValueError, match="Invalid Pulumi stack type") as exc:
        gather_pulumi_stacks("externalwebapp", tmp_path, settings)
    assert "fix the pulumi-state stacks setting" in str(exc.value)


def test_full_render_passes_only_the_four_keys(tmp_path):
    root = _write_relay_files(tmp_path / "repo")
    out = tmp_path / "out"
    values = {
        "aws_account_id": "657517041453",
        "aws_region": "us-east-1",
        "deploy_namespace": "externalwebapp",
        "kms_key_alias": "alias/externalwebapp-pulumi-state",
        "github_repo_slug": "beebauman/externalwebapp",
    }
    render_pulumi_artifacts(
        "externalwebapp", values, root, out, True, _relay_settings()
    )
    infra = out / "infra"
    rendered = (infra / "Pulumi.externalwebapp-public-relay.yaml").read_text()
    assert "aws:region: us-east-1" in rendered
    assert "relay:account: '657517041453'" in rendered
    assert "relay:namespace: externalwebapp" in rendered
    assert "relay:kms: alias/externalwebapp-pulumi-state" in rendered
    assert "relay:repo: '{{github_repo_slug}}'" in rendered
    assert (infra / "webapp_public_relay_stack.py").read_text() == "# relay\n"


@pytest.mark.parametrize(
    ("program", "template", "missing"),
    [
        (True, False, "Pulumi.public-relay-stack.yaml.tmpl"),
        (False, True, "webapp_public_relay_stack.py"),
    ],
)
def test_full_render_refuses_missing_files(tmp_path, program, template, missing):
    root = _write_relay_files(tmp_path / "repo", program=program, template=template)
    with pytest.raises(ProjectStackFilesMissing, match=missing) as exc:
        render_pulumi_artifacts(
            "externalwebapp", {}, root, tmp_path / "out", True, _relay_settings()
        )
    assert "remove 'public-relay' from the pulumi-state stacks" in str(exc.value)


def _scoped_payload(monkeypatch):
    settings = _relay_settings(
        stack_state={
            "externalwebapp-public-relay": {
                "secrets_provider": _PROVIDER,
                "encrypted_key": "encrypted-relay",
            }
        }
    )
    monkeypatch.setattr(
        config_module,
        "resolve_project",
        lambda conn, project, required=False: SimpleNamespace(
            id=7, slug="externalwebapp"
        ),
    )
    monkeypatch.setattr(
        config_module, "_load_project_renderer_settings", lambda conn, p: settings
    )
    return build_pulumi_stack_config(
        object(), "externalwebapp", "externalwebapp-public-relay"
    )


def test_scoped_config_and_render_use_only_the_four_keys(tmp_path, monkeypatch):
    payload = _scoped_payload(monkeypatch)
    assert payload["stack_kind"] == "public-relay"
    assert set(payload["render_values"]) == PROJECT_STACK_RENDER_KEYS
    assert payload["render_values"]["deploy_namespace"] == "externalwebapp"
    assert payload["authority"]["github_repo"] == ""

    root = _write_relay_files(tmp_path / "repo")
    stack_path = render_scoped_pulumi_config(
        payload, project_root=root, output_dir=tmp_path / "out"
    )
    assert stack_path.name == "Pulumi.externalwebapp-public-relay.yaml"
    assert "relay:namespace: externalwebapp" in stack_path.read_text()
    assert (stack_path.parent / "webapp_public_relay_stack.py").is_file()


def test_scoped_render_refuses_missing_template(tmp_path, monkeypatch):
    payload = _scoped_payload(monkeypatch)
    root = _write_relay_files(tmp_path / "repo", template=False)
    with pytest.raises(ProjectStackFilesMissing, match="yaml.tmpl"):
        render_scoped_pulumi_config(
            payload, project_root=root, output_dir=tmp_path / "out"
        )


def _init(project_root: Path, calls: list) -> int:
    def child_factory(command, **kwargs):
        stack_path = Path(kwargs["cwd"]) / "Pulumi.externalwebapp-public-relay.yaml"
        calls.append(stack_path.read_text())
        stack_path.write_text(
            f"secretsprovider: {_PROVIDER}\nencryptedkey: generated\n"
            + stack_path.read_text()
        )
        return _Child(b"initialized\n")

    return execute_pulumi_command(
        "externalwebapp",
        "externalwebapp-public-relay",
        ["init", "--secrets-provider", _PROVIDER],
        config_loader=lambda project, stack: pytest.fail("fetched config"),
        project_root=project_root,
        settings_loader=lambda project: _relay_settings(),
        state_importer=lambda **kwargs: {"receipt_digest": "digest"},
        aws_env_loader=lambda *args, **kwargs: {
            "AWS_ACCESS_KEY_ID": "access-key",
            "AWS_SECRET_ACCESS_KEY": "secret-key",
        },
        child_factory=child_factory,
        out=StringIO(),
        err=StringIO(),
    )


def test_init_accepts_project_kind(tmp_path):
    calls: list = []
    root = _write_relay_files(_install_pulumi_project_files(tmp_path))
    assert _init(root, calls) == 0
    assert "relay:namespace: externalwebapp" in calls[0]


def test_init_refuses_project_kind_without_template(tmp_path):
    calls: list = []
    root = _write_relay_files(_install_pulumi_project_files(tmp_path), template=False)
    with pytest.raises(PulumiExecError, match="is missing"):
        _init(root, calls)
    assert calls == []
