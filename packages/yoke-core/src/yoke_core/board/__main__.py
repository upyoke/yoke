"""CLI entrypoint for board preview tools.

Usage::

    # Preview mode (operator-facing standalone art preview)
    python3 -m yoke_core.board preview --config /path/to/config --rainbow
    python3 -m yoke_core.board preview --config /path/to/config --done 5 --active 2 --total 10
    python3 -m yoke_core.board preview --config /path/to/config --zen

Full board markdown is rendered through the canonical rebuild surface:
``yoke board rebuild --print`` or ``yoke board rebuild --print-only``.

The ``--seed`` flag enables deterministic art/variant selection for
testing and reproducibility.  Callers pass ``BOARD_SEED`` through this
flag without inventing new randomness semantics.

Subcommands:
    preview — owned by ``yoke_core.board.preview._preview_main``.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from yoke_core.board.preview import _preview_main


_RENDER_RETIRED = (
    "Full board rendering moved to `yoke board rebuild --print` "
    "or `yoke board rebuild --print-only`. "
    "`python3 -m yoke_core.board` only supports the `preview` subcommand."
)


def _emit_help() -> int:
    print(
        "Usage: python3 -m yoke_core.board preview [options]\n\n"
        "Full board markdown: yoke board rebuild --print\n"
        "No-write full board markdown: yoke board rebuild --print-only"
    )
    return 0


def main(argv: "Optional[List[str]]" = None) -> int:
    """Parse CLI arguments and dispatch to render or preview.

    Supports the ``preview`` subcommand only. Full board rendering is
    available through ``yoke board rebuild``.
    """
    if argv is None:
        argv = sys.argv[1:]

    rest_argv = list(argv)
    if not rest_argv:
        print(_RENDER_RETIRED, file=sys.stderr)
        return 2
    if rest_argv[0] in ("-h", "--help"):
        return _emit_help()
    if rest_argv[0] == "render" or rest_argv[0].startswith("-"):
        print(_RENDER_RETIRED, file=sys.stderr)
        return 2

    if rest_argv[0] == "preview":
        rest_argv = rest_argv[1:]
        parser = argparse.ArgumentParser(
            prog="python3 -m yoke_core.board preview",
            description="Preview board art and timeline widgets.",
        )
        parser.add_argument(
            "--config",
            default=None,
            help="Optional JSON/key=value settings path for tests/operator-debug",
        )
        parser.add_argument(
            "--db",
            default=None,
            help="Legacy connection token accepted by --zen",
        )
        parser.add_argument("--seed", type=int, default=None, help="Deterministic seed")
        parser.add_argument(
            "--repo-root",
            default=None,
            help="Repository root for project-local board config/art.",
        )

        # Mode flags
        parser.add_argument("--rainbow", dest="mode", action="store_const", const="rainbow")
        parser.add_argument("--rainbow-mode", dest="rainbow_mode", type=int, default=None)
        parser.add_argument("--rainbow-all", dest="mode", action="store_const", const="rainbow-all")
        parser.add_argument("--done", dest="done_count", type=int, default=None)
        parser.add_argument("--active", dest="active_count", type=int, default=None)
        parser.add_argument("--total", dest="total_count", type=int, default=None)
        parser.add_argument("--percent", dest="percent_val", type=int, default=None)
        parser.add_argument("--variant", dest="variant_arg", default=None)
        parser.add_argument("--ascii", dest="ascii_num", type=int, default=None)
        parser.add_argument("--mixed", dest="mixed_num", type=int, default=None)
        parser.add_argument("--all", dest="mode", action="store_const", const="all")
        parser.add_argument("--zen", dest="mode", action="store_const", const="zen")

        # Options
        parser.add_argument("--stats", default=None, help="Stats: A,P,B,D,F")
        parser.add_argument("--no-stats", dest="no_stats", action="store_true")
        parser.add_argument("--dashboard", action="store_true")
        parser.add_argument("--velocity-meter", action="store_true")
        parser.add_argument("--celebrate", action="store_true")

        args = parser.parse_args(rest_argv)

        # Determine mode from args
        if args.mode is None:
            if args.rainbow_mode is not None:
                args.mode = "rainbow-mode"
            elif args.done_count is not None:
                args.mode = "progress"
            elif args.percent_val is not None:
                args.mode = "percent"
            elif args.variant_arg is not None:
                try:
                    args.variant_num = int(args.variant_arg)
                    args.variant_name = None
                    args.mode = "variant"
                except ValueError:
                    args.variant_num = None
                    args.variant_name = args.variant_arg
                    args.mode = "named-variant"
            elif args.ascii_num is not None:
                args.mode = "ascii"
            elif args.mixed_num is not None:
                args.mode = "mixed"
            else:
                args.mode = "rainbow"
        else:
            args.variant_num = None
            args.variant_name = None
            if hasattr(args, "variant_arg") and args.variant_arg:
                try:
                    args.variant_num = int(args.variant_arg)
                except ValueError:
                    args.variant_name = args.variant_arg
                    args.mode = "named-variant"

        # Ensure stat attrs exist
        args.stat_active = 0
        args.stat_pipeline = 0
        args.stat_backlog = 0
        args.stat_done = 0
        args.stat_frozen = 0
        args.stat_blocked = 0

        return _preview_main(args)

    print(_RENDER_RETIRED, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
