"""Run one registered QA command live, capturing it whole as it goes.

A registered Command case is the final verification gate, so its single
execution has to serve two readers at once: the agent watching it happen
now, and the durable QA artifact read afterwards. Collecting the output
and revealing it only at the end serves the second reader alone — which
is why agents ran the suite by hand first, watched that run, and then
paid for the identical suite a second time through the gate.

Filtering is deliberately not repeated here. A registered command is
expected to be a watcher wrapper that already classifies its own output,
so every line it emits is relayed verbatim; re-classifying would swallow
the inner wrapper's own banners and verdict lines. What this adds is what
a bare captured subprocess cannot give an agent: a capture path announced
before the command starts, live output while it runs, and whole-group
reaping when it times out or is interrupted.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, TextIO

from yoke_core.domain.source_python_environment import venv_python
from yoke_core.tools import _source_pythonpath

#: Capture-file and banner label. Names the surface an agent is reading,
#: matching the ``watch_<kind>`` banners the wrappers already emit.
CAPTURE_KIND = "qa_case"


def product_command_environment(
    env: Mapping[str, str], cwd: str | Path | None = None
) -> dict[str, str]:
    """Bind a Command case onto the checkout's .venv, else this runner.

    ``/bin/sh -c`` otherwise resolves ``python3`` from the process PATH —
    typically the system interpreter, which imports neither the project's
    test packages nor ``yoke_cli``. When the case's checkout *cwd* is
    another project with its own ``.venv``, that interpreter's folder goes
    first on PATH and ``VIRTUAL_ENV`` names it, so ``python -m pytest`` runs
    the project's own tests. Yoke's interpreter folder follows, so the product ``yoke``
    console script still resolves. Without a ``.venv``, ``python3`` and
    ``python`` are this process's ``sys.executable``. ``YOKE_PYTHON`` always
    names Yoke's interpreter for scripts that need it explicitly.

    Do not ``Path.resolve()`` the executable: a venv ``python`` is often a
    symlink onto the base interpreter, and that base has no product packages.
    """
    out = dict(env)
    folders = [str(Path(sys.executable).parent)]
    if cwd is not None and not _source_pythonpath.is_yoke_shaped_tree(Path(cwd)):
        prefix = Path(cwd) / ".venv"
        project_python = venv_python(prefix)
        if project_python.is_file():
            folders.insert(0, str(project_python.parent))
            out["VIRTUAL_ENV"] = str(prefix)
    existing = out.get("PATH", "")
    out["PATH"] = os.pathsep.join(folders + ([existing] if existing else []))
    out["YOKE_PYTHON"] = sys.executable
    return out


@dataclass(frozen=True)
class StreamedCommand:
    """One completed registered-command run and where to re-read it."""

    exit_code: int
    timed_out: bool
    output: str
    capture_path: Path
    candidate_source: dict | None = None


def stream_command(
    command: str,
    *,
    cwd: str,
    env: Mapping[str, str],
    timeout_seconds: Optional[float],
    stream: Optional[TextIO] = None,
    candidate_root: Path | None = None,
    liveness=None,
) -> StreamedCommand:
    """Run *command* through a shell, relaying its output as it arrives.

    Output goes to *stream* (stderr by default) rather than stdout so the
    callers that print a JSON result — ``yoke qa case run``, plan
    execution, deployment-run execution — keep a machine-readable stdout.

    ``timeout_seconds`` of ``None`` applies no deadline here: the command
    owns its own budget (a watched pytest run starts counting after gate
    admission, not while queueing), and its own ``124`` reports the
    expiry.
    """
    # Imported here rather than at module scope: the watcher machinery
    # reaches back into this package for its scratch paths and process
    # reaping, so binding it lazily keeps that a call-time edge.
    from yoke_core.tools._watch_runner import (
        TIMEOUT_EXIT,
        run_watcher,
    )
    from yoke_core.tools._watch_throttle import Classification, LineClass

    from yoke_core.tools._watch_capture_binding import mint_capture_paths

    relay = Classification(LineClass.URGENT)

    def relay_every_line(_line: str) -> Classification:
        """Pass the command's own stream through without re-filtering it."""
        return relay

    from yoke_core.domain.qa_case_candidate_source import candidate_source

    raw_capture, progress_capture = mint_capture_paths(
        CAPTURE_KIND, project=env.get("YOKE_PROJECT")
    )
    destination = sys.stderr if stream is None else stream
    product_env = product_command_environment(env, cwd)
    evidence = None
    with candidate_source(candidate_root, product_env) as binding:
        if binding and binding.refusal:
            exit_code = 1
            raw_capture.write_text(binding.refusal + "\n", encoding="utf-8")
            print(binding.refusal, file=destination, flush=True)
        else:
            exit_code = run_watcher(
                argv=["/bin/sh", "-c", command],
                classifier=relay_every_line,
                raw_capture=raw_capture,
                progress_capture=progress_capture,
                kind=CAPTURE_KIND,
                cwd=cwd,
                env=binding.env if binding else product_env,
                stdout_stream=destination,
                timeout_seconds=timeout_seconds,
                **({"liveness": liveness} if liveness is not None else {}),
            )
            if binding:
                binding.inspect("after")
                if binding.refusal:
                    exit_code = exit_code or 1
                    with raw_capture.open("a", encoding="utf-8") as capture:
                        capture.write("\n" + binding.refusal + "\n")
                    print(binding.refusal, file=destination, flush=True)
        if binding:
            evidence = binding.evidence
            report = binding.report()
            print(report, file=destination, flush=True)
    output = raw_capture.read_text(encoding="utf-8", errors="replace")
    # 124 is the shell's own "deadline expired" code, so a command that
    # exits 124 itself reads as a timeout — which is exactly right when
    # the command owns the budget. Either way the outcome is a failing
    # verdict with the full capture attached.
    timed_out = exit_code == TIMEOUT_EXIT
    if timed_out and timeout_seconds is not None:
        output += f"\ncommand timed out after {timeout_seconds:g} seconds\n"
    return StreamedCommand(
        exit_code=exit_code,
        timed_out=timed_out,
        output=output,
        capture_path=raw_capture,
        candidate_source=evidence,
    )


__all__ = [
    "CAPTURE_KIND",
    "StreamedCommand",
    "product_command_environment",
    "stream_command",
]
