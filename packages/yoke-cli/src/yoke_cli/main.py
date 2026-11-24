"""``yoke`` — the unified agent-facing operations CLI entrypoint.

Every harness tool call runs ``yoke hook evaluate <event>`` at least twice, so
that one command is answered before anything else loads: it only hands the
payload to the machine-local hook resident over its Unix socket, and the
command catalog would cost it hundreds of milliseconds per call. Every other
invocation routes through :mod:`yoke_cli.command_router`.
"""

from __future__ import annotations

import sys
from typing import List, Optional

from yoke_cli.cli_output import quiet_closed_stdout


_HOOK_EVALUATE_COMMAND = ["hook", "evaluate"]


@quiet_closed_stdout
def main(argv: Optional[List[str]] = None) -> int:
    """Run the ``yoke`` CLI for one invocation. Returns the exit code."""
    if sys.platform == "win32" and sys.version_info < (3, 12):
        from yoke_contracts.api_urls import DISTRIBUTION_PROD_URL

        print(
            "windows_python_floor: native Windows requires Python 3.12+ for "
            "non-blocking process pipes. Reinstall with "
            f"irm {DISTRIBUTION_PROD_URL}/install.ps1 | iex; uv supplies Python 3.12.",
            file=sys.stderr,
        )
        return 1
    from yoke_cli.config.native_windows_terminal import configure
    from yoke_contracts.standard_streams import InvalidStdinEncoding, use_utf8_stdin

    configure()  # UTF-8 output on Windows, hooks included.
    use_utf8_stdin()
    try:
        return _run_command(list(sys.argv[1:] if argv is None else argv))
    except InvalidStdinEncoding as exc:
        from yoke_contracts.refusal_recovery import compose_refusal

        # An undecodable hook payload cannot be evaluated or forwarded.
        print(
            compose_refusal(str(exc), recovery="Encode the input as UTF-8 and retry"),
            file=sys.stderr,
        )
        return 1


def _run_command(argv: List[str]) -> int:
    if argv[:2] == _HOOK_EVALUATE_COMMAND:
        from yoke_cli import sandbox_denial
        from yoke_cli.commands.adapters.hooks import hook_evaluate

        try:
            return sandbox_denial.run(hook_evaluate, argv[2:], argv)
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 1
        except KeyboardInterrupt:
            print("yoke: interrupted by Ctrl-C.", file=sys.stderr)
            return 130
    from yoke_contracts.refusal_recovery import compose_refusal
    from yoke_contracts.working_directory import (
        MISSING_REASON,
        MISSING_RECOVERY,
        WorkingDirectoryMissing,
        current_directory,
    )

    try:
        current_directory()
    except WorkingDirectoryMissing:
        print(compose_refusal(MISSING_REASON, recovery=MISSING_RECOVERY), file=sys.stderr)
        return 1

    from yoke_cli.command_router import route_command

    return route_command(argv)


if __name__ == "__main__":
    sys.exit(main())
