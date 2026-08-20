"""Cross-project isolation for https Doctor's locally composed checks.

Every test stands the runner in one temporary repository while asking for
another project's report, so a check that read the caller's tree would be
caught naming the wrong checkout rather than silently mislabelling it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from yoke_core.engines.doctor_https_compose import (
    checkout_root_for_project,
    merge_relayed_with_local,
    run_local_source_checks,
)
from yoke_core.engines.doctor_https_only import run_local_project_checks
from yoke_core.engines.doctor_project_checks import Discovery
from yoke_core.engines.doctor_registry_types import HealthCheck
from yoke_core.engines.doctor_report import _resolve_repo_root
from yoke_core.engines.doctor_source_root import bound_source_root

#: File each temporary repository uses to name itself, so a finding can be
#: traced back to the exact tree that produced it.
MARKER = "checkout-identity.txt"


def _make_repo(root: Path, name: str) -> Path:
    """A real git repository whose tree names itself."""
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text(name, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def _tree_identity_check() -> HealthCheck:
    """An HC that reports whichever checkout its root resolution found."""

    def fn(_conn, _args, rec) -> None:
        marker = Path(_resolve_repo_root() or ".") / MARKER
        rec.record(
            "HC-tree-identity",
            "Tree identity",
            "PASS",
            marker.read_text(encoding="utf-8") if marker.is_file() else "none",
        )

    return HealthCheck(slug="tree-identity", name="Tree identity", fn=fn)


def _caller_tree_name() -> str:
    """What ambient repository-root resolution reports right now."""
    marker = Path(_resolve_repo_root() or ".") / MARKER
    return marker.read_text(encoding="utf-8") if marker.is_file() else "none"


def _run_source_checks(selected: Path, project: str) -> list[dict]:
    hc = _tree_identity_check()
    with (
        patch(
            "yoke_core.engines.doctor_https_compose.HEALTH_CHECKS", [hc],
        ),
        patch(
            "yoke_core.engines.doctor_https_compose.checkout_root_for_project",
            return_value=selected,
        ),
        patch(
            "yoke_core.engines.doctor_https_compose.local_connection_or_none",
            return_value=None,
        ),
    ):
        return run_local_source_checks(
            project=project,
            quick=True,
            full=False,
            fix=False,
            only=None,
            slugs=["tree-identity"],
        )


def test_binding_overrides_ambient_resolution_and_restores_it(
    tmp_path: Path, monkeypatch,
) -> None:
    selected = _make_repo(tmp_path / "selected", "selected")
    monkeypatch.chdir(_make_repo(tmp_path / "caller", "caller"))

    assert _caller_tree_name() == "caller"
    with bound_source_root(selected):
        assert _caller_tree_name() == "selected"
    assert _caller_tree_name() == "caller"


def test_source_checks_read_selected_checkout_not_caller_tree(
    tmp_path: Path, monkeypatch,
) -> None:
    selected = _make_repo(tmp_path / "selected", "selected")
    monkeypatch.chdir(_make_repo(tmp_path / "caller", "caller"))

    # The ambient tree is genuinely the other repository, so a passing
    # assertion below cannot be an artefact of both roots agreeing.
    assert _caller_tree_name() == "caller"

    rows = _run_source_checks(selected, "selected-project")

    assert [row["detail"] for row in rows] == ["selected"]


def test_source_checks_bind_without_mutating_process_cwd(
    tmp_path: Path, monkeypatch,
) -> None:
    selected = _make_repo(tmp_path / "selected", "selected")
    monkeypatch.chdir(_make_repo(tmp_path / "caller", "caller"))
    before = os.getcwd()

    _run_source_checks(selected, "selected-project")

    assert os.getcwd() == before
    # The binding is scoped to the run: ambient resolution is unchanged.
    assert _caller_tree_name() == "caller"


def test_numeric_and_slug_project_targets_resolve_the_same_checkout(
    tmp_path: Path, monkeypatch,
) -> None:
    selected = _make_repo(tmp_path / "selected", "selected")
    monkeypatch.chdir(_make_repo(tmp_path / "caller", "caller"))

    with (
        patch(
            "yoke_core.engines.doctor_https_compose.checkout_for_project_id",
            return_value=selected,
        ) as by_id,
        patch(
            "yoke_core.engines.doctor_https_compose.checkout_for_project_slug",
            return_value=selected,
        ) as by_slug,
    ):
        assert checkout_root_for_project("7") == selected
        assert checkout_root_for_project("buzz") == selected

    by_id.assert_called_once_with(7)
    by_slug.assert_called_once_with("buzz")

    assert [row["detail"] for row in _run_source_checks(selected, "7")] == [
        "selected",
    ]
    assert [row["detail"] for row in _run_source_checks(selected, "buzz")] == [
        "selected",
    ]


def test_source_checks_skip_when_no_checkout_is_mapped(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.chdir(_make_repo(tmp_path / "caller", "caller"))
    hc = _tree_identity_check()

    with (
        patch("yoke_core.engines.doctor_https_compose.HEALTH_CHECKS", [hc]),
        patch(
            "yoke_core.engines.doctor_https_compose.checkout_root_for_project",
            return_value=None,
        ),
    ):
        rows = run_local_source_checks(
            project="unmapped",
            quick=True,
            full=False,
            fix=False,
            only=None,
            slugs=["tree-identity"],
        )

    # No mapped tree means nothing local to report; the relayed N/A stands.
    assert rows == []


def test_project_local_checks_read_selected_checkout(
    tmp_path: Path, monkeypatch,
) -> None:
    selected = _make_repo(tmp_path / "selected", "selected")
    monkeypatch.chdir(_make_repo(tmp_path / "caller", "caller"))
    hc = _tree_identity_check()

    with (
        patch(
            "yoke_core.engines.doctor_https_only.checkout_root_for_project",
            return_value=selected,
        ),
        patch(
            "yoke_core.engines.doctor_https_only.discover_project_checks",
            return_value=Discovery([hc], []),
        ),
        patch(
            "yoke_core.engines.doctor_https_only.local_connection_or_none",
            return_value=None,
        ),
    ):
        rows = run_local_project_checks(
            project="selected-project", slugs=["tree-identity"],
        )

    assert [row["detail"] for row in rows] == ["selected"]
    assert os.getcwd() == str(Path(tmp_path / "caller").resolve())


def test_composed_report_carries_the_selected_checkout_verdict(
    tmp_path: Path, monkeypatch,
) -> None:
    selected = _make_repo(tmp_path / "selected", "selected")
    monkeypatch.chdir(_make_repo(tmp_path / "caller", "caller"))
    relayed = [
        {
            "hc": "HC-tree-identity",
            "name": "Tree identity",
            "severity": "N/A",
            "detail": (
                "reads the selected-project source tree; this runner has "
                "no checkout for it (hosted runtime)"
            ),
        },
        {
            "hc": "HC-status-consistency",
            "name": "Status consistency",
            "severity": "PASS",
            "detail": "",
        },
    ]

    merged = merge_relayed_with_local(
        relayed, _run_source_checks(selected, "selected-project"),
    )

    by_hc = {row["hc"]: row for row in merged}
    assert by_hc["HC-tree-identity"]["severity"] == "PASS"
    assert by_hc["HC-tree-identity"]["detail"] == "selected"
    assert by_hc["HC-status-consistency"]["severity"] == "PASS"
