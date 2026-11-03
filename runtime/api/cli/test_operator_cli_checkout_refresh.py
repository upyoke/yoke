"""Relay release following refreshes checkouts and teaches local failures."""

import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config import operator_cli_release_follow as follow
from yoke_cli.config import session_relay_instance
from yoke_cli.commands.adapters import steering_report
from yoke_core.domain import global_orientation, session_orientation


def _checkout(tmp_path, name, mode="copy"):
    root = tmp_path / name
    (root / ".yoke").mkdir(parents=True)
    (root / ".yoke/install-manifest.json").write_text(
        json.dumps({"manifest_schema": 1, "mode": mode, "files": {}})
    )
    return root


def _mapped(monkeypatch, roots):
    monkeypatch.setattr(
        follow.machine_config, "load_config", lambda: {"active_env": "prod"}
    )
    monkeypatch.setattr(
        follow, "mapped_checkouts", lambda _: [(str(p), 1) for p in roots]
    )


def test_updated_release_refreshes_all_checkouts_and_records_failures(
    tmp_path, monkeypatch, capsys
):
    clean = _checkout(tmp_path, "clean")
    dirty = _checkout(tmp_path, "dirty")
    _mapped(monkeypatch, [clean, dirty])
    yoke = tmp_path / "yoke"
    yoke.touch()
    versions = iter(["1.0.0", "1.0.1"])
    calls = []
    env = {"PATH": "/usr/bin"}
    monkeypatch.setattr(follow, "strip_relay_owned_python_state", lambda: env)
    monkeypatch.setattr(follow.self_update, "resolve_target", lambda **_: "target")
    monkeypatch.setattr(follow.self_update, "install_release", lambda *a, **k: None)

    def run(argv, **kwargs):
        assert kwargs["env"] == env
        if argv[1] == "--version":
            return subprocess.CompletedProcess(argv, 0, next(versions))
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, int(argv[3] == str(dirty)), "{}", "checkout_dirty: commit changes"
        )

    record = follow.follow_release("1.0.1", tmp_path, executable=yoke, run=run)
    assert record["outcome"] == "updated"
    assert calls == [
        [str(yoke), "project", "refresh", str(root), "--json"]
        for root in (clean, dirty)
    ]
    stored = json.loads((tmp_path / follow.FOLLOW_RECORD_NAME).read_text())
    ok, failed = stored["project_refresh"]
    assert ok["status"] == "refreshed" and ok["path"] == str(clean)
    assert failed["status"] == "failed" and failed["path"] == str(dirty)
    assert "checkout_dirty" in failed["reason"]
    assert failed["recovery"] == f"yoke project install {dirty}"
    assert follow._refresh_line(failed) in capsys.readouterr().err


@pytest.mark.parametrize(
    "failure",
    [
        3,
        RuntimeError("refresh_crashed"),
        "bad-json",
        subprocess.TimeoutExpired("refresh", 600),
    ],
)
def test_current_release_records_failures_and_skips_source_checkouts(
    tmp_path, monkeypatch, failure
):
    failed = _checkout(tmp_path, "failed")
    source = _checkout(tmp_path, "source", "source-link")
    clean = _checkout(tmp_path, "clean")
    missing = tmp_path / "missing"
    _mapped(monkeypatch, [failed, source, missing, clean])
    yoke = tmp_path / "yoke"
    yoke.touch()
    calls = []

    def run(argv, **kwargs):
        if argv[1] == "--version":
            return subprocess.CompletedProcess(argv, 0, "1.0.1")
        calls.append(argv)
        if argv[3] == str(failed):
            if isinstance(failure, Exception):
                raise failure
            return subprocess.CompletedProcess(
                argv, 3 if failure == 3 else 0, "unreadable", "publish_pending"
            )
        return subprocess.CompletedProcess(argv, 0, "{}")

    record = follow.follow_release("1.0.1", tmp_path, executable=yoke, run=run)
    assert record["outcome"] == "current"
    assert [r["status"] for r in record["project_refresh"]] == [
        "failed",
        "skipped",
        "skipped",
        "refreshed",
    ]
    assert [call[3] for call in calls] == [str(failed), str(clean)]
    assert record["project_refresh"][0]["recovery"] == f"yoke project install {failed}"


def _record(monkeypatch, tmp_path, count):
    _mapped(monkeypatch, [])
    monkeypatch.setattr(
        session_relay_instance,
        "resolve_relay_instance",
        lambda **_: SimpleNamespace(state_dir=tmp_path),
    )
    rows = [
        {
            "path": str(tmp_path / f"project-{i}"),
            "status": "failed",
            "reason": "checkout_dirty",
            "recovery": f"yoke project install project-{i}",
        }
        for i in range(count)
    ]
    target = tmp_path / follow.FOLLOW_RECORD_NAME
    target.write_text(json.dumps({"project_refresh": rows}))
    monkeypatch.setattr(
        follow.operating_layer_drift, "stale_installed_layer", lambda _: True
    )
    return target, rows


def test_failure_reader_filters_repaired_checkouts_and_bounds_output(
    tmp_path, monkeypatch
):
    target, rows = _record(monkeypatch, tmp_path, 7)
    lines = follow.refresh_skip_lines()
    assert lines[:5] == [follow._refresh_line(row) for row in rows[:5]]
    assert len(lines) == 6 and "2 more" in lines[-1] and str(target) in lines[-1]
    monkeypatch.setattr(
        follow.operating_layer_drift,
        "stale_installed_layer",
        lambda root: root == Path(rows[1]["path"]),
    )
    assert follow.refresh_skip_lines() == [follow._refresh_line(rows[1])]


def test_refresh_notice_keeps_multiline_refusals_on_one_line():
    line = follow._refresh_line(
        {
            "path": "/checkout",
            "reason": "checkout_dirty:\n commit changes",
            "recovery": "yoke project install /checkout",
        }
    )
    assert line.splitlines() == [line]
    assert "checkout_dirty: commit changes" in line


@pytest.mark.parametrize("contents", [None, "{", '{"project_refresh": null}'])
def test_failure_reader_never_raises_for_missing_or_unreadable_records(
    tmp_path, monkeypatch, contents
):
    target, _ = _record(monkeypatch, tmp_path, 0)
    if contents is None:
        target.unlink()
    else:
        target.write_text(contents)
    assert follow.refresh_skip_lines() == []


def test_all_local_orientation_and_steering_surfaces_show_failures(
    tmp_path, monkeypatch
):
    _, rows = _record(monkeypatch, tmp_path, 2)
    lines = [follow._refresh_line(row) for row in rows]
    monkeypatch.setattr(session_orientation, "_operating_layer_advisory", lambda _: "")
    monkeypatch.setattr(session_orientation, "_git_line", lambda *_: "")
    monkeypatch.setattr(session_orientation, "_startup_block_lines", lambda: [])
    from yoke_core.domain import main_agent_packet

    monkeypatch.setattr(main_agent_packet, "render_install_advisory_block", lambda: "")
    monkeypatch.setattr(
        main_agent_packet, "render_interpreter_advisory_block", lambda: ""
    )
    project = session_orientation.render_orientation(
        {"session_id": "session"}, tmp_path / "unrelated"
    )
    outside = global_orientation.render_global_orientation(
        "session", tmp_path, setup_lines=[]
    )
    for output in (project, outside):
        for line in lines:
            assert line in output
    for writer in (steering_report._print_report, steering_report._print_full_report):
        stream = io.StringIO()
        writer(SimpleNamespace(result={"body": "server report"}), stream, io.StringIO())
        assert stream.getvalue().startswith("server report\n")
        for line in lines:
            assert line in stream.getvalue()
