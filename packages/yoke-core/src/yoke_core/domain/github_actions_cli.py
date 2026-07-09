"""Argument parser for the GitHub Actions command surface."""

from __future__ import annotations

import argparse

from yoke_core.domain.github_actions_run_monitoring import (
    CHECK_CI_DEFAULT_TIMEOUT_SEC,
)

__all__ = ["build_parser"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="github-actions",
        description="GitHub Actions integration via bearer-token REST transport",
    )
    sub = parser.add_subparsers(dest="subcmd")

    p_trigger = sub.add_parser("trigger")
    p_trigger.add_argument("repo")
    p_trigger.add_argument("workflow")
    p_trigger.add_argument("--ref", default="main")
    p_trigger.add_argument("--input", action="append", dest="inputs", default=[])

    p_poll = sub.add_parser("poll")
    p_poll.add_argument("repo")
    p_poll.add_argument("run_id")

    p_find = sub.add_parser("find-run")
    p_find.add_argument("repo")
    p_find.add_argument("workflow")
    p_find.add_argument("commit_sha")

    p_wait = sub.add_parser("wait-run")
    p_wait.add_argument("repo")
    p_wait.add_argument("run_id")
    p_wait.add_argument("--timeout", type=int, default=1800, dest="timeout_sec")

    p_ci = sub.add_parser("check-ci")
    p_ci.add_argument("repo")
    p_ci.add_argument("workflow")
    p_ci.add_argument("--branch", default="main")
    p_ci.add_argument("--wait", action="store_true")
    p_ci.add_argument(
        "--timeout", type=int, default=CHECK_CI_DEFAULT_TIMEOUT_SEC,
        dest="timeout_sec",
    )

    p_flog = sub.add_parser("failed-log")
    p_flog.add_argument("repo")
    p_flog.add_argument("run_id")
    p_flog.add_argument("--tail-lines", type=int, default=50, dest="tail_lines")

    p_jobs = sub.add_parser("jobs-count")
    p_jobs.add_argument("repo")
    p_jobs.add_argument("run_id")
    p_jobs.add_argument("--attempt", type=int, default=1)

    return parser
