"""A transient health probe failure does not declare the authority unreachable."""

from unittest.mock import MagicMock, patch

import pytest

from yoke_cli.config.status_server import fetch_server_health


def response(body=b'{"status":"ok"}'):
    result = MagicMock()
    result.__enter__.return_value.read.return_value = body
    return result


def test_health_retries_once_with_ten_second_timeout():
    with patch(
        "urllib.request.urlopen", side_effect=[TimeoutError(), response()]
    ) as request:
        assert fetch_server_health("https://example.test") == {"status": "ok"}
    assert request.call_count == 2
    assert all(call.kwargs["timeout"] == 10.0 for call in request.call_args_list)


@pytest.mark.parametrize(
    "failure", [TimeoutError(), ValueError(), response(b"[]"), response(b"invalid")]
)
def test_exhausted_attempts_return_unreachable(failure):
    with patch("urllib.request.urlopen", side_effect=[failure, failure]) as request:
        assert fetch_server_health("https://example.test") is None
    assert request.call_count == 2


def test_success_does_not_retry_and_preserves_explicit_timeout():
    with patch("urllib.request.urlopen", return_value=response()) as request:
        assert fetch_server_health("https://example.test", timeout_s=0.25)
    request.assert_called_once_with("https://example.test/v1/health", timeout=0.25)
