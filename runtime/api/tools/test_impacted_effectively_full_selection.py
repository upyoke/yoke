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


def _broad_importer_repo(tmp_path: Path) -> tuple[Path, str]:
    """A changed module one hop under a consumer whose branch is near-total.

    This is the shape that puts selection on the direct-tests fallback: the
    consumer itself is narrow, but a hub above it makes its transitive
    branch near-total, so the fallback contributes the consumer's own
    direct tests rather than its branch.
    """
    root = _tiny_repo(tmp_path)
    changed = "runtime/api/changed_core.py"
    _write(root, changed, "VALUE = 1\n")
    _write(root, "runtime/api/consumer.py", "from runtime.api import changed_core\n")
    _write(root, "runtime/api/hub.py", "from runtime.api import consumer\n")
    for number in range(impacted_tests.MIN_EFFECTIVELY_FULL_FILE_UNIVERSE):
        _write(
            root, f"runtime/api/test_hub_{number}.py", "from runtime.api import hub\n"
        )
    return root, changed


def test_bounded_deferral_reaches_tests_through_a_sibling_s_helpers(
    tmp_path: Path,
) -> None:
    """A test module is also a source: its importers are impacted too.

    The direct-tests fallback contributes the test that imports the changed
    consumer, and that test is frequently where siblings keep their shared
    fixtures and seeding helpers. Stopping there covers the module that
    DEFINES a helper and none of the ones that use it.
    """
    root, changed = _broad_importer_repo(tmp_path)
    _write(
        root,
        "runtime/api/test_seed_helpers.py",
        "from runtime.api import consumer\n\ndef seed():\n    return consumer\n",
    )
    _write(
        root,
        "runtime/api/test_helper_user.py",
        "from runtime.api.test_seed_helpers import seed\n",
    )
    _write(
        root,
        "runtime/api/test_helper_user_second_hop.py",
        "from runtime.api.test_helper_user import seed\n",
    )

    bounded = select(
        ["docs/lifecycle.md", changed], build_import_index(root), bounded=True
    )

    assert bounded.bounded_deferral is True
    assert "runtime/api/test_seed_helpers.py" in bounded.files
    # Both hops: the sibling importing the helper, and the one importing it.
    assert "runtime/api/test_helper_user.py" in bounded.files
    assert "runtime/api/test_helper_user_second_hop.py" in bounded.files
    # Still bounded — the hub's fanout is not pulled in behind them.
    assert "runtime/api/test_hub_0.py" not in bounded.files


def test_helper_closure_terminates_on_a_cycle_without_duplicating(
    tmp_path: Path,
) -> None:
    """Test modules importing each other terminate and appear once."""
    root, changed = _broad_importer_repo(tmp_path)
    _write(
        root,
        "runtime/api/test_cycle_first.py",
        "from runtime.api import consumer\nfrom runtime.api import test_cycle_second\n",
    )
    _write(
        root,
        "runtime/api/test_cycle_second.py",
        "from runtime.api import test_cycle_first\n",
    )

    bounded = select(
        ["docs/lifecycle.md", changed], build_import_index(root), bounded=True
    )

    assert "runtime/api/test_cycle_first.py" in bounded.files
    assert "runtime/api/test_cycle_second.py" in bounded.files
    assert len(bounded.files) == len(set(bounded.files))


def test_helper_closure_still_obeys_the_caller_s_bound(tmp_path: Path) -> None:
    """Closing the helper edge cannot smuggle a near-total set through.

    The closure widens the importer set, so the bound the caller already
    applies to that set is what keeps a widely-imported test helper from
    re-expanding a deferred selection into the full suite. The users here
    import the hub as well, so they are what makes the consumer's branch
    near-total AND what the closure would add — the set has to dominate
    the universe for the caller's bound to have anything to refuse.
    """
    root = _tiny_repo(tmp_path)
    changed = "runtime/api/changed_core.py"
    _write(root, changed, "VALUE = 1\n")
    _write(root, "runtime/api/consumer.py", "from runtime.api import changed_core\n")
    _write(root, "runtime/api/hub.py", "from runtime.api import consumer\n")
    _write(
        root,
        "runtime/api/test_shared_fixtures.py",
        "from runtime.api import consumer\n\ndef fixture():\n    return consumer\n",
    )
    for number in range(120):
        _write(
            root,
            f"runtime/api/test_fixture_user_{number}.py",
            "from runtime.api import hub\n"
            "from runtime.api.test_shared_fixtures import fixture\n",
        )

    index = build_import_index(root)
    total = sum(is_test_file(path) for path in index.module_of)
    # The closure's own result is near-total here, which is precisely the
    # case the caller is responsible for refusing.
    assert is_effectively_full(
        len(
            impacted_tests.bounded_importer_tests((changed,), index, total_files=total)
        ),
        total,
    )

    bounded = select(["docs/lifecycle.md", changed], index, bounded=True)

    assert bounded.bounded_deferral is True
    assert "runtime/api/test_fixture_user_0.py" not in bounded.files
    assert not is_effectively_full(len(bounded.files), total)
