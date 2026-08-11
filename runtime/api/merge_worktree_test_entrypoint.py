"""Run the merge engine with transient local GitHub App test authorization."""

from __future__ import annotations

import uuid
from pathlib import Path

from yoke_core.domain.project_github_auth import (
    bind_local_github_user_token_provider,
)
from yoke_core.engines.merge_boundary_ceremony import (
    MERGE_CEREMONY_NONCE_ENV,
)
from yoke_core.engines.merge_worktree import main

from runtime.api.source_pythonpath_test_helpers import SOURCE_PYTHONPATH


def merge_subprocess_env(
    base: dict[str, str], *, tmpdir: Path, standalone: bool,
) -> dict[str, str]:
    """Environment for one engine subprocess, resolved from this checkout.

    A standalone run drives the engine alone, which is exactly what the
    merge-boundary nonce authorizes; the nonce is spent per invocation, so each
    run mints its own. A caller asserting the refusal sets the variable itself
    — empty for no nonce at all — and that choice is preserved here.
    """
    env = {**base, "PYTHONPATH": SOURCE_PYTHONPATH}
    if standalone and MERGE_CEREMONY_NONCE_ENV not in env:
        nonce = Path(tmpdir) / f"merge-ceremony-nonce-{uuid.uuid4().hex}"
        nonce.write_text("ceremony\n", encoding="utf-8")
        env[MERGE_CEREMONY_NONCE_ENV] = str(nonce)
    return env


def run() -> int:
    with bind_local_github_user_token_provider(
        lambda: "transient-test-user-token",
        api_url="https://api.github.com",
    ):
        return main()


if __name__ == "__main__":
    raise SystemExit(run())
