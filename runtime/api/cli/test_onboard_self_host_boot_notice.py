"""Self-host boot notices name a safe, pasteable operator connection."""

import pytest
from yoke_contracts.self_host_bootstrap_output import (
    FIRST_BOOT_TOKEN_MARKER,
    TOKEN_PREFIX,
    TOKEN_BODY_LENGTH,
    connect_url_from_publish_spec,
    first_boot_admin_token_notice,
)

RAW_TOKEN = TOKEN_PREFIX + "A" * TOKEN_BODY_LENGTH


def test_boot_notice_names_the_token_file_and_never_the_token() -> None:
    notice = first_boot_admin_token_notice(
        host_path="./secrets/first-boot-admin-token",
        connect_url="http://127.0.0.1:8765",
    )

    assert FIRST_BOOT_TOKEN_MARKER in notice
    assert RAW_TOKEN not in notice
    assert "./secrets/first-boot-admin-token" in notice
    assert (
        "yoke connect http://127.0.0.1:8765 --token-stdin "
        "< ./secrets/first-boot-admin-token"
    ) in notice


@pytest.mark.parametrize(
    ("publish_spec", "expected"),
    [
        ("127.0.0.1:8765", "http://127.0.0.1:8765"),
        ("0.0.0.0:8765", "http://127.0.0.1:8765"),
        ("192.168.1.10:9000", "http://192.168.1.10:9000"),
        ("[::]:8765", "http://127.0.0.1:8765"),
        ("", "http://127.0.0.1:8765"),
    ],
)
def test_publish_spec_becomes_a_pasteable_connect_url(
    publish_spec: str,
    expected: str,
) -> None:
    assert connect_url_from_publish_spec(publish_spec) == expected
