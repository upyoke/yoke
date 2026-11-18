"""Each known-failure entry is its own file, named for its node id."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from runtime import known_failure_baseline as baseline
from runtime import known_failure_baseline_record as record

pytestmark = pytest.mark.windows

OS_NAMES = sorted(set(baseline.PLATFORM_BASELINES.values()))


def _write(directory: Path, name: str, body: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return path


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_checked_in_entries_are_one_per_file_and_named_for_their_node_id(os_name: str) -> None:
    for directory in (baseline.BASELINE_DIR / os_name, baseline.FLAKY_DIR / os_name):
        for path in baseline.entry_files(directory):
            entry = json.loads(path.read_text(encoding="utf-8"))
            assert path.name == baseline.entry_file_name(entry["node_id"]), path
    assert not list(baseline.BASELINE_DIR.glob("*.json")), "no shard files beside the OS folders"
    assert not list(baseline.FLAKY_DIR.glob("*.json")), "no shard files beside the flaky OS folders"


def test_entry_file_name_is_short_and_portable() -> None:
    long_id = "tests/a.py::test_x[" + "C:\\temp|<a>?*" * 40000 + "]"
    name = baseline.entry_file_name(long_id)
    assert len(name) == len("0123456789abcdef.json")
    assert name[:-5].isalnum() and name == baseline.entry_file_name(long_id)


def test_a_file_not_named_for_its_node_id_is_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(baseline, "BASELINE_DIR", tmp_path)
    node_id = "tests/x.py::t"
    _write(tmp_path / "windows", "0000000000000000.json", {"node_id": node_id, "reason": "why"})
    with pytest.raises(pytest.UsageError, match="known_failure_baseline_misnamed") as refused:
        baseline.load_baseline("windows")
    assert baseline.entry_file_name(node_id) in str(refused.value)


@pytest.mark.parametrize(
    "body",
    [
        "{not json",
        ["tests/x.py::t", "why"],
        {"tests/x.py::t": "why"},  # the old shard shape
        {"node_id": "tests/x.py::t"},
        {"node_id": "tests/x.py::t", "reason": " "},
        {"node_id": "", "reason": "why"},
        {"node_id": "tests/x.py::t", "reason": "why", "extra": 1},
    ],
)
def test_a_malformed_entry_file_is_refused(tmp_path, monkeypatch, body) -> None:
    monkeypatch.setattr(baseline, "BASELINE_DIR", tmp_path)
    _write(tmp_path / "windows", baseline.entry_file_name("tests/x.py::t"), body)
    with pytest.raises(pytest.UsageError, match=r"known_failure_baseline_(unreadable|invalid)"):
        baseline.load_baseline("windows")


def test_a_missing_folder_is_an_empty_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(baseline, "BASELINE_DIR", tmp_path)
    monkeypatch.setattr(baseline, "FLAKY_DIR", tmp_path / "flaky")
    assert baseline.load_baseline("macos") == {} and baseline.load_flaky("macos") == {}


def test_flaky_entries_require_feedback_and_fix_item(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(baseline, "FLAKY_DIR", tmp_path)
    node_id = "tests/x.py::t"
    name = baseline.entry_file_name(node_id)
    for bad in (
        {"node_id": node_id, "reason": "why", "feedback": 1},
        {"node_id": node_id, "reason": "why", "feedback": "1", "fix_item": "YOK-9"},
        {"node_id": node_id, "reason": "why", "feedback": 1, "fix_item": "soon"},
    ):
        _write(tmp_path / "windows", name, bad)
        with pytest.raises(pytest.UsageError, match="known_flaky_list_invalid"):
            baseline.load_flaky("windows")
    _write(tmp_path / "windows", name, {"node_id": node_id, "reason": "why", "feedback": 1, "fix_item": "YOK-9"})
    assert baseline.load_flaky("windows") == {node_id: {"reason": "why", "feedback": 1, "fix_item": "YOK-9"}}
    _write(tmp_path / "windows", "0000000000000000.json", {"node_id": "tests/y.py::t", "reason": "r", "feedback": 1, "fix_item": "YOK-9"})
    with pytest.raises(pytest.UsageError, match="known_flaky_list_misnamed"):
        baseline.load_flaky("windows")


def test_recorder_writes_and_deletes_only_changed_entry_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(baseline, "BASELINE_DIR", tmp_path)
    first = {"tests/a.py::t": "one", "tests/b.py::t": "two", "tests/c.py": "three"}
    assert record.write_baseline("windows", first, root=tmp_path) == (3, 0)
    assert baseline.load_baseline("windows") == first
    kept = tmp_path / "windows" / baseline.entry_file_name("tests/a.py::t")
    stamp = kept.stat().st_mtime_ns
    second = {"tests/a.py::t": "one", "tests/c.py": "changed", "tests/d.py::t[x]": "four"}
    assert record.write_baseline("windows", second, root=tmp_path) == (2, 1)
    assert baseline.load_baseline("windows") == second
    assert kept.stat().st_mtime_ns == stamp
    assert sorted(p.name for p in (tmp_path / "windows").iterdir()) == sorted(
        baseline.entry_file_name(node_id) for node_id in second
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )


def test_branches_deleting_different_entries_merge_without_conflict(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    root = repo / "baselines"
    # Adjacent node ids: in one shard they would be adjacent lines.
    entries = {f"tests/test_x.py::test_{n}": f"reason {n}" for n in range(5)}
    record.write_baseline("windows", entries, root=root)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    for branch, fixed in (("one", "tests/test_x.py::test_1"), ("two", "tests/test_x.py::test_2")):
        _git(repo, "checkout", "-q", "-b", branch, "main")
        record.write_baseline("windows", {k: v for k, v in entries.items() if k != fixed}, root=root)
        _git(repo, "commit", "-q", "-am", f"fix {fixed}")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-edit", "one")
    _git(repo, "merge", "-q", "--no-edit", "two")  # check=True: a conflict fails here
    names = sorted(p.name for p in (root / "windows").iterdir())
    remaining = {k for k in entries if k not in {"tests/test_x.py::test_1", "tests/test_x.py::test_2"}}
    assert names == sorted(baseline.entry_file_name(k) for k in remaining)
