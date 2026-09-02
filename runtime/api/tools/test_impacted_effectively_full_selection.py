"""Bounded reachability retains changes beside an effectively-full trigger."""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import impacted_tests
from yoke_core.tools.impacted_tests import build_import_index, select

from runtime.api.tools.test_impacted_tests import _tiny_repo, _with_floor, _write


def test_bounded_selection_keeps_individually_reachable_change(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    broad_source = "runtime/api/foundation.py"
    _write(root, broad_source, "VALUE = 1\n")
    for number in range(impacted_tests.MIN_EFFECTIVELY_FULL_FILE_UNIVERSE):
        _write(
            root,
            f"runtime/api/test_foundation_{number}.py",
            "from runtime.api import foundation\n",
        )

    selection = select(
        [broad_source, "runtime/api/leaf.py"],
        build_import_index(root),
        bounded=True,
    )

    assert selection.fallback_rule == "effectively_full_selection"
    assert selection.bounded_deferral is True
    assert selection.trigger_paths == (broad_source,)
    assert selection.files == _with_floor("runtime/api/test_middle.py")


def test_bounded_deferral_keeps_small_direct_importer_set(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    source = "runtime/api/foundation.py"
    bridge = "runtime/api/foundation_bridge.py"
    direct_test = "runtime/api/test_foundation_direct.py"
    _write(root, source, "VALUE = 1\n")
    _write(root, bridge, "from runtime.api import foundation\n")
    _write(root, direct_test, "from runtime.api import foundation\n")
    for number in range(impacted_tests.MIN_EFFECTIVELY_FULL_FILE_UNIVERSE):
        _write(
            root,
            f"runtime/api/test_bridge_{number}.py",
            "from runtime.api import foundation_bridge\n",
        )

    selection = select(
        ["docs/lifecycle.md", source],
        build_import_index(root),
        bounded=True,
    )

    assert selection.bounded_deferral is True
    assert selection.fallback_rule == "unmapped_file_kind"
    assert selection.files == _with_floor(direct_test)
