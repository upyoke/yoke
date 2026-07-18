"""Executable coverage for the template-owned CloudFront invalidation helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
from types import ModuleType

import pytest


HELPER_PATH = (
    Path(__file__).resolve().parents[3]
    / "templates/webapp/ops/cloudfront_invalidate.py"
)


def _load_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "cloudfront_invalidate_template",
        HELPER_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("distribution_id", ("", "TODO"))
def test_missing_distribution_id_fails_closed(distribution_id: str) -> None:
    helper = _load_helper()

    with pytest.raises(SystemExit, match="distribution ID is not configured"):
        helper.invalidate_distribution(distribution_id)


def test_distribution_discovery_requires_an_existing_match(monkeypatch) -> None:
    helper = _load_helper()
    monkeypatch.setattr(
        helper.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="None\n",
            stderr="",
        ),
    )

    with pytest.raises(SystemExit, match="EUNKNOWN was not found"):
        helper.invalidate_distribution("EUNKNOWN")


def test_subprocess_failure_preserves_code_and_bounds_diagnostics(
    monkeypatch,
    capsys,
) -> None:
    helper = _load_helper()
    monkeypatch.setattr(
        helper.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=17,
            stdout="",
            stderr="x" * 2500,
        ),
    )

    with pytest.raises(SystemExit) as raised:
        helper.invalidate_distribution("EFAIL")

    stderr = capsys.readouterr().err
    assert raised.value.code == 17
    assert "CloudFront distribution discovery failed (exit 17)" in stderr
    assert "x" * 2000 in stderr
    assert "x" * 2001 not in stderr


def test_success_lists_distribution_then_creates_invalidation(
    monkeypatch,
    capsys,
) -> None:
    helper = _load_helper()
    commands: list[list[str]] = []
    outputs = iter(("EDIST d.example.test Deployed\n", "I123 InProgress\n"))

    def fake_run(command, **kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=next(outputs),
            stderr="",
        )

    monkeypatch.setattr(helper.subprocess, "run", fake_run)

    helper.invalidate_distribution("EDIST")

    assert commands[0][:3] == ["aws", "cloudfront", "list-distributions"]
    assert commands[1][:3] == ["aws", "cloudfront", "create-invalidation"]
    assert commands[1][commands[1].index("--distribution-id") + 1] == "EDIST"
    assert commands[1][commands[1].index("--paths") + 1] == "/*"
    output = capsys.readouterr().out
    assert "CloudFront distribution: EDIST d.example.test Deployed" in output
    assert "CloudFront invalidation: I123 InProgress" in output
