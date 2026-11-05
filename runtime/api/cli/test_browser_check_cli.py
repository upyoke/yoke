"""Private-check setup and multi-call browser sequences."""

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_cli.commands.qa_browser_lifecycle import qa_browser_setup

pytestmark = pytest.mark.usefixtures("bound_project_context")


def test_setup_start_passes_daemon_options(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    @contextmanager
    def scope(*args, **kwargs):
        yield SimpleNamespace(profile=tmp_path / "private", check_id="opaque")

    monkeypatch.setattr("yoke_harness.browser_check_profile.check_scope", scope)
    provisioned = [{"action": "provision-node", "source": "managed"}]
    with (
        patch(
            "yoke_harness.browser_runtime_home.ensure_materialized",
            return_value=Path("/machine/browser-runtime"),
        ),
        patch(
            "yoke_cli.commands.qa_browser_lifecycle._ensure_node_toolchain",
            return_value=provisioned,
        ),
        patch(
            "yoke_cli.commands.qa_browser_lifecycle._browser_readiness",
            return_value={"daemon": {"status": "not_running"}},
        ),
        patch(
            "yoke_harness.browser_client.daemon_start",
            return_value={"status": "started", "pid": 123},
        ) as daemon_start,
    ):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = qa_browser_setup(
                [
                    "--port",
                    "9876",
                    "--headed",
                    "--idle-timeout",
                    "60",
                    "--json",
                ]
            )

    assert rc == 0
    daemon_start.assert_called_once_with(
        profile_dir=str(tmp_path / "private"),
        port=9876,
        headed=True,
        idle_timeout=60_000,
    )
    payload = json.loads(out.getvalue())
    assert payload["check_id"] == "opaque"
    assert payload["prerequisite_actions"] == provisioned
    assert payload["daemon"]["status"] == "started"


def test_step_sequence_routes_private_state_until_final_call(
    tmp_path, monkeypatch, capsys
):
    import os
    from yoke_cli.commands.qa_browser import qa_browser_step
    from yoke_harness import browser_client, browser_check_profile

    monkeypatch.setattr(
        browser_check_profile.machine_config, "yoke_home", lambda: tmp_path
    )
    monkeypatch.setattr(
        browser_check_profile,
        "resolve_authorized_profile",
        lambda *a, **k: (None, "clean"),
    )
    monkeypatch.setattr(browser_client, "_browser_dir", lambda: tmp_path / "runtime")
    started = []
    stopped = []

    def start(*, profile_dir):
        started.append(profile_dir)
        state_path = browser_client._state_file_path(profile_dir)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"pid": os.getpid(), "profileDir": profile_dir})
        )
        return {"status": "started"}

    monkeypatch.setattr(browser_client, "daemon_start", start)
    monkeypatch.setattr(
        browser_client, "daemon_stop", lambda **kw: stopped.append(kw["profile_dir"])
    )
    monkeypatch.setattr(browser_client, "ensure_page", lambda name: name)
    monkeypatch.setattr(
        browser_client, "execute_step", lambda *a, **k: {"success": True}
    )
    args = [
        "--project",
        "fixture",
        "--identity",
        "admin",
        "--base-url",
        "https://example.test",
        "--step-json",
        "{}",
    ]
    assert qa_browser_step([*args, "--keep-open"]) == 0
    check_id = json.loads(capsys.readouterr().out)["check_id"]
    copy = Path(started[0])
    assert copy.is_dir()
    assert qa_browser_step([*args, "--check-id", check_id, "--keep-open"]) == 0
    assert json.loads(capsys.readouterr().out)["check_id"] == check_id
    assert qa_browser_step([*args, "--check-id", check_id]) == 0
    assert "check_id" not in json.loads(capsys.readouterr().out)
    assert started == [str(copy)] * 3
    assert stopped == [str(copy)]
    assert not copy.parent.exists()


@pytest.mark.parametrize("operation", ["step", "screenshot", "stop"])
def test_invalid_identity_names_recovery_without_traceback(operation, capsys):
    from yoke_cli.commands.qa_browser import qa_browser_step, qa_browser_screenshot
    from yoke_cli.commands.qa_browser_stop import qa_browser_stop

    adapter, arguments = {
        "step": (
            qa_browser_step,
            ["--base-url", "https://example.test", "--step-json", "{}"],
        ),
        "screenshot": (
            qa_browser_screenshot,
            ["https://example.test", "--output", "/tmp/unused.png"],
        ),
        "stop": (qa_browser_stop, ["--check-id", "unused"]),
    }[operation]
    assert (
        adapter([*arguments, "--project", "fixture", "--identity", "../invalid"]) == 1
    )
    assert "browser_identity" in capsys.readouterr().err


def test_status_inspects_only_the_named_private_check(monkeypatch, capsys):
    from contextlib import contextmanager
    from yoke_cli.commands.qa_browser_lifecycle import qa_browser_status
    from yoke_harness import browser_client

    @contextmanager
    def scope(project, identity, *, check_id, keep_open):
        assert (project, identity, check_id, keep_open) == (
            "fixture",
            "admin",
            "opaque",
            True,
        )
        yield

    monkeypatch.setattr("yoke_harness.browser_check_profile.check_scope", scope)
    monkeypatch.setattr(
        "yoke_cli.commands.qa_browser_lifecycle._browser_readiness",
        lambda *a, **k: {"daemon": {"status": "not_running"}},
    )
    monkeypatch.setattr(
        browser_client, "daemon_status", lambda: {"status": "running", "pid": 42}
    )
    assert (
        qa_browser_status(
            [
                "--project",
                "fixture",
                "--identity",
                "admin",
                "--check-id",
                "opaque",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["daemon"] == {"status": "running", "pid": 42}
    assert result["check_id"] == "opaque"


def test_default_status_never_probes_the_authoritative_daemon(monkeypatch, capsys):
    from unittest.mock import Mock
    from yoke_cli.commands.qa_browser_lifecycle import qa_browser_status
    from yoke_harness import browser_client

    status = Mock(
        side_effect=AssertionError("shared identity daemon must not be probed")
    )
    monkeypatch.setattr(browser_client, "daemon_status", status)
    assert qa_browser_status(["--project", "fixture", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert "--check-id" in result["daemon"]["detail"]
    status.assert_not_called()


def test_blank_status_check_id_refuses_instead_of_inspecting_another_browser(capsys):
    from yoke_cli.commands.qa_browser_lifecycle import qa_browser_status

    assert qa_browser_status(["--project", "fixture", "--check-id", ""]) == 2
    assert "browser_check_unavailable" in capsys.readouterr().err
