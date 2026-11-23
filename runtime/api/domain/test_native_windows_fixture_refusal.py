"""Native case setup refuses POSIX fixture operations."""

import pytest

from yoke_core.domain.native_windows_fixture import NativeWindowsFixture

pytestmark = pytest.mark.windows


def test_native_fixture_refuses_posix_operation_and_closes():
    fixture = NativeWindowsFixture(object())
    refused = fixture.execute_setup_operations(
        [{"id": "terminal.size-prepare", "parameters": {"columns": 80, "rows": 24}}]
    )
    assert not refused.ok
    assert refused.error_code == "native_windows_fixture_required"
    assert refused.evidence["operations"][0]["id"] == "terminal.size-prepare"
    assert fixture.close().ok
    assert fixture.closed
