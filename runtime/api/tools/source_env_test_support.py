"""Build the parent environment for source isolation tests."""

import os


def source_env(**overrides: str) -> dict[str, str]:
    # Keep the runner's Git on PATH rather than falling back to the macOS xcrun shim.
    return {
        **{key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ},
        **overrides,
    }
