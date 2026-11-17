"""The per-OS known-failure baselines name real tests, each with a reason."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime import known_failure_baseline as baseline
from runtime import known_failure_baseline_record as record

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOTS = ("runtime/api/", "runtime/harness/", "tests/")
OS_NAMES = sorted(set(baseline.PLATFORM_BASELINES.values()))


def _defined_tests(path: Path) -> set[str]:
    """``name`` and ``Class::name`` for every test function the module defines."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    names = {node.name for node in tree.body if isinstance(node, functions)}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names |= {
                f"{node.name}::{child.name}"
                for child in node.body
                if isinstance(child, functions)
            }
    return names


def _entry_problem(node_id: str, reason: object) -> str | None:
    if not isinstance(reason, str) or not reason.strip():
        return "has no reason"
    file_part, separator, test_part = node_id.partition("::")
    if "\\" in file_part:
        return "must use / separators"
    if not file_part.startswith(SUITE_ROOTS) or not file_part.endswith(".py"):
        return "is not a suite node id (path.py or path.py::test)"
    path = REPO_ROOT / file_part
    if not path.is_file():
        return f"names missing file {file_part}"
    if "[" in test_part and not test_part.endswith("]"):
        return "has an unclosed [params] part"
    test = test_part.split("[", 1)[0]
    if separator and test not in _defined_tests(path):
        return f"names no test {test} in {file_part}"
    return None


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_every_entry_names_a_real_test_with_a_reason(os_name: str) -> None:
    entries = baseline.load_baseline(os_name)
    problems = {
        node_id: problem
        for node_id, reason in entries.items()
        if (problem := _entry_problem(node_id, reason)) is not None
    }
    assert problems == {}, baseline.BASELINE_DIR / os_name


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_baseline_files_hold_one_entry_per_line(os_name: str) -> None:
    for path in baseline.baseline_files(os_name):
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == len(json.loads("\n".join(lines))) + 2, path


def test_entry_check_rejects_missing_reason_file_and_test() -> None:
    this = "tests/test_known_failure_baseline.py"
    real = f"{this}::test_entry_check_rejects_missing_reason_file_and_test"
    assert _entry_problem(real, "why") is None
    assert _entry_problem(real + "[case]", "why") is None
    assert _entry_problem(this, "module cannot import") is None
    assert _entry_problem(real, " ") == "has no reason"
    assert "missing file" in _entry_problem("tests/test_absent.py::test_x", "why")
    assert "names no test" in _entry_problem(f"{this}::test_absent", "why")
    assert "separators" in _entry_problem("tests\\test_known_failure_baseline.py::x", "why")
    assert _entry_problem(real + "[C:\\temp]", "why") is None
    assert "unclosed" in _entry_problem(real + "[/tmp/a", "why")


def test_duplicate_entries_across_files_are_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(baseline, "BASELINE_DIR", tmp_path)
    (tmp_path / "windows").mkdir()
    for name in ("a", "b"):
        (tmp_path / "windows" / f"{name}.json").write_text('{"tests/x.py::t": "why"}')
    with pytest.raises(pytest.UsageError, match="known_failure_baseline_duplicate"):
        baseline.load_baseline("windows")


class _Item(SimpleNamespace):
    def add_marker(self, marker) -> None:
        self.markers.append(marker)


def _marked(monkeypatch, platform: str, enabled: bool, entries: dict[str, str]):
    monkeypatch.setattr(baseline.sys, "platform", platform)
    if enabled:
        monkeypatch.setenv(baseline.ENABLE_ENV, "1")
    else:
        monkeypatch.delenv(baseline.ENABLE_ENV, raising=False)
    monkeypatch.setattr(baseline, "load_baseline", lambda _os: entries)
    config = SimpleNamespace(stash={})
    baseline.pytest_configure(config)
    items = [
        _Item(nodeid=node_id, markers=[], stash={})
        for node_id in ("tests/a.py::test_x[1]", "tests/a.py::test_y", "tests/a.py::test_z")
    ]
    baseline.pytest_collection_modifyitems(config, items)
    return {item.nodeid: item for item in items}


def test_listed_tests_become_strict_xfail_on_their_os(monkeypatch) -> None:
    marked = _marked(
        monkeypatch, "win32", True,
        {"tests/a.py::test_x": "uses fcntl", "tests/a.py::test_y": "POSIX paths"},
    )
    assert marked["tests/a.py::test_z"].markers == []
    for node_id, reason in (("tests/a.py::test_x[1]", "uses fcntl"), ("tests/a.py::test_y", "POSIX paths")):
        (marker,) = marked[node_id].markers
        assert marker.name == "xfail"
        assert marker.kwargs == {"strict": True, "reason": f"windows known failure: {reason}"}


@pytest.mark.parametrize("platform, enabled", [("linux", True), ("darwin", False)])
def test_no_baseline_applies_off_os_or_without_opt_in(monkeypatch, platform, enabled) -> None:
    marked = _marked(monkeypatch, platform, enabled, {"tests/a.py::test_y": "why"})
    assert all(item.markers == [] for item in marked.values())


def _drive(wrapper, report):
    generator = wrapper
    next(generator)
    with pytest.raises(StopIteration) as done:
        generator.send(report)
    return done.value.value


def _phase(item, when, outcome, excinfo=None, **extra):
    report = SimpleNamespace(when=when, outcome=outcome, failed=outcome == "failed", longrepr="x", **extra)
    return _drive(baseline.pytest_runtest_makereport(item, SimpleNamespace(excinfo=excinfo)), report)


@pytest.mark.parametrize("teardown_fails", [True, False])
def test_listed_test_is_judged_once_teardown_is_known(monkeypatch, teardown_fails) -> None:
    item = _marked(monkeypatch, "win32", True, {"tests/a.py::test_y": "why"})["tests/a.py::test_y"]
    # pytest's strict xfail reports a passing body as a failed call.
    call = _phase(item, "call", "failed")
    assert call.outcome == "passed" and call.longrepr is None
    teardown = _phase(item, "teardown", "skipped" if teardown_fails else "passed",
                      excinfo=object() if teardown_fails else None)
    if teardown_fails:
        assert teardown.outcome == "skipped"
        assert teardown.wasxfail == "windows known failure: why"
    else:
        assert teardown.outcome == "failed"
        assert teardown.longrepr.startswith(f"{baseline.XPASS_MARK} tests/a.py::test_y passed")


def test_expected_call_failure_and_unlisted_tests_are_left_alone(monkeypatch) -> None:
    marked = _marked(monkeypatch, "win32", True, {"tests/a.py::test_y": "why"})
    xfailed = _phase(marked["tests/a.py::test_y"], "call", "skipped", excinfo=object(), wasxfail="why")
    assert xfailed.outcome == "skipped"
    assert _phase(marked["tests/a.py::test_y"], "teardown", "passed").outcome == "passed"
    assert _phase(marked["tests/a.py::test_z"], "teardown", "failed", excinfo=object()).outcome == "failed"


@pytest.mark.parametrize("failed", [True, False])
def test_listed_module_must_keep_failing_to_import(monkeypatch, failed) -> None:
    monkeypatch.setattr(baseline.sys, "platform", "win32")
    monkeypatch.setenv(baseline.ENABLE_ENV, "1")
    module = object.__new__(pytest.Module)
    config = SimpleNamespace(stash={baseline._ENTRIES: {"tests/a.py": "imports fcntl"}})
    monkeypatch.setattr(pytest.Module, "config", config, raising=False)
    monkeypatch.setattr(pytest.Module, "nodeid", "tests/a.py", raising=False)
    monkeypatch.setattr(pytest.Module, "path", Path("tests/a.py"), raising=False)
    report = SimpleNamespace(failed=failed, outcome="failed" if failed else "passed", result=["t"])
    result = _drive(baseline.pytest_make_collect_report(module), report)
    if failed:
        assert result.outcome == "skipped"
        assert "windows known failure: imports fcntl" in result.longrepr[2]
    else:
        # It imports: its tests are listed, so each passing one XPASSes.
        assert result.outcome == "passed" and result.result == ["t"]
        assert baseline.baseline_reason("tests/a.py::test_q[2]", {"tests/a.py": "why"}) == "why"


def test_recorder_adds_failures_keeps_entries_and_drops_xpasses(tmp_path) -> None:
    lines = [
        "2026-11-17T00:21:53.8394317Z FAILED tests/a.py::test_x[1] - AttributeError: module 'os' has no attribute 'getuid'",
        "ERROR tests/b.py - ModuleNotFoundError: No module named 'pwd'",
        "[XPASS(strict)] tests/a.py::test_y passed: windows known failure: old",
        "ERROR tests/a.py::test_y",
        "[gw0] [ 5%] FAILED tests/a.py::test_ignored_progress_line",
        "FAILED tests/a.py::test_bare",
        "FAILED tests/a.py::test_p[/tmp/a dir - x] - assert 'D:\\tmp' == '/tmp'",
        "ERROR tests/a.py::test_q[two words]",
        "FAILED tests/a.py::test_slow - subprocess.TimeoutExpired: Command '['/tmp/venv/bin/yoke', 'setup', '--x']' timed out after 120 seconds",
    ]
    failures, passed = record.summary_entries(lines)
    assert failures == {
        "tests/a.py::test_x[1]": "AttributeError: module 'os' has no attribute 'getuid'",
        "tests/b.py": "ModuleNotFoundError: No module named 'pwd'",
        "tests/a.py::test_bare": "fails with no message",
        "tests/a.py::test_p[/tmp/a dir - x]": "assert 'D:\\tmp' == '/tmp'",
        "tests/a.py::test_q[two words]": "fails with no message",
        "tests/a.py::test_slow": "subprocess.TimeoutExpired: yoke timed out after 120 seconds",
    }
    assert passed == {"tests/a.py::test_y"}
    entries = {f"runtime/api/cli/test_{n:03}.py::test": "why" for n in range(record.ENTRIES_PER_FILE + 1)}
    entries["tests/b.py"] = "no pwd"
    written = record.write_baseline("windows", entries, root=tmp_path)
    assert [path.name for path in written] == ["runtime-api-cli-1.json", "runtime-api-cli-2.json", "tests.json"]
    merged = {}
    for path in written:
        merged.update(json.loads(path.read_text(encoding="utf-8")))
    assert merged == entries


def test_recorder_reads_exact_node_ids_from_junit(tmp_path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("")
    report = tmp_path / "pytest-report.xml"
    report.write_text(
        """<testsuites><testsuite>
<testcase classname="tests.test_a" name="test_x[two words\\nline]"><failure message="AssertionError: assert 1 == 2&#10;more">t</failure></testcase>
<testcase classname="tests.test_a.TestK" name="test_y"><error message='failed on setup with "OSError: nope"'>t</error></testcase>
<testcase classname="tests.test_a" name="test_z"><error message="failed on teardown with &quot;[XPASS(strict)] tests/test_a.py::test_z passed: r&quot;">t</error></testcase>
<testcase classname="" name="tests.test_b"><error message="collection failure">tests/test_b.py:1: in &lt;module&gt;
    import pwd
E   ModuleNotFoundError: No module named 'pwd'</error></testcase>
<testcase classname="tests.test_a" name="test_ok"/>
</testsuite></testsuites>""",
        encoding="utf-8",
    )
    failures, passed = record.junit_entries(report, root=tmp_path)
    assert failures == {
        "tests/test_a.py::test_x[two words\\nline]": "AssertionError: assert 1 == 2",
        "tests/test_a.py::TestK::test_y": "OSError: nope",
        "tests/test_b.py": "ModuleNotFoundError: No module named 'pwd'",
    }
    assert passed == {"tests/test_a.py::test_z"}
