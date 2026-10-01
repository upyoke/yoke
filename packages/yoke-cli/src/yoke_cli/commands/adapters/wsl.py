"""Client-local WSL setup used by installation and its recovery command."""

from __future__ import annotations

import argparse
import sys

from yoke_cli.commands._helpers import parse_or_usage_error

WSL_SETUP_USAGE = "yoke wsl setup"


def wsl_setup(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=WSL_SETUP_USAGE,
        description=(
            "Enable systemd inside WSL using available OS authority, then print the "
            "Windows shutdown and Ubuntu restart step. No yes/no prompt."
        ),
    )
    if parse_or_usage_error(parser, args, WSL_SETUP_USAGE) is None:
        return 2
    try:
        from yoke_harness.wsl_systemd import setup
    except ImportError as exc:
        print(f"{WSL_SETUP_USAGE} requires yoke-harness: {exc}", file=sys.stderr)
        return 2
    try:
        setup()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0
