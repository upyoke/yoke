"""Interpreter selection happens before duration splitting."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime import ci_test_selection as selection


def _item(node_id, fixtures=()):
    return SimpleNamespace(
        nodeid=node_id, fixturenames=fixtures, get_closest_marker=lambda _: None
    )


def test_oldest_leg_deselects_repository_and_wheel_checks(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".test_durations").write_text("{}")
    monkeypatch.setattr(selection, "DURATIONS_PATH", str(tmp_path / ".test_durations"))
    monkeypatch.setenv("YOKE_CI_PYTHON_SCOPE", "interpreter")
    independent = [
        _item("tests/teaching_prototype/test_map.py::test_links"),
        _item("runtime/api/test_runtime.py::test_installed", ["product_venv"]),
        _item("runtime/api/domain/test_path_snapshots.py::test_graph"),
        _item("runtime/api/engines/test_doctor_hc_paths.py::test_tree"),
        _item("runtime/api/test_doc_hygiene.py::test_links"),
        _item("runtime/api/test_command_teaching.py::test_recipe"),
    ]
    runtime = _item("runtime/api/test_service_client.py::test_parser")
    items = independent + [runtime]
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=Mock()))
    selection.pytest_collection_modifyitems(config, items)
    assert items == [runtime]
    config.hook.pytest_deselected.assert_called_once_with(items=independent)


def test_latest_and_local_runs_keep_every_test(monkeypatch):
    monkeypatch.delenv("YOKE_CI_PYTHON_SCOPE", raising=False)
    items = [_item("tests/teaching_prototype/test_map.py::test_links")]
    selection.pytest_collection_modifyitems(None, items)
    assert len(items) == 1


@pytest.mark.parametrize("scope", ["interpreter", "all"])
def test_repository_scans_and_node_checks_run_only_on_latest_leg(monkeypatch, tmp_path, scope):
    monkeypatch.setenv("YOKE_CI_PYTHON_SCOPE", scope)
    profile = tmp_path / "durations.json"
    profile.write_text("{}")
    monkeypatch.setattr(selection, "DURATIONS_PATH", str(profile))
    independent = [
        _item("runtime/api/test_universe_ui_mount_contract.py::test_node"),
        _item("runtime/api/domain/test_github_operation_permission_scopes.py::test_scan"),
        _item("runtime/api/tools/test_impacted_tests.py::test_select"),
        _item("runtime/api/tools/test_impacted_path_literal_references.py::test_edges"),
    ]
    runtime = _item("runtime/api/tools/test_watch_pytest_impacted_default.py::test_run")
    items = [*independent, runtime]
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=Mock()))
    selection.pytest_collection_modifyitems(config, items)
    assert items == ([runtime] if scope == "interpreter" else [*independent, runtime])
    config.hook.pytest_deselected.assert_called_once_with(
        items=independent if scope == "interpreter" else []
    )


def test_file_groups_keep_setup_cases_together_and_cover_every_item():
    items = [_item(f"tests/test_{name}.py::test_{case}")
             for name in "abc" for case in range(2)]
    durations = {item.nodeid: weight for item, weight in zip(items, [9, 1, 8, 2, 1, 1])}
    groups = [selection.file_group(items, durations, 2, group) for group in (1, 2)]
    assert groups[0][0].isdisjoint(groups[1][0])
    assert groups[0][0] | groups[1][0] == {
        "tests/test_a.py", "tests/test_b.py", "tests/test_c.py"
    }
    assert sorted(estimate for _, estimate in groups) == [10, 12]


def test_new_files_receive_known_mean_weight():
    items = [_item("tests/test_known.py::test_case"), _item("tests/test_new.py::test_case")]
    groups = [selection.file_group(items, {items[0].nodeid: 4}, 2, n) for n in (1, 2)]
    assert sorted(weight for _, weight in groups) == [4, 4]


def test_short_expensive_files_start_before_long_cheap_files():
    cheap = [_item(f"tests/test_cheap.py::test_{n}") for n in range(3)]
    expensive = _item("tests/test_expensive.py::test_case")
    items = cheap + [expensive]
    splitter = SimpleNamespace(
        cached_durations={item.nodeid: 1 for item in cheap} | {expensive.nodeid: 10},
        writer=Mock(),
    )
    config = SimpleNamespace(
        option=SimpleNamespace(splits=1, group=1),
        hook=SimpleNamespace(pytest_deselected=Mock()),
    )
    selection._FileSplitter(splitter).pytest_collection_modifyitems(config, items)
    assert items == [expensive, *cheap]


def test_product_wheel_files_share_one_shard():
    wheel = [
        _item(f"tests/test_wheel_{name}.py::test_case", ["product_venv"])
        for name in "ab"
    ] + [_item("tests/test_wheel_c.py::test_case", ["product_wheelhouse"])]
    plain = [_item(f"tests/test_plain_{name}.py::test_case") for name in "ab"]
    items = wheel + plain
    durations = {item.nodeid: 5 for item in items}
    groups = [selection.file_group(items, durations, 3, n)[0] for n in (1, 2, 3)]
    wheel_files = {item.nodeid.split("::", 1)[0] for item in wheel}
    assert [group for group in groups if group & wheel_files] == [wheel_files]
    assert set().union(*groups) == wheel_files | {
        "tests/test_plain_a.py", "tests/test_plain_b.py"
    }


def test_collection_fingerprint_records_the_unsplit_ids():
    items = [_item(f"tests/test_{name}.py::test_case") for name in "abcd"]
    splitter = SimpleNamespace(cached_durations={}, writer=Mock())
    configs = []
    for group in (1, 2):
        config = SimpleNamespace(
            option=SimpleNamespace(splits=2, group=group), workeroutput={},
            hook=SimpleNamespace(pytest_deselected=Mock()),
        )
        selected = list(items)
        selection._FileSplitter(splitter).pytest_collection_modifyitems(config, selected)
        assert len(selected) == 2
        configs.append(config)
    assert configs[0].workeroutput == configs[1].workeroutput
    assert configs[0].workeroutput["ci_collection"]["count"] == 4


def test_worker_collection_fingerprint_reaches_the_controller_log():
    reporter = Mock()
    node = SimpleNamespace(
        workeroutput={"ci_collection": {"count": 4, "ids_sha256": "abc"}},
        gateway=SimpleNamespace(id="gw0"),
        config=SimpleNamespace(pluginmanager=SimpleNamespace(get_plugin=lambda _: reporter)),
    )
    selection.pytest_testnodedown(node, None)
    assert 'CI collection gw0:' in reporter.write_line.call_args.args[0]
    assert '"count": 4' in reporter.write_line.call_args.args[0]


def test_worker_crash_without_collection_telemetry_keeps_its_original_verdict():
    selection.pytest_testnodedown(SimpleNamespace(), RuntimeError("worker lost"))


def test_assigned_files_are_ordered_by_weight_and_fingerprinted(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YOKE_CI_PYTHON_SCOPE", "all")
    (tmp_path / ".test_durations").write_text(
        '{"tests/test_a.py::test_case": 1, "tests/test_b.py::test_case": 9}'
    )
    monkeypatch.setattr(selection, "DURATIONS_PATH", str(tmp_path / ".test_durations"))
    items = [_item(f"tests/test_{name}.py::test_case") for name in "ab"]
    config = SimpleNamespace(workeroutput={}, hook=SimpleNamespace(pytest_deselected=Mock()))
    selection.pytest_collection_modifyitems(config, items)
    assert items[0].nodeid == "tests/test_b.py::test_case"
    assert config.workeroutput["ci_collection"]["count"] == 2


def test_profile_lookup_survives_a_nested_run_from_another_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YOKE_CI_PYTHON_SCOPE", "all")
    items = [_item("tests/test_selected.py::test_case")]
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=Mock()))
    selection.pytest_collection_modifyitems(config, items)
    assert len(items) == 1
