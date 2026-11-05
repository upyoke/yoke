# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import fnmatch

import io

import json

import pathlib

import subprocess

import sys

from contextlib import redirect_stdout

import pytest

from yoke_core.domain import file_line_check as flc


def _init_git_repo(tmp: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp), "config", "user.email", "t@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(tmp), "config", "user.name", "test"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp), "config", "commit.gpgsign", "false"], check=True
    )


def _commit_file(
    tmp: pathlib.Path, relpath: str, contents: str, *, message: str = "c"
) -> None:
    path = tmp / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp), "add", relpath], check=True)
    subprocess.run(["git", "-C", str(tmp), "commit", "-q", "-m", message], check=True)


def _make_lines(n: int, *, tag: str = "x") -> str:
    return "\n".join(f"{tag}{i}" for i in range(n)) + "\n"
