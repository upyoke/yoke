"""Shared fake Node toolchain for browser daemon-launch tests."""

from __future__ import annotations

from pathlib import Path

from yoke_cli import browser_node_toolchain
from yoke_cli.browser_node_toolchain import NodeToolchain


def install_fake_toolchain(monkeypatch, bin_dir: Path) -> NodeToolchain:
    """Pin daemon launches to a known toolchain instead of the host's Node.

    The launch path spawns node, npm, and npx by absolute path, so a test that
    asserts which commands it ran has to know those paths. Leaving resolution
    to the host would make the assertions depend on whichever Node the machine
    running the suite happens to carry — or on it carrying one at all.
    """
    toolchain = NodeToolchain(bin_dir=bin_dir, version="v24.20.0", source="managed")
    monkeypatch.setattr(
        browser_node_toolchain,
        "ensure_node_toolchain",
        lambda *_args, **_kwargs: toolchain,
    )
    return toolchain


__all__ = ["install_fake_toolchain"]
