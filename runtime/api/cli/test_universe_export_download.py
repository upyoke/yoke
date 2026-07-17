"""Self-host HTTPS universe archive download coverage."""

from __future__ import annotations

import io
from email.message import Message
from pathlib import Path

from yoke_cli.config import universe_export_download as download
from yoke_cli.transport.https import HttpsConnection


class _Response(io.BytesIO):
    def __init__(self, body: bytes, url: str, headers: dict[str, str]):
        super().__init__(body)
        self._url = url
        message = Message()
        for key, value in headers.items():
            message[key] = value
        self.headers = message
        self.fp = object()

    def geturl(self):
        return self._url

    def read1(self, size=-1):
        return self.read(size)


def test_download_streams_to_owner_only_atomic_file(tmp_path: Path, monkeypatch):
    connection = HttpsConnection(
        api_url="https://yoke.example.test",
        token="secret-token",
        env="self-host",
    )
    url = "https://yoke.example.test/v1/universe/export"
    body = b"portable universe"
    response = _Response(body, url, {
        "content-type": "application/x-tar",
        "content-length": str(len(body)),
        "content-disposition": 'attachment; filename="acme-universe.tar"',
        "x-yoke-universe-format": "universe-tar",
        "x-yoke-universe-org": "acme",
        "x-yoke-universe-sha256": "a" * 64,
    })
    captured = {}

    def open_request(request, **_kwargs):
        captured["request"] = request
        return response

    monkeypatch.setattr(download, "open_bounded_request", open_request)
    monkeypatch.setattr(download, "_engine_limits", lambda: (30.0, 1024))
    report = download.download_universe(connection, out=str(tmp_path) + "/")

    artifact = Path(str(report["artifact"]))
    assert artifact.name == "acme-universe.tar"
    assert artifact.read_bytes() == body
    assert artifact.stat().st_mode & 0o777 == 0o600
    assert report["source"] == "self-host-https"
    assert report["org"] == "acme"
    assert captured["request"].full_url == url
    assert captured["request"].headers["Authorization"] == "Bearer secret-token"


def test_download_rejects_oversized_content_before_writing(tmp_path, monkeypatch):
    connection = HttpsConnection("https://yoke.example.test", "token")
    response = _Response(b"12345", connection.api_url + "/v1/universe/export", {
        "content-type": "application/x-tar",
        "content-length": "5",
        "content-disposition": 'attachment; filename="safe.tar"',
    })
    monkeypatch.setattr(download, "open_bounded_request", lambda *_a, **_k: response)
    monkeypatch.setattr(download, "_engine_limits", lambda: (30.0, 4))
    try:
        download.download_universe(connection, out=str(tmp_path) + "/")
    except download.UniverseExportDownloadError as exc:
        assert "exceeds the 4-byte limit" in str(exc)
    else:
        raise AssertionError("oversized response should be refused")
    assert list(tmp_path.iterdir()) == []


def test_truncated_download_preserves_existing_backup(tmp_path, monkeypatch):
    connection = HttpsConnection("https://yoke.example.test", "token")
    target = tmp_path / "backup.tar"
    target.write_bytes(b"previous")
    response = _Response(b"short", connection.api_url + "/v1/universe/export", {
        "content-type": "application/x-tar",
        "content-length": "12",
        "content-disposition": 'attachment; filename="ignored.tar"',
    })
    monkeypatch.setattr(download, "open_bounded_request", lambda *_a, **_k: response)
    monkeypatch.setattr(download, "_engine_limits", lambda: (30.0, 1024))
    try:
        download.download_universe(connection, out=str(target))
    except download.UniverseExportDownloadError as exc:
        assert "length did not match" in str(exc)
    else:
        raise AssertionError("truncated response should be refused")
    assert target.read_bytes() == b"previous"
    assert not list(tmp_path.glob(".*.tmp-*"))
