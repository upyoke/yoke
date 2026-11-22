"""Exercise release retry against the exact upstream run and attempt."""

import json
import sys

import pytest

from runtime.api.tools.test_promote_main_artifacts import SHA, candidate
from yoke_core.tools import promote_main_artifacts as subject

REPO = "owner/yoke"
TAG = "v0.2.0.202611221412"
WHEELS = "yoke-build-artifacts.yml"
IMAGE = "yoke-server-image.yml"
RELEASE = "yoke-release.yml"
EARLY = "2026-11-22T14:00:00.000000Z"
RECOVERY = "2026-11-22T14:01:00Z"
LATE = "2026-11-22T14:02:00Z"


@pytest.mark.parametrize(
    ("downstream", "upstream", "expected"),
    [
        ({}, {}, True),
        ({"updated_at": LATE, "run_started_at": EARLY}, {}, False),
        ({"updated_at": "2026-11-22T14:01:00.000000Z"}, {}, False),
        ({}, {"conclusion": "failure"}, False),
        ({}, {"status": "in_progress"}, False),
        ({"conclusion": "success"}, {}, False),
        ({"status": "in_progress"}, {}, False),
        ({"updated_at": None}, {}, False),
        ({}, {"updated_at": "invalid"}, False),
    ],
)
def test_stale_failure_uses_completion_after_exact_upstream_recovery(
    downstream, upstream, expected
):
    failed = candidate(**({"updated_at": EARLY, "conclusion": "failure"} | downstream))
    recovered = candidate(**({"updated_at": RECOVERY} | upstream))
    assert subject.stale_failure(failed, recovered) is expected


@pytest.fixture
def factories(monkeypatch, tmp_path):
    def install(*, downstream=None, wait_code=0, refuse=False):
        runs = {
            WHEELS: [candidate(id=10, updated_at=RECOVERY)],
            IMAGE: [
                candidate(id=20, run_attempt=1, updated_at=EARLY, conclusion="failure"),
                candidate(
                    id=40, run_attempt=1, updated_at=EARLY,
                    head_branch=TAG, conclusion="failure",
                ),
                candidate(id=99, head_branch=TAG, head_repository={"full_name": "fork/yoke"}),
            ],
            RELEASE: [
                candidate(
                    id=30, run_attempt=1, updated_at=EARLY,
                    head_branch=TAG, conclusion="failure",
                ),
            ],
        }
        for entries in runs.values():
            for entry in entries:
                entry.update((downstream or {}).get(entry["id"], {}))
        (tmp_path / "runs.json").write_text(json.dumps(runs))
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.setenv("PATH", str(tmp_path), prepend=":")
        monkeypatch.setattr(subject.time, "sleep", lambda _seconds: None)
        fake = tmp_path / "gh"
        fake.write_text(f"#!{sys.executable}\n" + """\
import json
from pathlib import Path
import sys

root = Path(__file__).parent
args = sys.argv[1:]
runs = json.loads((root / "runs.json").read_text())


def find(run_id):
    return next(run for group in runs.values() for run in group if run["id"] == int(run_id))


def log(event, run_id):
    with (root / "calls").open("a") as handle:
        print(event, run_id, file=handle)


if Path(sys.argv[0]).name == "yoke":
    command, action, repo, run_id, project, slug, timeout, seconds = args
    assert (command, action, repo, project, slug, timeout, seconds) == (
        "github-actions", "wait-run", "owner/yoke", "--project", "yoke", "--timeout", "3600",
    )
    log("wait", run_id)
    if WAIT_CODE:
        print("wait produced diagnostic", file=sys.stderr)
        sys.exit(WAIT_CODE)
    find(run_id).update(status="completed", conclusion="success", updated_at="2026-11-22T14:02:00Z")
    (root / "runs.json").write_text(json.dumps(runs))
elif args[:2] == ["run", "rerun"]:
    run_id, flag, repo_flag, repo = args[2:]
    assert (flag, repo_flag, repo) == ("--failed", "--repo", "owner/yoke")
    log("rerun", run_id)
    if REFUSE:
        print("rerun produced diagnostic", file=sys.stderr)
        sys.exit(1)
elif "/workflows/" in args[1]:
    assert "branch=" not in args[1]
    workflow = args[1].split("/workflows/")[1].split("/")[0]
    print(json.dumps({"workflow_runs": runs[workflow]}))
else:
    run_id = args[1].split("/")[-1]
    marker = root / f"poll-{run_id}"
    run = find(run_id)
    log("poll", run_id)
    if marker.exists():
        run["run_attempt"] += 1
    marker.touch()
    print(json.dumps(run))
""".replace("WAIT_CODE", str(wait_code)).replace("REFUSE", str(refuse)))
        fake.chmod(0o755)
        (tmp_path / "yoke").symlink_to(fake)
        return tmp_path / "calls"

    return install


def retry():
    return subject.main(["rerun-stale", "--repo", REPO, "--source-sha", SHA, "--tag", TAG])


def test_incident_retry_reruns_and_waits_in_dependency_order(factories):
    calls = factories()
    assert retry() == 0
    assert calls.read_text().splitlines() == [
        f"{action} {run_id}"
        for run_id in (20, 30, 40)
        for action in ("rerun", "poll", "poll", "wait")
    ]


def test_retry_leaves_current_failures_green_and_in_flight_runs_alone(factories):
    calls = factories(downstream={
        20: {"conclusion": "success", "updated_at": EARLY},
        30: {"updated_at": LATE},
        40: {"status": "in_progress", "conclusion": None},
    })
    assert retry() == 0
    assert not calls.exists()


def test_retry_leaves_failures_alone_when_the_root_factory_is_down(factories):
    calls = factories(downstream={10: {"conclusion": "failure"}})
    assert retry() == 0
    assert not calls.exists()


@pytest.mark.parametrize("wait_code", [1, 3, 4])
def test_wait_failure_or_timeout_stops_the_edge_walk(factories, capfd, wait_code):
    calls = factories(wait_code=wait_code)
    assert retry() == (0 if wait_code == 3 else 1)
    assert calls.read_text().splitlines() == ["rerun 20", "poll 20", "poll 20", "wait 20"]
    output = capfd.readouterr()
    assert "wait produced diagnostic" in output.err
    if wait_code == 3:
        assert "still in flight" in output.out
    else:
        assert f"wait exited {wait_code}" in output.err


def test_rerun_refusal_keeps_gh_diagnostic(factories, capfd):
    calls = factories(refuse=True)
    assert retry() == 1
    assert calls.read_text().splitlines() == ["rerun 20"]
    assert "rerun produced diagnostic" in capfd.readouterr().err
