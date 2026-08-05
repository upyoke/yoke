"""``yoke watch <kind>`` adapters for the command-shaped watcher wrappers.

The wrappers themselves live in ``yoke_core.tools``; this module is the
sanctioned invocation surface for them. Calling them as bare modules
(``python3 -m yoke_core.tools.watch_pytest``) only resolves when the
invoking ``python3`` happens to import ``yoke_core``, which is false on
any machine whose ``yoke`` is an isolated tool install and false in every
project that installed Yoke without a Yoke checkout. The console script
always resolves an interpreter that can import the wrapper, so the
``yoke watch`` form is correct by construction.

Where the wrapper runs matters as much as whether it imports. A watcher
launches a workload — pytest, a merge engine, doctor — that should run in
the *project's* environment, not in the environment that happens to own
the ``yoke`` console script. So when the invocation directory belongs to
a uv-managed project (``pyproject.toml`` beside a ``uv.lock``) **and that
project's environment can import the wrapper**, the adapter re-execs
through ``uv run --frozen``. This is what makes the command correct
inside a linked worktree: the worktree's sources run, not the ones behind
the installed console script.

The import probe is what keeps the re-exec from recreating the very
failure this command exists to fix. A project that installed Yoke as an
isolated tool has a locked environment with no ``yoke_core`` in it;
re-execing there would fail exactly like the bare module form. When the
probe says no — or there is no uv project at all — the wrapper runs
in-process, where the console script's own interpreter is always enough.

Help output is always rendered in-process so ``yoke watch pytest --help``
is fast and reads with the command the operator actually typed.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS

AdapterFn = Callable[[List[str]], int]
# Each wrapper's ``main(argv, *, prog=None)``.
WrapperMain = Callable[..., Any]

UV_EXECUTABLE = "uv"
LOCKFILE_NAME = "uv.lock"
PROJECT_FILE_NAME = "pyproject.toml"
# Generous: the probe is the first `uv run` in a fresh worktree, so it
# pays for creating the project's virtualenv. Negligible against the
# multi-minute runs these commands wrap.
PROBE_TIMEOUT_SECONDS = 300

_HELP_FLAGS = ("-h", "--help")

# One-line `yoke --help` usage per CLI form.
TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke watch pytest": (
        "Run pytest under the shared raw+progress watcher; pass bare pytest "
        "args after `--`."
    ),
    "yoke watch doctor": (
        "Run Doctor under the shared raw+progress watcher; pass bare doctor "
        "args after `--`."
    ),
    "yoke watch merge": (
        "Run done-transition, merge-item, or merge-worktree under the shared "
        "raw+progress watcher."
    ),
    "yoke watch deploy": (
        "Run a deployment pipeline under the shared raw+progress watcher; "
        "pass the run id and `deployment-runs execute` flags after `--`."
    ),
    "yoke watch qa-case": (
        "Run the QA gate under the shared raw+progress watcher; pass bare "
        "`qa case run` flags after `--`."
    ),
    "yoke watch tail": (
        "Follow a watcher progress capture and exit on the wrapper's exit sentinel."
    ),
}


def _wants_help(args: List[str]) -> bool:
    """True when a help flag precedes the pass-through separator.

    A help flag after ``--`` belongs to the wrapped command, not to us.
    """
    for arg in args:
        if arg == "--":
            return False
        if arg in _HELP_FLAGS:
            return True
    return False


def uv_project_root(start: Path) -> Optional[Path]:
    """Return the nearest ancestor of *start* that is a uv-managed project.

    A directory qualifies when it holds both a ``pyproject.toml`` and a
    ``uv.lock`` — the pair that makes ``uv run --frozen`` deterministic.
    Returns ``None`` when no ancestor qualifies, which is the signal to
    run the wrapper in-process.
    """
    try:
        here = start.resolve()
    except OSError:
        return None
    for candidate in [here, *here.parents]:
        if (candidate / PROJECT_FILE_NAME).is_file() and (
            candidate / LOCKFILE_NAME
        ).is_file():
            return candidate
    return None


def _uv_run(trailing: List[str]) -> List[str]:
    return [UV_EXECUTABLE, "run", "--frozen", "python3", *trailing]


def project_env_imports(wrapper_module: str) -> bool:
    """True when the surrounding uv project's environment can run *wrapper*.

    A project that installed Yoke as an isolated tool has ``yoke`` on PATH
    and no ``yoke_core`` in its own locked environment, so re-execing there
    would reproduce the import failure the command exists to avoid.
    """
    try:
        completed = subprocess.run(
            _uv_run(["-c", f"import {wrapper_module}"]),
            capture_output=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def reexec_argv(wrapper_module: str, args: List[str]) -> Optional[List[str]]:
    """Return the ``uv run --frozen`` argv, or ``None`` to run in-process.

    The invocation directory is left untouched: ``uv`` discovers the same
    project from it, and the wrapped workload (pytest collection above
    all) resolves its relative paths against the directory the operator
    typed the command in.
    """
    if uv_project_root(Path.cwd()) is None:
        return None
    if shutil.which(UV_EXECUTABLE) is None:
        return None
    if not project_env_imports(wrapper_module):
        return None
    return _uv_run(["-m", wrapper_module, *args])


def _wrapper_main(wrapper_module: str) -> WrapperMain:
    """Resolve a wrapper module's ``main`` at call time.

    The engine ships beside the CLI but the transport decision owns
    whether it runs, so the CLI crosses to it dynamically — through the
    one entry-point roster, which keeps this a single classified edge.
    """
    entrypoints = importlib.import_module("yoke_core.tools.watch_entrypoints")
    return entrypoints.WRAPPER_MAINS[wrapper_module]


def _render_help(wrapper_main: WrapperMain, cli_form: str) -> int:
    """Print the wrapper's own help under the command as typed.

    ``argparse`` prints help and raises ``SystemExit`` rather than
    returning, so the exit code comes off the exception; every adapter
    contract in the CLI returns an int.
    """
    try:
        return int(wrapper_main(["--help"], prog=cli_form))
    except SystemExit as exit_request:
        return int(exit_request.code or 0)


def _run(wrapper_module: str, cli_form: str, args: List[str]) -> int:
    wrapper_main = _wrapper_main(wrapper_module)
    if _wants_help(args):
        return _render_help(wrapper_main, cli_form)
    argv = reexec_argv(wrapper_module, args)
    if argv is None:
        return int(wrapper_main(args))
    try:
        return subprocess.run(argv, check=False).returncode
    except OSError as exc:
        sys.stderr.write(
            f"{cli_form}: could not run '{' '.join(argv[:3])}' "
            f"in this project ({exc}); repair the uv environment or "
            f"invoke the wrapper module directly: "
            f"python3 -m {wrapper_module}\n"
        )
        return 1


def _adapter(wrapper_module: str, cli_form: str) -> AdapterFn:
    def run(args: List[str]) -> int:
        return _run(wrapper_module, cli_form, args)

    return run


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    tokens: _adapter(module, "yoke " + " ".join(tokens))
    for module, tokens in WATCH_CLI_TOKENS.items()
}


__all__ = [
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "reexec_argv",
    "uv_project_root",
]
