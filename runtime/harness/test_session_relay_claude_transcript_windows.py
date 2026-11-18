"""Native Windows Claude transcript keys observed on windows-native-lab."""

from pathlib import Path

import pytest

from yoke_harness.session_relay_claude_transcript import claude_project_storage_key


# Captured from actual Claude Code 2.1.327 transcript directories on Windows build 26200.
_CHECKOUT_ROOT = r"C:\Users\yokeqa\AppData\Local\Temp\Yoke Claude Key 4cwj0zu7"
_KEY_PREFIX = "C--Users-yokeqa-AppData-Local-Temp-Yoke-Claude-Key-4cwj0zu7-"


@pytest.mark.windows_only(reason="Claude hashes native Windows drive and backslash paths")
@pytest.mark.parametrize(
    ("checkout", "expected"),
    [
        pytest.param(
            _CHECKOUT_ROOT + r"\Checkout One",
            _KEY_PREFIX + "Checkout-One",
            id="drive-and-spaces",
        ),
        pytest.param(
            _CHECKOUT_ROOT + r"\Long Checkout " + "x" * 131,
            _KEY_PREFIX + "Long-Checkout-" + "x" * 126 + "-2wfrqi",
            id="long-native-path-hash",
        ),
    ],
)
def test_project_storage_key_matches_native_claude(checkout: str, expected: str) -> None:
    assert claude_project_storage_key(Path(checkout)) == expected
