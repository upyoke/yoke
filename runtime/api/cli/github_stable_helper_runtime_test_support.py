# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import os

from pathlib import Path

import subprocess

import pytest

from runtime.api.cli.github_stable_helper_test_support import (
    run_git as _git,
    write_github_app_config as _github_app_config,
)

from yoke_cli.config import github_git_credentials

from yoke_cli.config import github_git_credential_bundle

from yoke_cli.config import github_git_credential_launcher

from yoke_contracts import github_app_tokens


def _write_refresh_sitecustomize(
    root: Path,
    token: str,
    *,
    call_marker: Path | None = None,
) -> None:
    """Make a helper subprocess receive one deterministic OAuth response."""

    root.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {
            "access_token": token,
            "expires_in": 28_800,
            "refresh_token": "rotated-refresh-secret",
            "refresh_token_expires_in": 15_552_000,
            "scope": "",
            "token_type": "bearer",
        }
    ).encode("utf-8")
    (root / "sitecustomize.py").write_text(
        "import builtins\n"
        "import urllib.request\n"
        f"_BODY = {body!r}\n"
        "class _Response:\n"
        "    def __init__(self, url): self.url = url\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *args): return False\n"
        "    def read(self, size=-1): return _BODY[:size] if size >= 0 else _BODY\n"
        "    def geturl(self): return self.url\n"
        "class _Opener:\n"
        "    def open(self, request, timeout=None):\n"
        + (
            f"        builtins.open({str(call_marker)!r}, 'w').write('called')\n"
            if call_marker is not None
            else ""
        )
        + "        return _Response(request.full_url)\n"
        "urllib.request.build_opener = lambda *args, **kwargs: _Opener()\n",
        encoding="utf-8",
    )
