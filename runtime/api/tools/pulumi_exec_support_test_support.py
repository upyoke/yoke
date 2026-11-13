"""Shared Pulumi execution test settings."""

from io import BytesIO, StringIO
from pathlib import Path

from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)


STACK = "scratch-stack"
PROVIDER = "awskms://alias/externalwebapp-pulumi-state?region=us-east-1"


class _Child:
    def __init__(
        self,
        stdout: bytes = b"preview-ok\n",
        *,
        stderr: bytes = b"",
        returncode: int = 0,
    ) -> None:
        self.stdout = BytesIO(stdout)
        self.stderr = BytesIO(stderr)
        self.returncode = returncode

    def wait(self, timeout=None):
        del timeout
        return self.returncode


def _init_settings(
    project: str = "externalwebapp",
    environments: tuple[RendererEnvironmentSettings, ...] = (),
) -> ProjectRendererSettings:
    return ProjectRendererSettings(
        project=project,
        deploy_namespace=project,
        display_name="ExternalWebapp",
        site_id="",
        site_settings={},
        primary_environment=None,
        environments=environments,
        capabilities={
            "aws-admin": {
                "account_id": "657517041453",
                "region": "us-east-1",
            },
            "github": {
                "repo_owner": "beebauman",
                "repo_name": "externalwebapp",
            },
            "pulumi-state": {
                "state_bucket": "externalwebapp-pulumi-state",
                "kms_key_alias": "alias/externalwebapp-pulumi-state",
            },
        },
    )


def _file_project(
    tmp_path: Path,
    stack: str = STACK,
    stack_text: str = "config:\n  app:size: small\n",
    *,
    name: str = "scratch",
) -> Path:
    """Write a project root carrying infra/Pulumi.yaml and one stack file."""
    root = tmp_path / "project"
    infra = root / "infra"
    infra.mkdir(parents=True, exist_ok=True)
    (infra / "Pulumi.yaml").write_text(f"name: {name}\nruntime: python\n")
    (infra / f"Pulumi.{stack}.yaml").write_text(stack_text)
    return root


class _Auth:
    token = "github-token"
    repo = "beebauman/externalwebapp"


def _execute(root: Path, command, *, stack: str = STACK, **overrides) -> int:
    """Run ``execute_pulumi_command`` with offline loaders unless overridden."""
    from yoke_core.tools.pulumi_exec import execute_pulumi_command

    kwargs = {
        "project_root": root,
        "settings_loader": lambda project: _init_settings(),
        "aws_env_loader": lambda *a, **kw: {},
        "github_auth_loader": lambda *a, **kw: _Auth(),
        "child_factory": lambda *a, **kw: _Child(),
        "out": StringIO(),
        "err": StringIO(),
    }
    kwargs.update(overrides)
    project = kwargs.pop("project", "externalwebapp")
    return execute_pulumi_command(project, stack, command, **kwargs)


def _authority_payload(project: str = "platform", stack: str = "s") -> dict:
    """A file-backed payload with metadata-only authority for direct env tests."""
    return {
        "project_slug": project,
        "stack_name": stack,
        "render_values": {"deploy_namespace": project},
        "stack_secrets": ("encrypted-material",),
        "authority": {
            "aws_capability": "aws-admin",
            "aws_region": "us-east-1",
            "backend_url": "s3://state?region=us-east-1",
            "github_project": project,
            "github_repo": "",
            "github_api_url": "",
            "github_permissions": {"metadata": "read"},
        },
    }
