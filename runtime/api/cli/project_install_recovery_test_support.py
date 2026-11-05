# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

import subprocess

import pytest

from yoke_cli.project_install import install_recovery as recovery

from yoke_cli.project_install import instruction_discovery

from yoke_cli.project_install.bundle_apply import apply_bundle

from yoke_cli.project_install.files import ProjectInstallError, sha256_text

from yoke_core.domain.project_install_test_helpers import make_bundle


def _file(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )


def _commit(root, message):
    _git(root, "add", "-A")
    _git(
        root,
        "-c",
        "user.name=Installer",
        "-c",
        "user.email=installer@example.test",
        "commit",
        "-m",
        message,
    )
