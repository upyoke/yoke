"""Shared Pulumi execution test settings."""

import json
from io import BytesIO
from pathlib import Path
import shutil

from yoke_core.domain.project_renderer_settings import ProjectRendererSettings


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


def _stack_payload(project: str = "yoke", stack: str = "yoke-infra") -> dict:
    return {
        "config_schema": 2,
        "project_id": 1,
        "project_slug": project,
        "stack_name": stack,
        "stack_kind": "infra",
        "render_values": {
            "project_name": project,
            "pulumi_infra_stack_name": stack,
        },
        "operator_state": {
            "secrets_provider": "awskms://alias/yoke-pulumi",
            "encrypted_key": "encrypted-material",
        },
        "authority": {
            "aws_capability": "aws-admin",
            "aws_region": "us-east-1",
            "backend_url": "s3://yoke-state?region=us-east-1",
            "github_repo": "",
            "github_api_url": "",
            "github_permissions": {"metadata": "read"},
            "sensitive_paths": [
                "operator_state.secrets_provider",
                "operator_state.encrypted_key",
            ],
        },
    }


def _install_pulumi_project_files(tmp_path: Path) -> Path:
    """Materialize the project-owned infra files installed by Pulumi Packs."""

    source_root = Path(__file__).resolve().parents[3]
    project_root = tmp_path / "installed-project"
    project_root.mkdir(parents=True, exist_ok=True)
    for descriptor_path in sorted((source_root / "packs").glob("*/pack.json")):
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        version = descriptor["latest_version"]
        record = descriptor["versions"][version]
        version_root = descriptor_path.parent / record["source"]
        for file_record in record["files"]:
            target_name = file_record["target"]
            if not target_name.startswith("infra/"):
                continue
            if "{{" in target_name:
                raise AssertionError(f"unexpected dynamic infra target: {target_name}")
            target = project_root / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(version_root / file_record["source"], target)
            target.chmod(int(file_record["mode"], 8))
    return project_root


def _init_settings(
    *,
    stacks: list[str] | None = None,
    stack_state: dict | None = None,
) -> ProjectRendererSettings:
    state = {
        "stacks": stacks if stacks is not None else ["registry"],
        "state_bucket": "externalwebapp-pulumi-state",
        "kms_key_alias": "alias/externalwebapp-pulumi-state",
    }
    if stack_state is not None:
        state["stack_state"] = stack_state
    return ProjectRendererSettings(
        project="externalwebapp",
        deploy_namespace="externalwebapp",
        display_name="ExternalWebapp",
        site_id="",
        site_settings={},
        primary_environment=None,
        environments=(),
        capabilities={
            "aws-admin": {
                "account_id": "657517041453",
                "region": "us-east-1",
            },
            "github": {
                "repo_owner": "beebauman",
                "repo_name": "externalwebapp",
            },
            "pulumi-state": state,
        },
    )
