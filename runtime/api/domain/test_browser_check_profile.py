"""Private sign-in copies, sequence reuse, permissions and orphan cleanup."""

import json
import os
from types import SimpleNamespace

import pytest

from yoke_harness import browser_check_profile as checks
from yoke_harness import browser_client
from yoke_harness.browser_daemon_profile import selected_profile


@pytest.fixture()
def profiles(tmp_path, monkeypatch):
    source = tmp_path / "authoritative"
    source.mkdir()
    (source / "Cookies").write_bytes(b"synthetic-sign-in")
    (source / "Local Storage").mkdir()
    (source / "Local Storage" / "state").write_bytes(b"synthetic-storage")
    (source / "SingletonLock").symlink_to("not-a-profile-file")
    (source / "secret-outside-profile").symlink_to(tmp_path / "outside")
    monkeypatch.setattr(
        checks.machine_config, "yoke_home", lambda: tmp_path / "machine"
    )
    monkeypatch.setattr(
        checks, "resolve_authorized_profile", lambda *a, **k: (source, "authorized")
    )
    monkeypatch.setattr(browser_client, "_browser_dir", lambda: tmp_path / "runtime")
    stopped = []
    monkeypatch.setattr(
        browser_client, "daemon_stop", lambda **kw: stopped.append(kw["profile_dir"])
    )
    return source, stopped


def test_copy_preserves_sign_in_and_storage_and_deletes_only_private_copy(profiles):
    source, stopped = profiles
    with checks.check_scope("fixture", "admin") as check:
        profile = check.profile
        assert profile != source
        assert selected_profile() == str(profile)
        assert (profile / "Cookies").read_bytes() == b"synthetic-sign-in"
        assert (
            profile / "Local Storage" / "state"
        ).read_bytes() == b"synthetic-storage"
        assert not (profile / "SingletonLock").exists()
        assert not (profile / "secret-outside-profile").is_symlink()
        assert profile.stat().st_mode & 0o777 == 0o700
        assert (profile / "Cookies").stat().st_mode & 0o777 == 0o600
        (profile / "Cookies").write_bytes(b"check-only-rotation")
    assert not check.directory.exists()
    assert source.joinpath("Cookies").read_bytes() == b"synthetic-sign-in"
    assert stopped == []


def test_sequence_reuses_its_own_copy_then_final_call_deletes_it(profiles, monkeypatch):
    source, stopped = profiles
    states = {}
    monkeypatch.setattr(
        browser_client.DaemonState,
        "load",
        lambda path=None: states.get(str(path or browser_client._state_file_path())),
    )
    monkeypatch.setattr(browser_client, "daemon_running", lambda state: True)
    with checks.check_scope("fixture", "admin", keep_open=True) as first:
        states[str(browser_client._state_file_path())] = SimpleNamespace(
            pid=os.getpid()
        )
        (first.profile / "Cookies").write_bytes(b"sequence-state")
    assert first.directory.exists()
    with checks.check_scope("fixture", "admin") as independent:
        assert independent.profile != first.profile
        assert (independent.profile / "Cookies").read_bytes() == b"synthetic-sign-in"
    with checks.check_scope("fixture", "admin", check_id=first.check_id) as resumed:
        assert resumed.profile == first.profile
        assert (resumed.profile / "Cookies").read_bytes() == b"sequence-state"
    assert stopped == [str(first.profile)]
    assert not first.directory.exists()
    assert source.exists()


def test_failure_removes_private_copy(profiles):
    with pytest.raises(RuntimeError, match="step failed"):
        with checks.check_scope("fixture") as check:
            raise RuntimeError("step failed")
    assert not check.directory.exists()


def test_dead_owner_is_swept_without_probing_authoritative_daemon(profiles):
    source, stopped = profiles
    with checks.check_scope("fixture", "admin") as check:
        record_path = check.directory / "owner.json"
        record = json.loads(record_path.read_text())
        record["owner"] = {"pid": 999999999, "start": "gone"}
        record_path.write_text(json.dumps(record))
        checks.sweep_checks()
        assert not check.directory.exists()
    assert source.is_dir()
    assert stopped == []


def test_wrong_identity_cannot_close_another_check(profiles, monkeypatch):
    monkeypatch.setattr(
        browser_client.DaemonState, "load", lambda *a: SimpleNamespace(pid=os.getpid())
    )
    monkeypatch.setattr(browser_client, "daemon_running", lambda state: True)
    with checks.check_scope("fixture", "admin", keep_open=True) as check:
        pass
    with pytest.raises(RuntimeError, match="browser_check_identity_mismatch"):
        with checks.check_scope("other", "admin", check_id=check.check_id):
            pytest.fail("foreign check must refuse")
    assert check.directory.exists()
    with checks.check_scope("fixture", "admin", check_id=check.check_id):
        pass
    assert not check.directory.exists()


@pytest.mark.parametrize(
    "check_id", ["", "invalid", "../outside", "00000000-0000-0000-0000-000000000000"]
)
def test_unknown_check_names_recovery(profiles, check_id):
    with pytest.raises(RuntimeError, match="browser_check_unavailable"):
        with checks.check_scope("fixture", check_id=check_id):
            pytest.fail("unknown check must refuse")


def test_cleanup_deletes_copy_when_daemon_exits_during_stop(profiles, monkeypatch):
    monkeypatch.setattr(
        browser_client.DaemonState, "load", lambda *a: SimpleNamespace(pid=os.getpid())
    )
    monkeypatch.setattr(browser_client, "daemon_running", lambda state: True)

    def already_exited(**kwargs):
        raise RuntimeError("daemon not running")

    monkeypatch.setattr(browser_client, "daemon_stop", already_exited)
    with checks.check_scope("fixture") as check:
        checks.record_daemon_owner(str(check.profile), os.getpid())
        assert check.profile.is_dir()
    assert not check.directory.exists()


def test_unavailable_owner_refuses_without_publishing_a_copy(profiles, monkeypatch):
    source, stopped = profiles
    monkeypatch.setattr(checks, "process_start_time", lambda pid: None)
    with pytest.raises(RuntimeError, match="browser_check_owner_unavailable"):
        with checks.check_scope("fixture"):
            pytest.fail("an unowned copy must never be used")
    assert not list(checks._root().iterdir())
    assert source.is_dir()
    assert stopped == []


def test_reused_daemon_pid_never_stops_the_replacement_process(profiles, monkeypatch):
    source, stopped = profiles
    with checks.check_scope("fixture") as check:
        record = json.loads((check.directory / "owner.json").read_text())
        record["daemon"] = {"pid": os.getpid(), "start": "previous-process"}
        checks._write_record(check, record)
        monkeypatch.setattr(
            browser_client.DaemonState,
            "load",
            lambda *a: SimpleNamespace(pid=os.getpid()),
        )
        monkeypatch.setattr(browser_client, "daemon_running", lambda state: True)
    assert stopped == []
    assert not check.directory.exists()
    assert source.is_dir()


def test_unproven_live_daemon_is_preserved_until_idle_exit(profiles, monkeypatch):
    with pytest.raises(RuntimeError, match="browser_check_owner_unavailable"):
        with checks.check_scope("fixture") as check:
            monkeypatch.setattr(
                browser_client.DaemonState,
                "load",
                lambda *a: SimpleNamespace(pid=os.getpid()),
            )
            monkeypatch.setattr(browser_client, "daemon_running", lambda state: True)
    assert check.directory.exists()
    assert profiles[1] == []
    monkeypatch.setattr(browser_client, "daemon_running", lambda state: False)
    checks._remove(check)
    assert not check.directory.exists()


def test_daemon_birth_token_is_recorded_before_readiness(
    profiles, monkeypatch, tmp_path
):
    from unittest.mock import Mock
    from yoke_harness import browser_client_readiness as readiness

    process = SimpleNamespace(pid=os.getpid(), kill=Mock(), wait=Mock())
    monkeypatch.setattr(readiness, "launch_daemon", lambda *a: process)
    with checks.check_scope("fixture") as check:

        def ready(*args, **kwargs):
            record = json.loads((check.directory / "owner.json").read_text())
            assert record["daemon"] == checks._owner(process.pid)
            return {"pid": process.pid, "status": "started"}

        monkeypatch.setattr(readiness, "wait_for_daemon_ready", ready)
        result = readiness.start_daemon(
            ["node"], {}, tmp_path / "runtime-state", profile_dir=str(check.profile)
        )
        assert result["pid"] == process.pid
    process.kill.assert_not_called()


def test_failed_daemon_owner_record_stops_only_the_new_child(
    profiles, monkeypatch, tmp_path
):
    from unittest.mock import Mock
    from yoke_harness import browser_client_readiness as readiness

    process = SimpleNamespace(pid=42, kill=Mock(), wait=Mock())
    monkeypatch.setattr(readiness, "launch_daemon", lambda *a: process)
    ready = Mock()
    monkeypatch.setattr(readiness, "wait_for_daemon_ready", ready)
    with pytest.raises(RuntimeError, match="browser_check_owner_unavailable"):
        with checks.check_scope("fixture") as check:

            def unavailable(pid):
                raise RuntimeError(
                    "browser_check_owner_unavailable: process query failed"
                )

            monkeypatch.setattr(checks, "_owner", unavailable)
            readiness.start_daemon(
                ["node"], {}, tmp_path / "runtime-state", profile_dir=str(check.profile)
            )
    process.kill.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=5)
    ready.assert_not_called()
    assert not check.directory.exists()
