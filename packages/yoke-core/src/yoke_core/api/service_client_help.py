"""Universal ``--help`` safety net for the service_client dispatcher.

Sibling of :mod:`yoke_core.api.service_client`. Provides the
``run_with_help_fallback`` helper invoked by ``main()`` when a
sub-argument is ``-h`` / ``--help``.

The dispatcher pre-existing behaviour mapped subcommand exit ``2`` to
``0`` when ``--help`` was passed — argparse-based subcommands with
``add_help=False`` reject ``--help`` as an unknown flag, exit 2, and
that mapping converts the parse-error into a clean exit. But a
subcommand that reads ``args[0]`` as a positional id (e.g.
``cmd_apply_approval``, ``cmd_update_item``, ``cmd_execute_close``,
``cmd_execute_update``, ``cmd_validate_status``, ``cmd_validate_update``)
crashes with ``Item ID must be integer, got '--help'`` and exits ``1``
— OR raises an unhandled exception (``cmd_backlog_dedup_search`` tries
to query the DB for ``--help`` and dies on a missing file). This
helper guarantees:

* Each ``--help`` invocation exits ``0``.
* Each invocation produces NO file artifacts in cwd.
* Subcommands with their own ``--help`` handler (e.g.
  ``execute-structured-write``) keep printing their bespoke usage.
* Subcommands without ``--help`` handlers print a generic fallback
  (function docstring or "no usage available" notice) — the raw
  crash output is suppressed so operators are not greeted with a
  Traceback.

This helper is deliberately small and isolated: ``service_client.py``
imports a single name, calls it from ``main()`` when ``sub_args[0]``
is a help flag, and otherwise dispatches normally.
"""

from __future__ import annotations

import contextlib
import io
import sys
from typing import Callable


_HELP_TOKENS = ("-h", "--help")


def is_help_sub_arg(sub_args: list[str]) -> bool:
    """True iff ``sub_args[0]`` is ``-h`` or ``--help``."""
    return bool(sub_args) and sub_args[0] in _HELP_TOKENS


def run_with_help_fallback(
    cmd: str,
    sub_args: list[str],
    fn: Callable[[list[str]], int],
) -> int:
    """Run ``fn(sub_args)`` when ``sub_args[0]`` is a help flag.

    Captures stdout/stderr so a crashing subcommand does not flood the
    operator with a Traceback. When the subcommand returns 0 (it has a
    real ``--help`` handler) the captured output is passed through
    verbatim. When the subcommand misbehaves (non-zero exit, raised
    exception), the captured noise is dropped and a generic fallback
    usage block is printed to stdout. Exit code is always 0.
    """
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    rc = 1
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            rc = fn(sub_args)
    except SystemExit as exc:
        # argparse / explicit sys.exit calls
        rc = exc.code if isinstance(exc.code, int) else 1
    except Exception:
        rc = 1

    if rc == 0:
        sys.stdout.write(buf_out.getvalue())
        sys.stderr.write(buf_err.getvalue())
        return 0

    doc = (fn.__doc__ or "").strip()
    print(f"Usage: python3 -m yoke_core.api.service_client {cmd} ...")
    if doc:
        print()
        print(doc)
    else:
        print()
        print(
            "(no docstring registered; this subcommand needs a "
            "`--help` handler upgrade — file a follow-up if the "
            "missing usage blocks your work)"
        )
    return 0


__all__ = ["is_help_sub_arg", "run_with_help_fallback"]
