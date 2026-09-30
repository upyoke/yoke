"""Self-host root bootstrap and runtime secret permission contract."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from yoke_contracts.self_host_bootstrap import (
    IMPORT_UNIVERSE_ARG,
    RECOVER_IMPORT_CREDENTIAL_ARG,
)
from yoke_core.domain.db_backend import PG_DSN_FILE_ENV
from yoke_core.tools import self_host_server_bootstrap
from yoke_core.api import container_healthcheck
from yoke_core.tools.self_host_server_bootstrap import (
    SelfHostServerBootstrapError,
    assert_no_effective_linux_capabilities,
    assert_runtime_secrets_readable,
    materialize_self_host_runtime_secrets,
)


def test_handoff_inputs_are_written_by_runtime_without_chown(tmp_path, monkeypatch):
    payloads = {PG_DSN_FILE_ENV: b"host=db dbname=yoke user=yoke password=test\n"}
    monkeypatch.setattr(os, "chown", lambda *_a: pytest.fail("no chown is needed"))
    monkeypatch.setattr(os, "fchown", lambda *_a: pytest.fail("no chown is needed"))
    env, targets = materialize_self_host_runtime_secrets(
        {PG_DSN_FILE_ENV: "/run/secrets/yoke-db-dsn"},
        payloads=payloads,
        target_dir=tmp_path / "runtime",
        runtime_uid=os.geteuid(),
        runtime_gid=os.getegid(),
    )
    assert targets[0].read_bytes() == payloads[PG_DSN_FILE_ENV]
    assert stat.S_IMODE(targets[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(targets[0].parent.stat().st_mode) == 0o700
    assert env[PG_DSN_FILE_ENV] == str(targets[0])
    assert_runtime_secrets_readable(targets)


@pytest.mark.parametrize(
    "payloads",
    ({}, {PG_DSN_FILE_ENV: b""}, {PG_DSN_FILE_ENV: b"x", "unexpected": b"x"}),
)
def test_missing_empty_or_unrequested_input_refuses(tmp_path, payloads):
    with pytest.raises(SelfHostServerBootstrapError, match="self_host_handoff"):
        materialize_self_host_runtime_secrets(
            {PG_DSN_FILE_ENV: "/run/secrets/yoke-db-dsn"},
            payloads=payloads,
            target_dir=tmp_path / "runtime",
            runtime_uid=os.geteuid(),
            runtime_gid=os.getegid(),
        )


def test_linux_effective_capability_proof_is_fail_closed(tmp_path: Path):
    status = tmp_path / "status"
    status.write_text("Name:\ttest\nCapEff:\t0000000000000000\n", encoding="utf-8")
    assert_no_effective_linux_capabilities(status_path=status)

    status.write_text("Name:\ttest\nCapEff:\t0000000000000001\n", encoding="utf-8")
    with pytest.raises(SelfHostServerBootstrapError, match="retained effective"):
        assert_no_effective_linux_capabilities(status_path=status)


def test_compose_healthcheck_drops_root_before_running_probe(monkeypatch):
    calls = []
    monkeypatch.setattr(self_host_server_bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        self_host_server_bootstrap.pwd,
        "getpwnam",
        lambda _name: SimpleNamespace(pw_uid=100, pw_gid=101),
    )
    monkeypatch.setattr(
        self_host_server_bootstrap,
        "drop_to_self_host_runtime_identity",
        lambda **identity: calls.append(("drop", identity)),
    )
    monkeypatch.setattr(
        self_host_server_bootstrap,
        "assert_no_effective_linux_capabilities",
        lambda: calls.append(("capabilities", {})),
    )
    monkeypatch.setattr(
        container_healthcheck,
        "main",
        lambda: calls.append(("healthcheck", {})) or 0,
    )

    assert self_host_server_bootstrap.main(["--healthcheck"]) == 0
    assert calls == [
        ("drop", {"uid": 100, "gid": 101}),
        ("capabilities", {}),
        ("healthcheck", {}),
    ]


@pytest.mark.parametrize(
    ("selector", "expected_tail"),
    (
        (
            IMPORT_UNIVERSE_ARG,
            ["-m", "yoke_core.domain.universe_import_cli", "--stdin"],
        ),
        (
            RECOVER_IMPORT_CREDENTIAL_ARG,
            [
                "-m",
                "yoke_core.domain.universe_import_cli",
                "--recover-credential",
            ],
        ),
    ),
)
def test_bootstrap_allowlists_import_commands_after_privilege_drop(
    monkeypatch, selector, expected_tail
):
    calls = []
    runtime_env = {
        "YOKE_PG_DSN_FILE": "/dev/shm/yoke-runtime-secrets/yoke-db-dsn",
        "YOKE_FIRST_BOOT_TOKEN_FD": "42",
    }
    monkeypatch.setattr(
        self_host_server_bootstrap,
        "receive_bootstrap_handoff",
        lambda env: (runtime_env, {}),
    )
    monkeypatch.setattr(self_host_server_bootstrap.os, "dup2", lambda *_a: None)
    monkeypatch.setattr(self_host_server_bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        self_host_server_bootstrap.pwd,
        "getpwnam",
        lambda _name: SimpleNamespace(pw_uid=100, pw_gid=101),
    )
    monkeypatch.setattr(
        self_host_server_bootstrap,
        "materialize_self_host_runtime_secrets",
        lambda *_args, **_kwargs: (runtime_env, (Path("/runtime/dsn"),)),
    )
    monkeypatch.setattr(
        self_host_server_bootstrap,
        "drop_to_self_host_runtime_identity",
        lambda **identity: calls.append(("drop", identity)),
    )
    monkeypatch.setattr(
        self_host_server_bootstrap,
        "assert_runtime_secrets_readable",
        lambda paths: calls.append(("readable", paths)),
    )
    monkeypatch.setattr(
        self_host_server_bootstrap,
        "assert_no_effective_linux_capabilities",
        lambda: calls.append(("capabilities", {})),
    )

    def execvpe(executable, argv, env):
        calls.append(("exec", (executable, argv, env)))
        raise RuntimeError("exec intercepted")

    monkeypatch.setattr(self_host_server_bootstrap.os, "execvpe", execvpe)

    with pytest.raises(RuntimeError, match="exec intercepted"):
        self_host_server_bootstrap.main([selector])

    assert calls[:3] == [
        ("drop", {"uid": 100, "gid": 101}),
        ("readable", (Path("/runtime/dsn"),)),
        ("capabilities", {}),
    ]
    executable, argv, env = calls[3][1]
    assert argv[0] == executable
    assert argv[1:] == expected_tail
    assert env == runtime_env
