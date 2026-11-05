"""Automatic timing refresh cannot undo a committed fixture-cost reset."""

import json
from pathlib import Path
import subprocess

import pytest

from yoke_core.tools import ci_durations_refresh as refresh


def _reports(directory, problem=None):
    for group in range(1, refresh.SHARD_COUNT + 1):
        if problem == "missing" and group == refresh.SHARD_COUNT:
            continue
        report = directory / f"pytest-output-3.14-{group}" / "pytest-report.xml"
        report.parent.mkdir(parents=True)
        name = 1 if problem == "duplicate" else group
        report.write_text(
            f'<testsuites><testsuite time="10" failures="0" errors="0">'
            f'<testcase classname="source" name="test_{name}" time="20"/>'
            '</testsuite></testsuites>'
            if problem != "malformed" else '<testsuites>'
        )


@pytest.fixture
def history(tmp_path):
    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(tmp_path), *args], text=True,
        ).strip()

    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    profile = tmp_path / refresh.DURATIONS_PATH
    profile.write_text('{"case": 100}')
    git("add", ".")
    git("commit", "-qm", "Initial costs")
    older = git("rev-parse", "HEAD")
    profile.write_text('{"case": 1}')
    git("commit", "-qam", "Measured fixture costs")
    baseline = git("rev-parse", "HEAD")
    (tmp_path / "source.py").write_text("value = 1\n")
    git("add", ".")
    git("commit", "-qm", "Source using the measured baseline")
    descendant = git("rev-parse", "HEAD")
    return tmp_path, older, baseline, descendant


def test_baseline_comes_from_profile_history_and_requires_source_ancestry(history):
    root, older, baseline, descendant = history
    assert refresh.profile_baseline(root) == baseline
    assert not refresh.contains_baseline(root, baseline, older)
    assert refresh.contains_baseline(root, baseline, baseline)
    assert refresh.contains_baseline(root, baseline, descendant)
    assert not refresh.contains_baseline(root, baseline, "0" * 40)


@pytest.mark.parametrize("incompatible", ["source", "extra-shard", "missing-shard"])
def test_latest_skips_incompatible_source_or_report_sets(
    history, monkeypatch, tmp_path, incompatible,
):
    root, older, _baseline, descendant = history
    requests = []

    def gh(args):
        requests.append(args)
        if args[0] == "run":
            assert args[-1] == "databaseId,headSha"
            # Repository recency does not imply compatible fixture costs.
            return [
                {"databaseId": 30, "headSha": older if incompatible == "source" else descendant},
                {"databaseId": 20, "headSha": descendant},
            ]
        count = refresh.SHARD_COUNT
        if args[-1] == "repos/owner/repo/actions/runs/30/artifacts":
            assert incompatible != "source", "stale source must not reach artifacts"
            count += 1 if incompatible == "extra-shard" else -1
        else:
            assert args == [
                "api", "--paginate", "--slurp",
                "repos/owner/repo/actions/runs/20/artifacts",
            ]
        # Required reports can straddle pages after increasing matrix size.
        artifacts = [
            {"name": f"pytest-output-3.14-{group}", "expired": False}
            for group in range(1, count + 1)
        ]
        return [{"artifacts": artifacts[:3]}, {"artifacts": artifacts[3:]}]

    real_run = subprocess.run
    downloads = []

    def run(args, **kwargs):
        if args[0] == "gh":
            downloads.append(args)
            _reports(Path(args[-1]))
            return subprocess.CompletedProcess(args, 0)
        return real_run(args, **kwargs)

    monkeypatch.setattr(refresh, "_gh", gh)
    monkeypatch.setattr(refresh.subprocess, "run", run)
    assert refresh.download_latest(root, "owner/repo", "3.14", tmp_path) == "20"
    assert len(requests) == (2 if incompatible == "source" else 3)
    assert downloads[0][:4] == ["gh", "run", "download", "20"]


@pytest.mark.parametrize("problem", ["duplicate", "missing", "malformed"])
def test_latest_validates_reports_before_selecting_a_run(
    history, monkeypatch, capsys, problem,
):
    root, _older, _baseline, descendant = history
    prior = (root / refresh.DURATIONS_PATH).read_bytes()
    downloads = []

    def gh(args):
        if args[0] == "run":
            return [{"databaseId": run_id, "headSha": descendant} for run_id in (30, 20)]
        return [{"artifacts": [
            {"name": f"pytest-output-3.14-{group}", "expired": False}
            for group in range(1, refresh.SHARD_COUNT + 1)
        ]}]

    real_run = subprocess.run

    def run(args, **kwargs):
        if args[0] != "gh":
            return real_run(args, **kwargs)
        downloads.append(args[3])
        _reports(Path(args[-1]), problem if args[3] == "30" else None)
        assert (root / refresh.DURATIONS_PATH).read_bytes() == prior
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(refresh, "_gh", gh)
    monkeypatch.setattr(refresh.subprocess, "run", run)
    from yoke_core.domain import workspace_authority

    monkeypatch.setattr(workspace_authority, "assert_target_under_session_work_authority", lambda _: None)
    assert refresh.main([
        "--target-root", str(root), "--latest", "--repository", "owner/repo",
    ]) == 0
    assert downloads == ["30", "20"]
    output = capsys.readouterr().out
    assert "ci_profile_run_skipped: run 30:" in output
    assert '"source_run_id": "20"' in output
    profile = json.loads((root / refresh.DURATIONS_PATH).read_text())
    assert profile == {f"source.py::test_{group}": 10 for group in range(1, refresh.SHARD_COUNT + 1)}


def test_invalid_retained_reports_preserve_the_committed_profile(history, monkeypatch, capsys):
    root, _older, _baseline, descendant = history
    prior = (root / refresh.DURATIONS_PATH).read_bytes()
    monkeypatch.setattr(refresh, "_gh", lambda args: (
        [{"databaseId": 30, "headSha": descendant}] if args[0] == "run" else
        [{"artifacts": [
            {"name": f"pytest-output-3.14-{group}", "expired": False}
            for group in range(1, refresh.SHARD_COUNT + 1)
        ]}]
    ))
    real_run = subprocess.run

    def run(args, **kwargs):
        if args[0] != "gh":
            return real_run(args, **kwargs)
        _reports(Path(args[-1]), "duplicate")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(refresh.subprocess, "run", run)
    with pytest.raises(ValueError, match="ci_profile_reports_unavailable"):
        refresh.download_latest(root, "owner/repo", "3.14", root / "reports")
    assert (root / refresh.DURATIONS_PATH).read_bytes() == prior
    assert "ci_profile_run_skipped: run 30: ci_profile_duplicate:" in capsys.readouterr().out


def test_no_compatible_source_retains_the_committed_profile(history, monkeypatch):
    root, older, _baseline, _descendant = history
    prior = (root / refresh.DURATIONS_PATH).read_bytes()

    def gh(args):
        assert args[0] == "run", "incompatible artifacts must not be downloaded"
        return [{"databaseId": 30, "headSha": older}]

    monkeypatch.setattr(refresh, "_gh", gh)
    with pytest.raises(ValueError, match="ci_profile_reports_unavailable.*baseline"):
        refresh.download_latest(root, "owner/repo", "3.14", root / "reports")
    assert (root / refresh.DURATIONS_PATH).read_bytes() == prior


def test_missing_profile_history_names_the_explicit_report_recovery(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises(ValueError, match="ci_profile_baseline_missing.*--reports"):
        refresh.profile_baseline(Path(tmp_path))
