"""Streaming-pair emission contract (350-cap sibling of test_watch_runner).

Pins ``print_streaming_pair``'s output shape: the background invocation,
the auto-exiting ``watch_tail`` progress leg, the post-completion raw
inspection line, the ``cd <repo-root>`` prefix that binds both pasteable
command lines to the emitting checkout, and mint fidelity for the
invoking connection env.
"""

from __future__ import annotations

import io
import shlex
from pathlib import Path

import pytest

from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_contracts.uv_project import uv_project_root
from yoke_core.tools import _watch_runner


@pytest.fixture(autouse=True)
def _isolate_connection_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_OVERRIDE, raising=False)


def _pair_text(
    wrapper_args: list[str],
    wrapper_module: str = "yoke_core.tools.watch_pytest",
) -> str:
    out = io.StringIO()
    _watch_runner.print_streaming_pair(
        kind="pytest",
        wrapper_module=wrapper_module,
        wrapper_args=wrapper_args,
        raw_capture=Path("/tmp/raw.log"),
        progress_capture=Path("/tmp/prog.log"),
        out=out,
    )
    return out.getvalue()


def _command_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("cd ")]


def test_warns_that_the_two_printed_commands_are_a_bound_pair():
    """The pair binds only when the bg command is pasted verbatim.

    Arming the tail on the printed progress capture while running the
    wrapper without the printed capture flags mints a second pair, so
    the run's sentinel lands where nobody reads it.
    """
    text = _pair_text(["runtime/api/"])
    assert "VERBATIM" in text
    assert "matched pair" in text
    assert "--raw-capture/--progress-capture" in text
    # The warning must say what happens when they are dropped, not just
    # that they matter.
    assert "mints a fresh capture pair" in text


def test_emits_background_and_progress_tail_invocations():
    text = _pair_text(["runtime/api/", "-k", "fast"])
    assert "yoke watch pytest" in text
    assert "--raw-capture /tmp/raw.log" in text
    assert "--progress-capture /tmp/prog.log" in text
    assert "ready-to-paste streaming pair" in text
    # Progress tail command points at the progress capture, not raw,
    # and uses the auto-exiting watch_tail follower so a Monitor
    # running this leaves no child tail process behind.
    assert "yoke watch tail /tmp/prog.log" in text
    # Bare `tail -f` against the progress capture must NOT appear --
    # that was the orphan-Monitor source the watch_tail follower replaced.
    assert "tail -f /tmp/prog.log" not in text
    # Post-completion inspection still points at the raw capture.
    assert "tail -80 /tmp/raw.log" in text


def test_pasteable_lines_use_the_console_script_not_a_bare_interpreter():
    """Both legs must resolve from any directory.

    ``python3 -m yoke_core.tools.watch_pytest`` only works when the
    ambient ``python3`` happens to import ``yoke_core``; the console
    script always resolves an interpreter that can, and re-execs the
    project's own environment when there is one.
    """
    text = _pair_text(["runtime/api/"])
    assert "python3 -m yoke_core.tools" not in text
    # The locked-environment binding is the adapter's job now, so the
    # pasted line no longer carries a uv prefix of its own.
    assert "uv run --frozen" not in text


def test_wrapper_without_an_adapter_keeps_the_locked_module_form():
    """``watch_advance`` and friends have no ``yoke`` token yet.

    They still print pairs, so they keep the ``uv run --frozen`` module
    invocation that binds a checkout's locked environment.
    """
    text = _pair_text(["--item", "PREFIX-1"], "yoke_core.tools.watch_advance")
    assert "uv run --frozen python3 -m yoke_core.tools.watch_advance" in text
    # The progress leg has an adapter regardless of the wrapper's own form.
    assert "yoke watch tail /tmp/prog.log" in text


def test_command_lines_are_repo_root_anchored():
    """Both pasteable lines carry ``cd <repo-root>``.

    Pasted commands do not reliably inherit the minting cwd, and a
    subdirectory cwd resolves a nested or mixed environment.
    """
    text = _pair_text(["runtime/api/"])
    root = uv_project_root(Path.cwd()) or Path.cwd().resolve()
    anchor = f"cd {shlex.quote(str(root))} && "
    command_lines = _command_lines(text)
    assert len(command_lines) == 2
    assert all(line.startswith(anchor) for line in command_lines)
    # The source-only PYTHONPATH binding stayed retired — it left dev
    # dependencies to whatever python3 resolved.
    assert "PYTHONPATH" not in text


def test_subdirectory_cwd_still_anchors_at_repo_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = uv_project_root(Path.cwd())
    assert root is not None
    nested = root / "packages"
    assert nested.is_dir()
    monkeypatch.chdir(nested)
    text = _pair_text(["runtime/api/"])
    anchor = f"cd {shlex.quote(str(root))} && "
    command_lines = _command_lines(text)
    assert len(command_lines) == 2
    assert all(line.startswith(anchor) for line in command_lines)
    assert str(nested) not in "".join(command_lines)


def test_cli_form_carries_invoking_connection_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_OVERRIDE, "prod-db-admin")
    text = _pair_text(["RUN-ID"], "yoke_core.tools.watch_deploy")
    command_lines = _command_lines(text)
    assert len(command_lines) == 2
    assert all("yoke --env prod-db-admin watch " in line for line in command_lines)
    assert "yoke --env prod-db-admin watch deploy" in command_lines[0]
    assert "yoke --env prod-db-admin watch tail" in command_lines[1]
    assert "yoke watch deploy" not in command_lines[0]
    assert "yoke watch tail" not in command_lines[1]


def test_module_form_carries_invoking_connection_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_OVERRIDE, "prod-db-admin")
    text = _pair_text(["--item", "PREFIX-1"], "yoke_core.tools.watch_advance")
    command_lines = _command_lines(text)
    assert command_lines[0].startswith("cd ")
    assert (
        f"{ENV_OVERRIDE}=prod-db-admin uv run --frozen python3 -m "
        "yoke_core.tools.watch_advance"
    ) in command_lines[0]
    assert "yoke --env prod-db-admin watch tail" in command_lines[1]


def test_omits_connection_env_when_unset():
    text = _pair_text(["runtime/api/"])
    assert "--env " not in text
    assert f"{ENV_OVERRIDE}=" not in text
    assert "yoke watch pytest" in text
