"""HC-install-bundle-drift: packaged install-bundle tree matches its source.

The committed ``yoke_core.install_bundle_tree`` snapshot ships in the wheel as
package-data so the server can serve ``GET /v1/projects/{id}/install-bundle`` in
product-wheel mode. It is a byte-exact copy of the repo-root source dirs
(:data:`yoke_core.domain.install_bundle.INSTALL_BUNDLE_SOURCE_DIRS`) — the Yoke
skill tree, the rendered agent adapters, and the Claude session rules. Because
the snapshot has no build-time regenerator, an adapter/skill/rules edit that
skips the resync silently drifts the shipped wheel from source. This check FAILs
on any divergence so the gap is caught by ``/yoke doctor`` and CI before merge,
rather than only by the ``test_install_bundle`` pytest.

PASS — snapshot byte-matches source (or this checkout ships no snapshot tree).
FAIL — at least one file is missing / stale / changed; the detail names each
path and the ``sync`` repair command.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)


_HC_NAME = "HC-install-bundle-drift"
_HC_DESC = "Packaged install-bundle tree matches its source dirs"
_REPAIR = "python3 -m yoke_core.domain.install_bundle_tree_sync sync"


def hc_install_bundle_drift(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    try:
        from yoke_core.domain import install_bundle_tree_sync
    except ImportError as exc:  # pragma: no cover - defensive
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            f"install_bundle_tree_sync module unavailable ({exc}); "
            "snapshot drift surface not provisioned yet",
        )
        return

    repo_root = _resolve_repo_root()
    if not repo_root:
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "repo root not resolvable (git rev-parse failed); "
            "install-bundle snapshot drift check skipped",
        )
        return

    root = Path(repo_root)
    if not (root / install_bundle_tree_sync.PACKAGED_TREE_REL).is_dir():
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "no packaged install-bundle tree in this checkout; "
            "snapshot drift check not applicable",
        )
        return

    try:
        drift = install_bundle_tree_sync.detect_drift(target_root=root)
    except Exception as exc:
        rec.record(
            _HC_NAME, _HC_DESC, "FAIL",
            f"install-bundle snapshot drift check raised: {exc}",
        )
        return

    if not drift:
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "packaged install-bundle tree byte-matches its source dirs",
        )
        return

    detail_lines = ["packaged install-bundle tree drifts from source:"]
    detail_lines.extend(f"- {entry}" for entry in drift)
    detail_lines.append(f"Run `{_REPAIR}` to repair.")
    rec.record(_HC_NAME, _HC_DESC, "FAIL", "\n".join(detail_lines))
