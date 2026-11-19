"""A call routed to a named connection runs under that connection's locality.

The router marks a whole invocation remote when the *active* connection is
https. Project uninstall asks the connection that owns the checkout for its
default branch; when that owner is a local postgres connection, the lookup
dispatches in-process and opens the database directly, so it must not inherit
the active connection's remote mark (feedback 97693).
"""

from __future__ import annotations

import os

import pytest

from yoke_contracts.control_plane_locality import (
    PG_DSN_ENV,
    PG_DSN_FILE_ENV,
    refuse_direct_connection,
    remote_control_plane,
    remote_control_plane_active,
)
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.harness_folder_trust_grant import grant_folder_trust
from yoke_contracts.testing.real_home_isolation import set_home
from yoke_cli.config import project_onboard_support, writer
from yoke_cli.project_install import owned_cleanup
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install.uninstall import uninstall
from yoke_core.domain import yoke_function_dispatch
from yoke_core.domain.project_install_test_helpers import make_bundle
from runtime.api.cli.project_uninstall_test_support import git


@pytest.fixture
def hosted_active_local_owner(tmp_path, monkeypatch):
    """A checkout registered on postgres ``local`` while https ``hosted`` is active."""
    for name in (PG_DSN_ENV, PG_DSN_FILE_ENV, "YOKE_ENV"):
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    set_home(monkeypatch, home)
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    launcher = home / "bin/yoke"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o700)
    monkeypatch.setenv("PATH", str(launcher.parent) + os.pathsep + os.environ["PATH"])
    config = tmp_path / "machine/config.json"
    writer.set_connection(
        "local", transport="local-postgres", dsn="postgresql://fixture.invalid/yoke", path=config
    )
    writer.set_connection(
        "hosted",
        transport="https",
        api_url="https://hosted.invalid",
        token="fixture-only",
        path=config,
    )
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "maintenance.auto", "false")
    git(root, "config", "gc.auto", "0")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.com")
    monkeypatch.setenv("YOKE_ENV", "local")
    bundle = make_bundle()
    bundle["project_id"] = 1
    apply_bundle(root, bundle, source="fixture")
    writer.register_project(root, 1, path=config)
    owned_cleanup.record_registration(root, 1, config)
    grant_folder_trust(root)
    git(root, "add", "-A")
    git(root, "commit", "--no-verify", "-m", "Fixture install")
    monkeypatch.delenv("YOKE_ENV")
    writer.set_active_env("hosted", path=config)
    return root, config


def test_uninstall_reaches_the_local_owner_in_process_under_a_remote_mark(
    hosted_active_local_owner, monkeypatch
):
    root, config = hosted_active_local_owner
    looked_up = []

    def engine_dispatch(request):
        # The in-process engine opens the owner's database first thing.
        refuse_direct_connection("db_backend.connect()")
        looked_up.append((request.function, os.environ.get("YOKE_ENV")))
        return FunctionCallResponse(
            request_id=request.request_id,
            function=request.function,
            version="1",
            success=True,
            result={"value": "main"},
        )

    monkeypatch.setattr(yoke_function_dispatch, "dispatch", engine_dispatch)
    with remote_control_plane():  # the router's mark for an https active connection
        report = uninstall(root, config_path=config)
        assert remote_control_plane_active()
    assert looked_up == [("projects.get", "local")]
    assert report["outcome"] == "complete", report
    assert not report["warnings"], report["warnings"]


def test_a_named_https_owner_keeps_the_remote_mark(
    hosted_active_local_owner, monkeypatch
):
    _root, config = hosted_active_local_owner
    writer.set_active_env("local", path=config)
    observed = []

    def call_dispatcher(**kwargs):
        observed.append((os.environ.get("YOKE_ENV"), remote_control_plane_active()))
        return FunctionCallResponse(
            request_id="r", function=kwargs["function_id"], version="1",
            success=True, result={},
        )

    monkeypatch.setattr(project_onboard_support, "call_dispatcher", call_dispatcher)
    assert not remote_control_plane_active()
    project_onboard_support.dispatch("projects.get", {}, config, env="hosted")
    assert observed == [("hosted", True)]
    assert not remote_control_plane_active()


def test_the_invocation_mark_is_restored_when_the_call_raises(
    hosted_active_local_owner, monkeypatch
):
    _root, config = hosted_active_local_owner

    def call_dispatcher(**_kwargs):
        assert not remote_control_plane_active()
        raise RuntimeError("engine failed")

    monkeypatch.setattr(project_onboard_support, "call_dispatcher", call_dispatcher)
    with remote_control_plane():
        with pytest.raises(RuntimeError, match="engine failed"):
            project_onboard_support.dispatch("projects.get", {}, config, env="local")
        assert remote_control_plane_active()
    assert os.environ.get("YOKE_ENV") is None


def test_orchestrated_uninstall_with_a_dirty_lane_refuses_by_name(
    hosted_active_local_owner, monkeypatch, capsys
):
    """`yoke uninstall` runs this exact command; it must refuse, not crash."""
    from yoke_cli.commands.adapters.install import project_uninstall

    root, config = hosted_active_local_owner
    lane = root / ".worktrees/WALKNE-1"
    git(root, "worktree", "add", "-b", "WALKNE-1", str(lane))
    (lane / "wordcount.py").write_text("print('work')\n")
    head = git(root, "rev-parse", "HEAD")

    def engine_dispatch(request):
        refuse_direct_connection("db_backend.connect()")
        return FunctionCallResponse(
            request_id=request.request_id, function=request.function,
            version="1", success=True, result={"value": "main"},
        )

    monkeypatch.setattr(yoke_function_dispatch, "dispatch", engine_dispatch)
    args = [str(root), "--config", str(config), "--remove-lanes", "--json"]
    with remote_control_plane():
        assert project_uninstall(args) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: project_uninstall_lane_dirty: ")
    assert "Traceback" not in err
    assert git(root, "rev-parse", "HEAD") == head
    assert (lane / "wordcount.py").is_file()
