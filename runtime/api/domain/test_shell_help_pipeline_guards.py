"""A help stage is print-only even when a pipeline filters its output."""

import pytest

from yoke_core.domain.lint_yoke_adapter_output_truncation import (
    find_truncation_violation,
)
from yoke_core.domain.lint_yoke_adapter_stderr_visibility import evaluate_payload
from yoke_core.domain.lint_pipe_to_truncator import _find_pipe_to_truncator


@pytest.mark.parametrize(
    "command",
    [
        "yoke messages acknowledge --help | head -40",
        "yoke --env prod claims work acquire --help 2>&1 | tail -20",
        "yoke watch pytest --help | head -80",
        "pytest --help | tail -10",
        "python3 -m pytest -h | head -20",
        "env YOKE_X=1 yoke items create --help 2>/dev/null | head -30",
    ],
)
def test_help_pipeline_is_allowed(command):
    assert find_truncation_violation(command) is None
    assert evaluate_payload({"tool_input": {"command": command}}) is None
    assert _find_pipe_to_truncator(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "yoke messages acknowledge message | head -40",
        "yoke dev run -- python3 -c 'print(1)' --help | head -20",
        "yoke watch pytest --help; yoke items create --title example | tail -20",
    ],
)
def test_help_does_not_exempt_another_command(command):
    assert find_truncation_violation(command) is not None
