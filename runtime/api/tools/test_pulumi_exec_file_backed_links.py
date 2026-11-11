"""File-backed `yoke pulumi exec` refuses a symlinked stack file and keeps other links."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil

import pytest

from yoke_core.tools.pulumi_exec import PulumiExecError, execute_pulumi_command
from runtime.api.tools.pulumi_exec_support_test_support import _init_settings
from runtime.api.tools.test_pulumi_exec_file_backed import (
    _PROJECT_TEXT,
    _PROVIDER,
    _STACK,
    _project,
    _run,
    _snapshot,
)


def _link_stack_file(tmp_path: Path, root: Path) -> Path:
    stack_path = root / "infra" / f"Pulumi.{_STACK}.yaml"
    target = tmp_path / "shared" / "Pulumi.shared.yaml"
    target.parent.mkdir()
    shutil.move(stack_path, target)
    stack_path.symlink_to(target)
    return target


def test_preview_refuses_a_symlinked_stack_file_and_leaves_its_target(tmp_path):
    root = _project(tmp_path)
    target = _link_stack_file(tmp_path, root)
    before = target.read_bytes()
    calls: list[dict] = []

    with pytest.raises(PulumiExecError) as refusal:
        _run(root, ["preview"], calls=calls)

    message = str(refusal.value)
    assert message.startswith("pulumi_stack_file_symlink:")
    assert f"Pulumi.{_STACK}.yaml" in message
    assert "Replace the link with a regular file" in message
    assert calls == []
    assert target.read_bytes() == before
    assert (root / "infra" / f"Pulumi.{_STACK}.yaml").is_symlink()


def test_init_refuses_a_symlinked_stack_file_and_leaves_its_target(tmp_path):
    root = _project(tmp_path)
    target = _link_stack_file(tmp_path, root)
    before = target.read_bytes()

    with pytest.raises(PulumiExecError, match="pulumi_stack_file_symlink"):
        execute_pulumi_command(
            "externalwebapp",
            _STACK,
            ["init", "--secrets-provider", _PROVIDER],
            project_root=root,
            settings_loader=lambda project: _init_settings(),
            aws_env_loader=lambda *a, **kw: {},
            child_factory=lambda *a, **kw: pytest.fail("refused init ran pulumi"),
            out=StringIO(),
            err=StringIO(),
        )

    assert target.read_bytes() == before


def test_regular_stack_file_with_a_linked_virtualenv_directory_runs(tmp_path):
    root = _project(tmp_path)
    venv = root / "infra" / "venv"
    shared_venv = tmp_path / "shared-venv"
    shutil.move(venv, shared_venv)
    venv.symlink_to(shared_venv, target_is_directory=True)
    before = _snapshot(root)
    shared_before = _snapshot(shared_venv)
    calls: list[dict] = []

    assert _run(root, ["preview"], calls=calls) == 0

    call = calls[0]
    assert call["venv_target"] == shared_venv.resolve()
    assert call["python_link"] is True
    assert "yoke:aws_region" in call["stack_text"]
    assert _PROJECT_TEXT.splitlines()[2] in call["stack_text"]
    assert _snapshot(root) == before
    assert _snapshot(shared_venv) == shared_before
