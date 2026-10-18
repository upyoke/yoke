"""Client-local adapter for claimed-lane source commands."""

from __future__ import annotations

import argparse
import importlib
from yoke_cli.commands._helpers import show_delegate_help
from typing import List


def _source_runner():
    return importlib.import_module("yoke_core.tools.source_dev_run")


def source_dev_run(args: List[str]) -> int:
    if show_delegate_help(
        args,
        "yoke dev run [--lane PATH] [--allow-real-machine-home] -- COMMAND [ARG ...]",
        "Uses a claimed source lane, its locked environment, and a disposable machine-home snapshot. --allow-real-machine-home explicitly permits real machine writes. Registered scanners and claimed-target maintenance may use the mapped main checkout when no lane exists.",
    ):
        return 0
    return _source_runner().main(args)


def _run_check(module: str, args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=f"yoke dev {module.replace('_', '-')}", add_help=False, allow_abbrev=False
    )
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--lane", dest="selected_lane", metavar="PATH")
    selector.add_argument("--workdir", dest="selected_lane", metavar="PATH")
    parsed, command_args = parser.parse_known_args(args)
    return _source_runner().run(
        ["python3", "-m", f"yoke_core.tools.{module}", *command_args],
        lane=parsed.selected_lane,
    )


def ruff_changed(args: List[str]) -> int:
    if show_delegate_help(
        args,
        "yoke dev ruff-changed --base REF [--lane PATH | --workdir PATH] [--fix-format | --format-check]",
        "Select a live claimed source lane with --lane or --workdir when several exist; checks use its locked environment.",
    ):
        return 0
    return _run_check("ruff_changed", args)


def import_check(args: List[str]) -> int:
    if show_delegate_help(
        args,
        "yoke dev import-check [--lane PATH | --workdir PATH] MODULE [MODULE ...]",
        "Select a live claimed source lane with --lane or --workdir when several exist; checks use its locked environment.",
    ):
        return 0
    return _run_check("import_check", args)


__all__ = ["import_check", "ruff_changed", "source_dev_run"]
