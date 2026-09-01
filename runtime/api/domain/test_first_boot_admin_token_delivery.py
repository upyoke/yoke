"""Where a newborn universe's one-time admin token actually lands."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from yoke_core.api import first_boot_admin_token_delivery as subject
from yoke_core.tools import self_host_server_bootstrap as bootstrap
from yoke_contracts.self_host_bootstrap_output import (
    API_PUBLISH_ENV,
    FIRST_BOOT_TOKEN_FD_ENV,
    FIRST_BOOT_TOKEN_FILE_ENV,
    FIRST_BOOT_TOKEN_HOST_PATH_ENV,
    FIRST_BOOT_TOKEN_MARKER,
    TOKEN_BODY_LENGTH,
    TOKEN_PREFIX,
)

RAW_TOKEN = TOKEN_PREFIX + ("B" * TOKEN_BODY_LENGTH)


@pytest.fixture()
def token_file(tmp_path: Path) -> Path:
    target = tmp_path / "first-boot-admin-token"
    target.touch(mode=0o600)
    return target


def test_token_goes_to_the_file_and_never_to_the_log(
    token_file: Path, capsys,
) -> None:
    descriptor = os.open(token_file, os.O_WRONLY)
    try:
        banner = subject.deliver_first_boot_admin_token(
            RAW_TOKEN,
            env={
                FIRST_BOOT_TOKEN_FILE_ENV: "/run/yoke-first-boot-admin-token",
                FIRST_BOOT_TOKEN_FD_ENV: str(descriptor),
                FIRST_BOOT_TOKEN_HOST_PATH_ENV: "./secrets/first-boot-admin-token",
                API_PUBLISH_ENV: "0.0.0.0:9100",
            },
        )
    finally:
        os.close(descriptor)

    assert token_file.read_text(encoding="utf-8") == RAW_TOKEN + "\n"
    printed = capsys.readouterr().out
    assert RAW_TOKEN not in printed
    assert FIRST_BOOT_TOKEN_MARKER in printed
    assert "./secrets/first-boot-admin-token" in printed
    # The publish spec is a bind address; the operator needs a URL to paste.
    assert "yoke connect http://127.0.0.1:9100 --token-stdin" in printed
    assert banner in printed


def test_an_existing_token_file_is_overwritten_not_appended(
    token_file: Path,
) -> None:
    token_file.write_text("x" * 4096, encoding="utf-8")
    descriptor = os.open(token_file, os.O_WRONLY)
    try:
        subject.deliver_first_boot_admin_token(
            RAW_TOKEN,
            env={
                FIRST_BOOT_TOKEN_FILE_ENV: "/run/token",
                FIRST_BOOT_TOKEN_FD_ENV: str(descriptor),
            },
        )
    finally:
        os.close(descriptor)

    assert token_file.read_text(encoding="utf-8") == RAW_TOKEN + "\n"


def test_a_declared_file_with_no_descriptor_fails_the_boot() -> None:
    with pytest.raises(subject.FirstBootTokenDeliveryError) as raised:
        subject.deliver_first_boot_admin_token(
            RAW_TOKEN,
            env={FIRST_BOOT_TOKEN_FILE_ENV: "/run/yoke-first-boot-admin-token"},
        )

    # Falling back to stdout here would print the credential into the log the
    # file exists to keep it out of.
    assert "carries no open descriptor" in str(raised.value)
    assert "docker compose up -d" in str(raised.value)


def test_an_unwritable_descriptor_names_the_bundle_repair(
    token_file: Path,
) -> None:
    descriptor = os.open(token_file, os.O_RDONLY)
    try:
        with pytest.raises(subject.FirstBootTokenDeliveryError) as raised:
            subject.deliver_first_boot_admin_token(
                RAW_TOKEN,
                env={
                    FIRST_BOOT_TOKEN_FILE_ENV: "/run/token",
                    FIRST_BOOT_TOKEN_FD_ENV: str(descriptor),
                },
            )
    finally:
        os.close(descriptor)

    assert "--protect-existing" in str(raised.value)


def test_a_server_outside_a_bundle_still_surrenders_its_token(capsys) -> None:
    subject.deliver_first_boot_admin_token(
        RAW_TOKEN, env={API_PUBLISH_ENV: "127.0.0.1:8765"},
    )

    printed = capsys.readouterr().out
    assert RAW_TOKEN in printed
    # No file to point at, so the banner says where the token now is.
    assert "This log now holds the token" in printed
    assert "yoke connect http://127.0.0.1:8765 --token-stdin" in printed


def test_bootstrap_opens_the_drop_before_privileges_are_dropped(
    token_file: Path,
) -> None:
    env = bootstrap.open_first_boot_token_drop(
        {FIRST_BOOT_TOKEN_FILE_ENV: str(token_file)}
    )

    descriptor = int(env[FIRST_BOOT_TOKEN_FD_ENV])
    try:
        # Inheritable, or the descriptor would not survive the exec into the
        # server process that has to write through it.
        assert os.get_inheritable(descriptor) is True
        os.write(descriptor, b"probe")
    finally:
        os.close(descriptor)
    assert token_file.read_bytes() == b"probe"


def test_bootstrap_refuses_a_bundle_whose_token_file_is_missing(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "secrets" / "first-boot-admin-token"

    with pytest.raises(bootstrap.SelfHostServerBootstrapError) as raised:
        bootstrap.open_first_boot_token_drop({FIRST_BOOT_TOKEN_FILE_ENV: str(missing)})

    assert str(missing) in str(raised.value)
    assert "--protect-existing" in str(raised.value)


def test_bootstrap_leaves_a_server_with_no_declared_drop_alone() -> None:
    assert bootstrap.open_first_boot_token_drop({"YOKE_SERVER_MODE": "self-host"}) == {
        "YOKE_SERVER_MODE": "self-host"
    }
