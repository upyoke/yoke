"""Interpreter selection happens before duration splitting."""

from types import SimpleNamespace
from unittest.mock import Mock

from runtime import ci_test_selection as selection


def _item(node_id, fixtures=()):
    return SimpleNamespace(
        nodeid=node_id, fixturenames=fixtures, get_closest_marker=lambda _: None
    )


def test_oldest_leg_deselects_repository_and_wheel_checks(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".test_durations").write_text("{}")
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


def test_assigned_files_are_ordered_by_weight_and_fingerprinted(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YOKE_CI_PYTHON_SCOPE", "all")
    (tmp_path / ".test_durations").write_text(
        '{"tests/test_a.py::test_case": 1, "tests/test_b.py::test_case": 9}'
    )
    items = [_item(f"tests/test_{name}.py::test_case") for name in "ab"]
    config = SimpleNamespace(workeroutput={}, hook=SimpleNamespace(pytest_deselected=Mock()))
    selection.pytest_collection_modifyitems(config, items)
    assert items[0].nodeid == "tests/test_b.py::test_case"
    assert config.workeroutput["ci_collection"]["count"] == 2


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
