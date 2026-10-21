"""Automatic timing refresh cannot undo a committed fixture-cost reset."""

from pathlib import Path
import subprocess

import pytest

from yoke_core.tools import ci_durations_refresh as refresh


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
            return subprocess.CompletedProcess(args, 0)
        return real_run(args, **kwargs)

    monkeypatch.setattr(refresh, "_gh", gh)
    monkeypatch.setattr(refresh.subprocess, "run", run)
    assert refresh.download_latest(root, "owner/repo", "3.14", tmp_path) == "20"
    assert len(requests) == (2 if incompatible == "source" else 3)
    assert downloads[0][:4] == ["gh", "run", "download", "20"]


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
