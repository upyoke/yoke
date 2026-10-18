"""Valid reads bypass locks; refresh proof precedes serialization."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import timedelta
import fcntl
import json
import os
from threading import Event
from types import SimpleNamespace

import pytest

from yoke_cli.config import github_git_credential_file as credential_file
from yoke_cli.config import github_git_credential_helper as git_helper
from yoke_cli.config import github_git_credential_store as store
from yoke_cli.config import github_local_user_access, github_machine_operation
from yoke_cli.config import machine_config
from yoke_cli.config import github_binding_auth
from yoke_cli.config import writer

from .github_user_token_test_support import NOW, FakeResponse, configured_credential
from .github_binding_test_support import _two_service_config


def _service_config(config):
    payload = json.loads(config.read_text())
    payload["active_env"] = "service"
    payload["connections"] = {
        "service": {
            "transport": "https",
            "api_url": "https://service.example/v1",
            "credential_source": {"kind": "token_file", "path": "/unused"},
        }
    }
    payload["github"].update(
        profile_source="service", profile_service_api_url="https://service.example/v1"
    )
    config.write_text(json.dumps(payload))


def test_concurrent_valid_git_and_local_reads_ignore_held_locks(tmp_path, monkeypatch):
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config, credential = configured_credential(
        tmp_path, expires_at=NOW + timedelta(hours=1)
    )
    _service_config(config)
    monkeypatch.setattr(
        store.credential_document.clock_contract, "utc_now", lambda: NOW
    )

    def refuse(*args, **kwargs):
        raise AssertionError("valid reads must make no profile or refresh request")

    monkeypatch.setattr(store.github_service_profile_proof, "prove", refuse)
    with ExitStack() as stack:
        for target in (github_machine_operation.operation_lock_target(), credential):
            descriptor = os.open(
                credential_file.lock_path(target), os.O_CREAT | os.O_RDWR, 0o600
            )
            stack.callback(os.close, descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = []
            for _ in range(2):
                futures.append(
                    pool.submit(
                        git_helper.access_token_for_git_request,
                        config,
                        {"protocol": "https", "host": "github.com"},
                        opener=refuse,
                    )
                )
                futures.append(
                    pool.submit(
                        github_local_user_access.access_token,
                        config,
                        now=NOW,
                        opener=refuse,
                        profile_opener=refuse,
                    )
                )
            results = [future.result(timeout=1) for future in futures]
    assert [
        r["access_token"] if isinstance(r, dict) else r.access_token for r in results
    ] == ["stored-access"] * 4


def test_concurrent_refresh_proves_outside_lock_and_reuses_first_result(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config, _ = configured_credential(tmp_path, expires_at=NOW)
    _service_config(config)
    proofs_ready = Event()
    refresh_started = Event()
    second_lock_attempted = Event()
    proof_count = []
    refresh_count = []
    lock_count = []
    real_lock = store.machine_operation_lock

    def prove(*args, **kwargs):
        assert not getattr(github_machine_operation._LOCAL, "depth", 0)
        proof_count.append(True)
        if len(proof_count) == 2:
            proofs_ready.set()
        assert proofs_ready.wait(2)

    @contextmanager
    def observed_lock(path):
        lock_count.append(True)
        if len(lock_count) == 2:
            assert refresh_started.wait(2)
            second_lock_attempted.set()
        with real_lock(path):
            yield

    def refresh(request, timeout):
        refresh_count.append(True)
        refresh_started.set()
        assert second_lock_attempted.wait(2)
        return FakeResponse(
            {
                "access_token": "new-access",
                "expires_in": 28800,
                "refresh_token": "new-refresh",
                "refresh_token_expires_in": 15552000,
            }
        )

    monkeypatch.setattr(store.github_service_profile_proof, "prove", prove)
    monkeypatch.setattr(store, "machine_operation_lock", observed_lock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                store.access_token_from_machine_config, config, now=NOW, opener=refresh
            )
            for _ in range(2)
        ]
        tokens = [future.result(timeout=4) for future in futures]
    assert refresh_count == [True]
    assert [token["access_token"] for token in tokens] == ["new-access", "new-access"]
    assert sorted(token["cached"] for token in tokens) == [False, True]


def test_binding_proof_and_valid_token_read_do_not_hold_machine_lock(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config, _ = configured_credential(tmp_path, expires_at=NOW + timedelta(hours=1))
    monkeypatch.setattr(
        store.credential_document.clock_contract, "utc_now", lambda: NOW
    )
    phases = []
    real_config_lock = github_binding_auth.machine_config_file.exclusive_lock

    def prove(github, **kwargs):
        phases.append("proof")
        assert not getattr(github_machine_operation._LOCAL, "depth", 0)
        return SimpleNamespace(**github)

    @contextmanager
    def config_lock(path):
        assert phases == ["proof"]
        with real_config_lock(path):
            phases.append("binding-write")
            yield

    monkeypatch.setattr(
        github_binding_auth.github_app_public_profile,
        "resolve_selected_and_match",
        prove,
    )
    monkeypatch.setattr(
        github_binding_auth.machine_config_file, "exclusive_lock", config_lock
    )
    with github_machine_operation.operation_lock(config):
        # Holding a lock in this thread would use its reentrant fast path;
        # the actual binding read runs on another thread.
        def bind():
            with github_binding_auth.locked_profile_bound_access_for_binding(
                config
            ) as authority:
                assert authority.token.access_token == "stored-access"

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(bind).result(timeout=1)
    assert phases == ["proof", "binding-write"]


def test_connection_change_does_not_take_github_machine_lock(tmp_path, monkeypatch):
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    config = _two_service_config(tmp_path)
    with github_machine_operation.operation_lock(config):
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(
                writer.set_active_env, "service-b", path=config
            ).result(timeout=1)
    assert result["active_env"] == "service-b"


def test_lock_wait_notice_starts_after_two_seconds(tmp_path, monkeypatch):
    notices = []
    clock = iter([0, 0, 0.05, 1.9, 2.0, 2.5, 3.0])
    current_time = 0

    def monotonic():
        nonlocal current_time
        current_time = next(clock)
        return current_time

    monkeypatch.setattr(
        credential_file,
        "announce_designed_wait",
        lambda *args, **kwargs: notices.append(current_time),
    )

    def busy(*args):
        raise BlockingIOError()

    monkeypatch.setattr(
        credential_file.platform_file_lock,
        "acquire_exclusive_nonblocking",
        busy,
    )
    with pytest.raises(credential_file.CredentialFileBusy):
        credential_file._wait_for_exclusive_lock(
            0,
            tmp_path / "lock",
            wait_seconds=3,
            sleep=lambda _: None,
            monotonic=monotonic,
        )
    assert notices == [2.0]
