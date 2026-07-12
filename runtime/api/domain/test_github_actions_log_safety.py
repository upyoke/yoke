"""Adversarial bounds and ZIP-bomb tests for GitHub Actions logs."""

from __future__ import annotations

import io
import urllib.error
import zipfile

import pytest

from yoke_core.domain import github_actions_log_archive as archive_safety
from yoke_core.domain import github_actions_logs
from yoke_core.domain.gh_rest_transport import RestAuthError, RestNetworkError


class _RecordingReader:
    def __init__(self, payload: bytes, *, headers: dict[str, str] | None = None):
        self.payload = payload
        self.headers = headers or {}
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self.payload if size < 0 else self.payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def close(self) -> None:
        return None


def _build_zip(
    entries: dict[str, bytes],
    *,
    compression: int = zipfile.ZIP_STORED,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def test_compressed_fetch_accepts_exact_boundary_and_uses_sentinel(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        github_actions_logs, "GITHUB_ACTIONS_LOG_ARCHIVE_LIMIT_BYTES", 8
    )
    response = _RecordingReader(b"12345678")
    monkeypatch.setattr(
        github_actions_logs, "urlopen", lambda *_args, **_kwargs: response
    )

    result = github_actions_logs.fetch_failed_log_zip("o/r", 1, token="ghs_x")

    assert result == b"12345678"
    assert response.read_sizes == [9]


def test_compressed_fetch_rejects_overflow_sentinel(monkeypatch) -> None:
    monkeypatch.setattr(
        github_actions_logs, "GITHUB_ACTIONS_LOG_ARCHIVE_LIMIT_BYTES", 8
    )
    response = _RecordingReader(b"123456789")
    monkeypatch.setattr(
        github_actions_logs, "urlopen", lambda *_args, **_kwargs: response
    )

    with pytest.raises(github_actions_logs.ActionsLogArchiveError):
        github_actions_logs.fetch_failed_log_zip("o/r", 1, token="ghs_x")

    assert response.read_sizes == [9]


def test_direct_parser_rejects_oversized_compressed_input(monkeypatch) -> None:
    monkeypatch.setattr(archive_safety, "GITHUB_ACTIONS_LOG_ARCHIVE_LIMIT_BYTES", 8)

    with pytest.raises(archive_safety.ActionsLogArchiveError, match="compressed"):
        archive_safety.parse_failed_log_zip(b"123456789")


def test_content_length_oversize_fails_before_read(monkeypatch) -> None:
    monkeypatch.setattr(
        github_actions_logs, "GITHUB_ACTIONS_LOG_ARCHIVE_LIMIT_BYTES", 8
    )
    response = _RecordingReader(b"ignored", headers={"content-length": "9"})
    monkeypatch.setattr(
        github_actions_logs, "urlopen", lambda *_args, **_kwargs: response
    )

    with pytest.raises(github_actions_logs.ActionsLogArchiveError):
        github_actions_logs.fetch_failed_log_zip("o/r", 1, token="ghs_x")

    assert response.read_sizes == []


def test_http_error_is_bounded_classified_and_token_scrubbed(monkeypatch) -> None:
    token = "ghs_log_secret"
    monkeypatch.setattr(github_actions_logs, "GITHUB_SMALL_RESPONSE_LIMIT_BYTES", 256)
    body = _RecordingReader(
        f"prefix{token}suffix repeated={token}:{token}".encode("utf-8")
    )
    error = urllib.error.HTTPError("https://api.github.com/x", 401, token, {}, body)

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(github_actions_logs, "urlopen", fail)

    with pytest.raises(RestAuthError) as exc_info:
        github_actions_logs.fetch_failed_log_zip("o/r", 1, token=token)

    rendered = f"{exc_info.value} {exc_info.value.body}"
    assert token not in rendered
    assert body.read_sizes == [257]
    assert exc_info.value.status == 401
    assert exc_info.value.__cause__ is None


def test_oversized_http_error_preserves_status_classification(monkeypatch) -> None:
    monkeypatch.setattr(github_actions_logs, "GITHUB_SMALL_RESPONSE_LIMIT_BYTES", 8)
    body = _RecordingReader(b"123456789")
    error = urllib.error.HTTPError("https://api.github.com/x", 403, "secret", {}, body)
    monkeypatch.setattr(
        github_actions_logs,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(RestAuthError) as exc_info:
        github_actions_logs.fetch_failed_log_zip("o/r", 1, token="secret")

    assert exc_info.value.status == 403
    assert body.read_sizes == [9]


def test_network_reason_is_detail_free(monkeypatch) -> None:
    token = "ghs_network_secret"

    def fail(*_args, **_kwargs):
        raise urllib.error.URLError(f"upstream echoed {token}")

    monkeypatch.setattr(github_actions_logs, "urlopen", fail)
    monkeypatch.setattr(github_actions_logs, "sleep", lambda _seconds: None)

    with pytest.raises(RestNetworkError) as exc_info:
        github_actions_logs.fetch_failed_log_zip("o/r", 1, token=token)

    assert token not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize("failure_type", [TimeoutError, OSError])
def test_direct_network_failures_are_normalized(monkeypatch, failure_type) -> None:
    token = "ghs_direct_network_secret"

    def fail(*_args, **_kwargs):
        raise failure_type(token)

    monkeypatch.setattr(github_actions_logs, "urlopen", fail)
    monkeypatch.setattr(github_actions_logs, "sleep", lambda _seconds: None)

    with pytest.raises(RestNetworkError) as exc_info:
        github_actions_logs.fetch_failed_log_zip("o/r", 1, token=token)

    assert token not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_archive_rejects_excess_entry_count_before_extract(monkeypatch) -> None:
    monkeypatch.setattr(archive_safety, "GITHUB_ACTIONS_LOG_ENTRY_COUNT_LIMIT", 1)
    payload = _build_zip({"1_a.txt": b"a", "2_b.txt": b"b"})

    with pytest.raises(archive_safety.ActionsLogArchiveError, match="too many"):
        archive_safety.parse_failed_log_zip(payload)


def test_archive_rejects_relevant_entry_size_before_extract(monkeypatch) -> None:
    monkeypatch.setattr(archive_safety, "GITHUB_ACTIONS_LOG_ENTRY_LIMIT_BYTES", 3)
    payload = _build_zip({"1_build.txt": b"four"})

    with pytest.raises(archive_safety.ActionsLogArchiveError, match="entry exceeded"):
        archive_safety.parse_failed_log_zip(payload)


def test_archive_stream_rejects_lie_with_one_byte_overflow_read(monkeypatch) -> None:
    monkeypatch.setattr(archive_safety, "GITHUB_ACTIONS_LOG_ENTRY_LIMIT_BYTES", 5)
    monkeypatch.setattr(archive_safety, "GITHUB_ACTIONS_LOG_TOTAL_LIMIT_BYTES", 5)

    class _LyingInfo:
        filename = "1_build.txt"
        file_size = 1
        compress_size = 100
        flag_bits = 0

        @staticmethod
        def is_dir() -> bool:
            return False

    class _ChunkSource(_RecordingReader):
        def __init__(self) -> None:
            super().__init__(b"123456")
            self.offset = 0

        def read(self, size: int = -1) -> bytes:
            self.read_sizes.append(size)
            selected = (
                self.payload[self.offset :]
                if size < 0
                else self.payload[self.offset : self.offset + size]
            )
            self.offset += len(selected)
            return selected

    source = _ChunkSource()

    class _LyingArchive:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def infolist():
            return [_LyingInfo()]

        @staticmethod
        def open(_info, _mode):
            return source

    monkeypatch.setattr(
        archive_safety.zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: _LyingArchive(),
    )

    with pytest.raises(archive_safety.ActionsLogArchiveError, match="size limit"):
        archive_safety.parse_failed_log_zip(b"synthetic")

    assert source.read_sizes == [6]


def test_archive_rejects_cumulative_expanded_size(monkeypatch) -> None:
    monkeypatch.setattr(archive_safety, "GITHUB_ACTIONS_LOG_TOTAL_LIMIT_BYTES", 5)
    payload = _build_zip({"1_a.txt": b"aaa", "2_b.txt": b"bbb"})

    with pytest.raises(archive_safety.ActionsLogArchiveError, match="expanded"):
        archive_safety.parse_failed_log_zip(payload)


def test_archive_rejects_excess_compression_ratio(monkeypatch) -> None:
    monkeypatch.setattr(archive_safety, "GITHUB_ACTIONS_LOG_COMPRESSION_RATIO_LIMIT", 2)
    payload = _build_zip(
        {"1_build.txt": b"a" * 1_024}, compression=zipfile.ZIP_DEFLATED
    )

    with pytest.raises(archive_safety.ActionsLogArchiveError, match="compression"):
        archive_safety.parse_failed_log_zip(payload)


def test_corrupted_entry_fails_typed_and_detail_free() -> None:
    body = b"unique-crc-payload"
    payload = _build_zip({"1_build.txt": body})
    corrupted = payload.replace(body, b"x" * len(body), 1)

    with pytest.raises(archive_safety.ActionsLogArchiveError) as exc_info:
        archive_safety.parse_failed_log_zip(corrupted)

    assert "unique-crc-payload" not in str(exc_info.value)


def test_archive_accepts_exact_entry_and_total_boundary(monkeypatch) -> None:
    monkeypatch.setattr(archive_safety, "GITHUB_ACTIONS_LOG_ENTRY_LIMIT_BYTES", 5)
    monkeypatch.setattr(archive_safety, "GITHUB_ACTIONS_LOG_TOTAL_LIMIT_BYTES", 5)
    payload = _build_zip({"1_build.txt": b"abcde"})

    result = archive_safety.parse_failed_log_zip(payload)

    assert result == {"build": "abcde"}
