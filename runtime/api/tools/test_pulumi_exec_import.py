"""Allowlisted Pulumi file-import regressions."""

import pytest
from yoke_core.tools.pulumi_exec import PulumiExecError
from runtime.api.tools.pulumi_exec_support_test_support import (
    STACK,
    _Child,
    _execute,
    _file_project,
)


def test_import_accepts_only_safe_file_form(tmp_path):
    root = _file_project(tmp_path)
    import_file = tmp_path / "imports.json"
    import_file.write_text("{}")
    with pytest.raises(PulumiExecError, match="argument is not allowed"):
        _execute(root, ["import", "aws:s3/bucket", "name"])
    commands = []

    def child_factory(command, **kwargs):
        commands.append(command)
        return _Child()

    _execute(
        root,
        [
            "import",
            "--file",
            str(import_file),
            "--protect=false",
            "--generate-code=false",
            "--yes",
            "--non-interactive",
        ],
        child_factory=child_factory,
    )
    assert commands[0][2:4] == ["--file", str(import_file)]
    assert commands[0][-2:] == ["--stack", STACK]


def test_import_requires_exactly_one_file(tmp_path):
    with pytest.raises(PulumiExecError, match="exactly one"):
        _execute(
            _file_project(tmp_path),
            ["import", "--file", "one.json", "--file", "two.json"],
        )
