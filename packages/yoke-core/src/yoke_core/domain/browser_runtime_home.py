"""Compatibility view of the harness-owned Browser QA runtime materializer.

The packaged sources, source hash, and copy implementation have one owner:
``yoke_harness.browser_runtime_home``. Core keeps this import path for existing
callers while delegating every public operation to that owner.
"""

from yoke_harness.browser_runtime_home import (
    HASH_MARKER_NAME,
    RUNTIME_DIR_NAME,
    ensure_materialized,
    package_source_root,
    runtime_dir,
    source_hash,
)


# Retain the historical core spelling without retaining a second resolver.
package_source_dir = package_source_root


__all__ = [
    "HASH_MARKER_NAME",
    "RUNTIME_DIR_NAME",
    "ensure_materialized",
    "package_source_dir",
    "package_source_root",
    "runtime_dir",
    "source_hash",
]
