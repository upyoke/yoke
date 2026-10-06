"""Harness capability resolution through canonical manifests and shared registry."""

from __future__ import annotations

import json
import os

from runtime.api.sessions_api_stale_test_helpers import (
    conn as conn,  # backend-aware fixture re-export
    ownership_conn as ownership_conn,  # backend-aware fixture re-export
)
from yoke_core.domain.harness_capability_registry import shared_downstream_paths
from yoke_core.domain.sessions_queries import resolve_harness_capabilities


class TestHarnessCapabilities:
    """Surface identity resolves the same family capability manifest."""

    def test_claude_aliases_use_claude_manifest_directory(self, tmp_path):
        """Claude executor aliases resolve the canonical Claude manifest path."""
        ws = str(tmp_path)
        manifest_dir = os.path.join(ws, "runtime", "harness", "claude")
        os.makedirs(manifest_dir, exist_ok=True)
        with open(
            os.path.join(manifest_dir, "manifest.json"),
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump({"supports": {"command_source": "shared_yoke_registry"}}, handle)

        for executor in ("claude-code", "claude-vscode"):
            result = resolve_harness_capabilities(executor, ws)

            assert result["manifest_executor"] == "claude-code"
            assert result["manifest_directory"] == "claude"
            assert result["source"] == "shared_registry"
            # A manifest declaring no limitations inherits the registry set
            # verbatim, so compare against the registry rather than a literal
            # that goes stale the moment a routable path is added.
            assert result["downstream_paths"] == shared_downstream_paths()

    def test_surface_specific_executor_uses_shared_registry(self, ownership_conn):
        """surface executors inherit shared registry truth through coarse manifest."""
        _conn, ws = ownership_conn
        manifest_dir = os.path.join(ws, "runtime", "harness", "codex")
        os.makedirs(manifest_dir, exist_ok=True)
        with open(
            os.path.join(manifest_dir, "manifest.json"), "w", encoding="utf-8"
        ) as handle:
            json.dump({"supports": {"command_source": "shared_yoke_registry"}}, handle)

        result = resolve_harness_capabilities("codex-desktop", ws)

        assert result["manifest_executor"] == "codex"
        assert result["manifest_directory"] == "codex"
        assert result["source"] == "shared_registry"
        assert result["downstream_paths"] == shared_downstream_paths()
