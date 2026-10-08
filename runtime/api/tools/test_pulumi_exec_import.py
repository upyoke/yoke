"""Allowlisted Pulumi file-import regressions."""

from io import StringIO
import pytest
from yoke_core.tools.pulumi_exec import PulumiExecError, execute_pulumi_command
from runtime.api.tools.test_pulumi_exec_support import (
    _Child,
    _install_pulumi_project_files,
    _stack_payload,
)


def test_import_accepts_only_safe_file_form(tmp_path):
    import_file = tmp_path / "imports.json"
    import_file.write_text("{}")
    with pytest.raises(PulumiExecError, match="argument is not allowed"):
        execute_pulumi_command(
            "yoke",
            "yoke-infra",
            ["import", "aws:s3/bucket", "name"],
            config_loader=lambda project, stack: _stack_payload(project, stack),
            project_root=tmp_path,
        )
    commands = []

    def child_factory(command, **kwargs):
        commands.append(command)
        return _Child()

    execute_pulumi_command(
        "yoke",
        "yoke-infra",
        [
            "import",
            "--file",
            str(import_file),
            "--protect=false",
            "--generate-code=false",
            "--yes",
            "--non-interactive",
        ],
        config_loader=lambda project, stack: _stack_payload(project, stack),
        project_root=_install_pulumi_project_files(tmp_path),
        aws_env_loader=lambda *args, **kwargs: {},
        child_factory=child_factory,
        out=StringIO(),
        err=StringIO(),
    )
    assert commands[0][-2:] == ["--stack", "yoke-infra"]


def test_import_requires_exactly_one_file(tmp_path):
    with pytest.raises(PulumiExecError, match="exactly one"):
        execute_pulumi_command(
            "yoke",
            "yoke-infra",
            ["import", "--file", "one.json", "--file", "two.json"],
            config_loader=lambda project, stack: _stack_payload(project, stack),
            project_root=tmp_path,
        )
