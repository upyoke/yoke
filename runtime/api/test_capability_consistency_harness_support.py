"""Harness-support consistency checks for the capability registry.

These checks complement ``test_capability_consistency.py`` by verifying:

1. ``/yoke conduct`` declares full-universe harness support (the
   single-harness override has been removed; the row inherits the default
   ``HARNESS_UNIVERSE`` tuple).
2. Per-harness manifest limitations are the canonical substrate-gap
   surface — each present manifest declares its own limitations under
   ``supports.disabled_entrypoints`` / ``supports.disabled_downstream_paths``;
   the registry's manifest-derived helpers consume that declaration so the
   consistency layer never re-encodes per-harness gap truth.

Carved out of ``test_capability_consistency.py`` to keep both files under
the 350-line authored-file budget (HC-file-line-limit).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain.harness_capability_registry import (
    HARNESS_UNIVERSE,
    SAFE_OPERATOR_SURFACE,
    downstream_paths_for_manifest,
    entrypoints_for_manifest,
    manifest_disabled_downstream_paths,
    manifest_disabled_entrypoints,
    shared_downstream_paths,
    shared_entrypoints,
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repo root from test module location.")


REPO = _repo_root()
HARNESS = REPO / "runtime" / "harness"


@pytest.fixture(scope="module")
def codex_manifest() -> dict:
    return json.loads((HARNESS / "codex" / "manifest.json").read_text(encoding="utf-8"))


class TestConductDualHarnessSupport:
    """`/yoke conduct` is supported on every harness in the universe.
    The single-harness override has been removed; the row inherits the
    default `HARNESS_UNIVERSE` tuple."""

    def test_conduct_row_supports_full_universe(self):
        conduct = next(
            (c for c in SAFE_OPERATOR_SURFACE if c.entrypoint == "/yoke conduct"),
            None,
        )
        assert conduct is not None, "SAFE_OPERATOR_SURFACE missing /yoke conduct row"
        assert conduct.harness_support == HARNESS_UNIVERSE, (
            "/yoke conduct must declare full-universe harness support; got "
            f"{conduct.harness_support}"
        )


class TestManifestDerivedLimitations:
    """Per-harness manifest limitations are the canonical substrate-gap
    surface. Each present manifest declares its own limitations under
    `supports.disabled_entrypoints` / `supports.disabled_downstream_paths`;
    the registry's manifest-derived helpers consume that declaration so the
    consistency layer never re-encodes per-harness gap truth."""

    def test_codex_manifest_limitations_round_trip(self, codex_manifest):
        disabled_entrypoints = manifest_disabled_entrypoints(codex_manifest)
        disabled_paths = manifest_disabled_downstream_paths(codex_manifest)

        # Codex declares no structural compat gaps today; the manifest is the
        # source of truth and the registry surfaces the same answer.
        assert disabled_entrypoints == []
        assert disabled_paths == []

        # The manifest-derived entrypoint and downstream-path lists are the
        # shared registry minus whatever the manifest disables.
        assert entrypoints_for_manifest(codex_manifest) == shared_entrypoints()
        assert downstream_paths_for_manifest(codex_manifest) == shared_downstream_paths()
