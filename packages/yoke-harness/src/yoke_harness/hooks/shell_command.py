"""Predictable non-login shell commands for native harness hooks."""

from __future__ import annotations


_HOOK_PATH = (
    '"${XDG_BIN_HOME:-$HOME/.local/bin}:'
    '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"'
)


def hook_shell_command(body: str) -> str:
    """Wrap trusted hook source without reading operator startup files."""
    if "'" in body:
        raise ValueError("hook shell body cannot contain a single quote")
    return f"/bin/sh -c 'PATH={_HOOK_PATH}; export PATH; {body}'"


__all__ = ["hook_shell_command"]
