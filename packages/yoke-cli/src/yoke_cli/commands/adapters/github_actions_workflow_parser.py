"""Shared argument builders for the GitHub Actions workflow commands."""

from __future__ import annotations

import argparse

from yoke_cli.commands._helpers import add_json_arg, add_session_arg

PROJECT_HELP = "Project capability owning the GitHub App repo binding."
INPUT_HELP = "Workflow input as KEY=VALUE; repeat for each input."


def add_workflow_args(parser: argparse.ArgumentParser, *, dispatch: bool) -> None:
    add = parser.add_argument
    add("repo", help="GitHub repo slug, e.g. upyoke/platform.")
    add("workflow", help="Workflow file name in .github/workflows.")
    if dispatch:
        add(
            "--ref",
            default="main",
            help="Git ref to run the workflow on; default: main.",
        )
        add("--input", action="append", dest="inputs", default=[], help=INPUT_HELP)


def add_common_args(parser: argparse.ArgumentParser, *, run_id: bool = False) -> None:
    parser.add_argument("repo", help="GitHub repo slug, e.g. upyoke/platform.")
    if run_id:
        parser.add_argument("run_id", help="GitHub Actions workflow run id.")
    parser.add_argument("--project", required=True, help=PROJECT_HELP)
    add_session_arg(parser)
    add_json_arg(parser)
