"""Bounded reachability retains changes beside an effectively-full trigger."""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import impacted_tests
from yoke_core.tools.impacted_tests import (
    build_import_index,
    is_effectively_full,
    is_test_file,
    reachable_tests,
    select,
)

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


def test_bounded_deferral_keeps_tests_on_a_narrow_importer_branch(
    tmp_path: Path,
) -> None:
    root = _tiny_repo(tmp_path)
    source = "runtime/api/foundation.py"
    broad_bridge = "runtime/api/broad_bridge.py"
    narrow_bridge = "runtime/api/narrow_bridge.py"
    narrow_test = "runtime/api/test_narrow_bridge.py"
    _write(root, source, "VALUE = 1\n")
    _write(root, broad_bridge, "from runtime.api import foundation\n")
    _write(root, narrow_bridge, "from runtime.api import foundation\n")
    _write(root, narrow_test, "from runtime.api import narrow_bridge\n")
    for number in range(impacted_tests.MIN_EFFECTIVELY_FULL_FILE_UNIVERSE):
        _write(
            root,
            f"runtime/api/test_broad_bridge_{number}.py",
            "from runtime.api import broad_bridge\n",
        )

    selection = select([source], build_import_index(root), bounded=True)

    assert selection.fallback_rule == "effectively_full_selection"
    assert selection.bounded_deferral is True
    assert selection.files == _with_floor(narrow_test)


def test_bounded_keeps_a_broad_importer_s_own_test(tmp_path: Path) -> None:
    """A one-hop consumer's own test survives its branch being near-total.

    The consumer of a changed symbol is the cheapest place that breakage
    shows up, but its transitive branch is near-total whenever anything
    broadly imported sits above it. Dropping the importer wholesale for
    that reason loses exactly the test the change most needed.
    """
    root = _tiny_repo(tmp_path)
    changed = "runtime/api/changed_core.py"
    _write(root, changed, "VALUE = 1\n")
    _write(
        root,
        "runtime/api/consumer.py",
        "from runtime.api import changed_core\n",
    )
    _write(
        root,
        "runtime/api/test_consumer.py",
        "from runtime.api import consumer\n",
    )
    # A hub above the consumer makes the consumer's own branch near-total
    # without the consumer itself being broad.
    _write(root, "runtime/api/hub.py", "from runtime.api import consumer\n")
    for number in range(impacted_tests.MIN_EFFECTIVELY_FULL_FILE_UNIVERSE):
        _write(
            root,
            f"runtime/api/test_hub_{number}.py",
            "from runtime.api import hub\n",
        )

    index = build_import_index(root)
    consumer_branch = reachable_tests(("runtime/api/consumer.py",), index)
    total = sum(is_test_file(path) for path in index.module_of)
    assert is_effectively_full(len(consumer_branch or ()), total)

    bounded = select(["docs/lifecycle.md", changed], index, bounded=True)

    assert bounded.bounded_deferral is True
    assert "runtime/api/test_consumer.py" in bounded.files
    # Still a bounded subset — the hub's fanout is not pulled in with it.
    assert "runtime/api/test_hub_0.py" not in bounded.files


def test_unmapped_file_does_not_drop_python_reachability(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    broad = "runtime/api/foundation.py"
    _write(root, broad, "VALUE = 1\n")
    for number in range(impacted_tests.MIN_EFFECTIVELY_FULL_FILE_UNIVERSE):
        _write(
            root,
            f"runtime/api/test_foundation_{number}.py",
            "from runtime.api import foundation\n",
        )

    python_only = select(
        [broad, "runtime/api/leaf.py"],
        build_import_index(root),
        bounded=True,
    )
    with_docs = select(
        ["docs/lifecycle.md", broad, "runtime/api/leaf.py"],
        build_import_index(root),
        bounded=True,
    )

    assert "runtime/api/test_middle.py" in python_only.files
    assert with_docs.fallback_rule == "unmapped_file_kind"
    assert with_docs.trigger_paths == ("docs/lifecycle.md",)
    assert "runtime/api/test_middle.py" in with_docs.files
    assert with_docs.telemetry().startswith(
        "impacted-selection scope=bounded_deferral rule=unmapped_file_kind "
        "triggers=docs/lifecycle.md "
    )
