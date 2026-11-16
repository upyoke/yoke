"""Line-ending folding for Yoke-managed text.

Git for Windows checks text out with CRLF (``core.autocrlf``). Installer
comparisons fold CRLF to LF first, so a converted checkout still equals the
bundle it came from and refresh, prune, uninstall and recovery never mistake a
line-ending conversion for a local edit.
"""

from __future__ import annotations


def fold_newlines(content: str) -> str:
    """Return *content* with CRLF line endings folded to LF."""
    return content.replace("\r\n", "\n")


__all__ = ["fold_newlines"]
