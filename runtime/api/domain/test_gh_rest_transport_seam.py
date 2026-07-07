"""Tests for the gh_rest_transport test seams + helpers."""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO

import pytest

from yoke_core.domain import gh_rest_transport as t
from yoke_core.domain import gh_rest_transport_fakes as fakes


def _http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.github.com/x",
        code=status,
        msg=f"HTTP {status}",
        hdrs={"Content-Type": "application/json"},  # type: ignore[arg-type]
        fp=BytesIO(body),
    )


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.setattr(t, "sleep", lambda _s: None)
    monkeypatch.delenv(fakes.FAKE_DIR_ENV, raising=False)
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_split_repo_ok():
    assert t.split_repo("anthropics/yoke") == ("anthropics", "yoke")


def test_split_repo_invalid():
    with pytest.raises(ValueError):
        t.split_repo("bare")
    with pytest.raises(ValueError):
        t.split_repo("/r")
    with pytest.raises(ValueError):
        t.split_repo("o/")


def test_build_url_relative():
    req = t.RestRequest(method="GET", path="/x")
    assert t._build_url(req) == "https://api.github.com/x"


def test_build_url_absolute_passthrough():
    req = t.RestRequest(method="GET", path="https://api.github.com/y")
    assert t._build_url(req) == "https://api.github.com/y"


def test_build_url_with_query():
    req = t.RestRequest(
        method="GET",
        path="/repos/o/r/pulls",
        query={"head": "o:b", "state": "open"},
    )
    url = t._build_url(req)
    assert url.startswith("https://api.github.com/repos/o/r/pulls?")
    assert "head=o%3Ab" in url
    assert "state=open" in url


# ---------------------------------------------------------------------------
# YOKE_REST_FAKE_DIR test seam
# ---------------------------------------------------------------------------


def test_fake_dir_returns_canned_success(monkeypatch, tmp_path):
    payload = {"status": 200, "headers": {}, "body": {"number": 33, "url": "u"}}
    (tmp_path / "POST_repos_o_r_pulls.json").write_text(json.dumps(payload))
    monkeypatch.setenv(fakes.FAKE_DIR_ENV, str(tmp_path))
    resp = t.request_with_retry(
        t.RestRequest(method="POST", path="/repos/o/r/pulls"),
        token="ghp_x",
    )
    assert resp.status == 200
    assert resp.body == {"number": 33, "url": "u"}


def test_fake_dir_returns_canned_error(monkeypatch, tmp_path):
    payload = {"status": 422, "headers": {}, "body": {"message": "already exists"}}
    (tmp_path / "POST_repos_o_r_pulls.json").write_text(json.dumps(payload))
    monkeypatch.setenv(fakes.FAKE_DIR_ENV, str(tmp_path))
    with pytest.raises(t.RestUnprocessableError):
        t.request_with_retry(
            t.RestRequest(method="POST", path="/repos/o/r/pulls"),
            token="ghp_x",
        )


def test_fake_dir_missing_file_raises(monkeypatch, tmp_path):
    monkeypatch.setenv(fakes.FAKE_DIR_ENV, str(tmp_path))
    with pytest.raises(t.RestTransportError):
        t.request_with_retry(
            t.RestRequest(method="GET", path="/missing"), token="ghp_x"
        )


def test_fake_dir_query_in_filename(monkeypatch, tmp_path):
    payload = {"status": 200, "headers": {}, "body": [{"number": 7, "url": "u"}]}
    filename = fakes.fake_response_filename(
        t.RestRequest(
            method="GET",
            path="/repos/o/r/pulls",
            query={"head": "o:b", "state": "open"},
        )
    )
    (tmp_path / filename).write_text(json.dumps(payload))
    monkeypatch.setenv(fakes.FAKE_DIR_ENV, str(tmp_path))
    resp = t.request_with_retry(
        t.RestRequest(
            method="GET",
            path="/repos/o/r/pulls",
            query={"head": "o:b", "state": "open"},
        ),
        token="ghp_x",
    )
    assert resp.body == [{"number": 7, "url": "u"}]


def test_fake_filename_canonical_form():
    """The filename is deterministic so tests can author them by name."""
    req = t.RestRequest(method="POST", path="/repos/o/r/pulls")
    assert fakes.fake_response_filename(req) == "POST_repos_o_r_pulls.json"


def test_max_attempts_one_disables_retry(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(_request, timeout=None):
        calls["n"] += 1
        raise _http_error(502, b"Bad Gateway")

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    with pytest.raises(t.RestServerError):
        t.request_with_retry(
            t.RestRequest(method="GET", path="/x"),
            token="ghp_x",
            max_attempts=1,
        )

    assert calls["n"] == 1
