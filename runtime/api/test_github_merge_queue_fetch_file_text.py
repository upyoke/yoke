"""fetch_file_text over the shared GitHub REST decode path."""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO

from yoke_core.domain import gh_rest_transport, github_merge_queue_rest as mq_rest


class _FakeResponse:
    def __init__(self, status: int, body):
        self.status = status
        self._body = (
            body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        )
        self.headers = {"X-RateLimit-Remaining": "5000"}

    def read(self, _size: int = -1):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _install_urlopen(monkeypatch, responses):
    def fake(req, timeout=None):
        if not responses:
            raise AssertionError("fake urlopen exhausted")
        nxt = responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr(gh_rest_transport, "urlopen", fake)
    monkeypatch.setattr(gh_rest_transport, "sleep", lambda _s: None)


def _http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.github.com/x",
        code=status,
        msg=f"HTTP {status}",
        hdrs={"Content-Type": "application/json"},  # type: ignore[arg-type]
        fp=BytesIO(body),
    )


def test_json_declaration_body_returns_text_after_transport_decode(monkeypatch):
    payload = {"schema": 1, "ruleset": {"name": "merge-queue-main"}}
    _install_urlopen(monkeypatch, [_FakeResponse(200, payload)])
    text = mq_rest.fetch_file_text(
        "o", "r", ".yoke/merge-queue.json", ref="main", token="ghs_x",
    )
    assert text is not None
    assert json.loads(text) == payload


def test_json_null_body_is_null_document_not_missing(monkeypatch):
    _install_urlopen(monkeypatch, [_FakeResponse(200, None)])
    text = mq_rest.fetch_file_text(
        "o", "r", ".yoke/merge-queue.json", ref="main", token="ghs_x",
    )
    assert text == "null"


def test_404_returns_none(monkeypatch):
    _install_urlopen(monkeypatch, [_http_error(404, b'{"message":"Not Found"}')])
    text = mq_rest.fetch_file_text(
        "o", "r", ".yoke/merge-queue.json", ref="main", token="ghs_x",
    )
    assert text is None


def test_non_json_body_stays_raw_text(monkeypatch):
    yaml_text = b"on:\n  merge_group:\n"
    _install_urlopen(monkeypatch, [_FakeResponse(200, yaml_text)])
    text = mq_rest.fetch_file_text(
        "o", "r", ".github/workflows/yoke-ci.yml", ref="main", token="ghs_x",
    )
    assert text == yaml_text.decode("utf-8")
