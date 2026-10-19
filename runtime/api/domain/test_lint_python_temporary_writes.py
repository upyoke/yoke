"""Scratch provenance suppresses cwd fallback without hiding source writes."""

import pytest

from yoke_core.domain.lint_session_cwd_target_extract import (
    analyze_payload_write_targets,
    resolve_payload_cwd,
)


def analyze(body):
    return analyze_payload_write_targets(
        {
            "tool_name": "Bash",
            "tool_input": {"command": f"python3 - <<'PY'\n{body}\nPY"},
        }
    )


@pytest.mark.parametrize(
    "body",
    [
        "import tempfile\nfrom pathlib import Path\nwith tempfile.TemporaryDirectory() as root:\n (Path(root) / 'out').write_text('x')",
        "import tempfile as t\nfrom pathlib import Path\nroot = t.mkdtemp()\n(Path(root) / 'out').write_text('x')",
        "from tempfile import mkdtemp as scratch\nfrom pathlib import Path\nroot = scratch(dir='/tmp')\n(Path(root) / 'out').write_bytes(b'x')",
        "import tempfile\nf = tempfile.NamedTemporaryFile()\nopen(f.name, 'w')",
        "from pathlib import Path\nprefix='/tmp/capture-'\nPath(prefix + filename).write_text('x')",
        "import tempfile\nfrom pathlib import Path\nwith tempfile.TemporaryDirectory() as root:\n Path(root).open('w')",
    ],
)
def test_temporary_destination_does_not_fall_back_to_cwd(body):
    result = analyze(body)
    assert result.unresolved_variable is True
    assert not result.unresolved_writes


@pytest.mark.parametrize(
    "body",
    [
        "from pathlib import Path\nPath(unknown).write_text('x')",
        "from pathlib import Path\nprefix='/tmp-lookalike/'\nPath(prefix + filename).write_text('x')",
        "import tempfile\nfrom pathlib import Path\nroot=tempfile.mkdtemp()\nroot=unknown\n(Path(root) / 'out').write_text('x')",
        "import tempfile\nfrom pathlib import Path\nroot=tempfile.mkdtemp()\n(Path(root) / '../source.py').write_text('x')",
        "import tempfile\nfrom pathlib import Path\nroot=tempfile.mkdtemp()\nPath(unknown).write_text('x')",
    ],
)
def test_unknown_or_escaping_write_keeps_cwd_fallback(body):
    result = analyze(body)
    assert result.unresolved_variable is False
    assert result.unresolved_writes


def test_scratch_does_not_hide_explicit_main_target():
    result = analyze(
        "import tempfile\nfrom pathlib import Path\nroot=tempfile.mkdtemp()\nPath('/repo/source.py').write_text('x')"
    )
    assert "/repo/source.py" in result.targets


def test_tempfile_explicit_checkout_directory_is_a_write_target():
    result = analyze("import tempfile\nroot=tempfile.mkdtemp(dir='/repo')")
    assert result.targets == ["/repo"]


@pytest.mark.parametrize("key", ["input", "tool_input", "toolInput"])
def test_workdir_uses_the_same_payload_container_as_command(key):
    assert (
        resolve_payload_cwd(
            {
                "cwd": "/repo",
                key: {"cmd": "touch x", "workdir": "/repo/.worktrees/lane"},
            }
        )
        == "/repo/.worktrees/lane"
    )


def test_dynamic_child_of_temporary_directory_is_scratch():
    result = analyze(
        "import tempfile\nfrom pathlib import Path\nroot=tempfile.mkdtemp()\n(Path(root) / filename).write_text('x')"
    )
    assert result.unresolved_variable
    assert not result.unresolved_writes


def test_positional_tempfile_checkout_directory_is_checked():
    result = analyze("import tempfile\nroot=tempfile.mkdtemp('', 'capture-', '/repo')")
    assert result.targets == ["/repo"]


def test_registered_checkout_under_temp_is_not_scratch():
    result = analyze_payload_write_targets(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 - <<'PY'\nfrom pathlib import Path\nroot=Path('/tmp/checkout/.worktrees/lane')\n(root / filename).write_text('x')\nPY"
            },
        },
        protected_roots=("/tmp/checkout",),
    )
    assert not result.unresolved_variable
    assert result.unresolved_writes == ("(root / filename).write_text(...)",)
