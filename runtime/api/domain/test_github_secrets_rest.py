"""Tests for github_secrets_rest — encrypt + push + list via REST.

Encryption uses a libsodium sealed box; we generate a real keypair in
the test, encrypt against the public half, decrypt with the private
half, and assert roundtrip equality. The REST transport is mocked via
``urlopen`` monkeypatching — no live network.
"""

from __future__ import annotations

import base64
import io
import json
from typing import Any

import pytest
from nacl.public import PrivateKey, SealedBox

from yoke_core.domain import github_secrets_rest as mod
from yoke_core.domain.gh_rest_transport import RestNotFoundError


def _make_keypair_b64() -> tuple[str, PrivateKey]:
    """Generate a fresh keypair; return (public_b64, private_key_obj)."""
    private = PrivateKey.generate()
    public_b64 = base64.b64encode(bytes(private.public_key)).decode("ascii")
    return public_b64, private


def test_encrypt_secret_roundtrips_through_sealed_box():
    public_b64, private = _make_keypair_b64()
    ciphertext_b64 = mod.encrypt_secret(public_b64, "hello world")

    ciphertext = base64.b64decode(ciphertext_b64)
    plaintext = SealedBox(private).decrypt(ciphertext)
    assert plaintext == b"hello world"


def test_encrypt_secret_handles_unicode():
    public_b64, private = _make_keypair_b64()
    ciphertext = base64.b64decode(mod.encrypt_secret(public_b64, "héllo 🌍"))
    assert SealedBox(private).decrypt(ciphertext).decode("utf-8") == "héllo 🌍"


class _FakeResponse:
    def __init__(self, status: int, body: Any):
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


def _install_fake_urlopen(monkeypatch, responses: list[Any]):
    """Install a fake urlopen that serves ``responses`` FIFO and records each request."""
    received: list[dict] = []

    def fake(req, timeout=None):
        received.append(
            {
                "method": req.get_method(),
                "url": req.full_url,
                "headers": dict(req.header_items()),
                "body": req.data,
            }
        )
        if not responses:
            raise AssertionError("fake urlopen exhausted")
        nxt = responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    # Patch the module-level urlopen attribute used by the transport.
    from yoke_core.domain import gh_rest_transport

    monkeypatch.setattr(gh_rest_transport, "urlopen", fake)
    return received


def test_fetch_public_key_returns_key_id_and_key(monkeypatch):
    received = _install_fake_urlopen(
        monkeypatch,
        [_FakeResponse(200, {"key_id": "abc123", "key": "BASE64PUBKEY=="})],
    )

    key_id, key_b64 = mod.fetch_public_key(
        "owner/repo", token="ghs_secrets_transport_test"
    )
    assert key_id == "abc123"
    assert key_b64 == "BASE64PUBKEY=="
    assert received[0]["method"] == "GET"
    assert "/repos/owner/repo/actions/secrets/public-key" in received[0]["url"]


def test_set_repo_secret_fetches_key_then_puts_ciphertext(monkeypatch):
    public_b64, private = _make_keypair_b64()
    received = _install_fake_urlopen(
        monkeypatch,
        [
            _FakeResponse(200, {"key_id": "kid-1", "key": public_b64}),
            _FakeResponse(204, b""),
        ],
    )

    mod.set_repo_secret(
        "owner/repo", "MY_SECRET", "shh", token="ghs_secrets_transport_test"
    )

    assert len(received) == 2
    get_req, put_req = received
    assert get_req["method"] == "GET"
    assert put_req["method"] == "PUT"
    assert "/repos/owner/repo/actions/secrets/MY_SECRET" in put_req["url"]

    put_body = json.loads(put_req["body"].decode("utf-8"))
    assert put_body["key_id"] == "kid-1"
    decrypted = SealedBox(private).decrypt(
        base64.b64decode(put_body["encrypted_value"])
    )
    assert decrypted == b"shh"


def test_list_repo_secret_names_extracts_names(monkeypatch):
    _install_fake_urlopen(
        monkeypatch,
        [
            _FakeResponse(
                200,
                {
                    "total_count": 2,
                    "secrets": [
                        {"name": "DEPLOY_KEY", "created_at": "2025-01-01"},
                        {"name": "DEPLOY_HOST", "created_at": "2025-01-02"},
                    ],
                },
            )
        ],
    )
    names = mod.list_repo_secret_names("owner/repo", token="ghs_secrets_transport_test")
    assert names == ["DEPLOY_KEY", "DEPLOY_HOST"]


def test_repo_secret_exists_true_and_false(monkeypatch):
    _install_fake_urlopen(
        monkeypatch,
        [_FakeResponse(200, {"secrets": [{"name": "X"}]})],
    )
    assert (
        mod.repo_secret_exists("owner/repo", "X", token="ghs_secrets_transport_test")
        is True
    )

    _install_fake_urlopen(
        monkeypatch,
        [_FakeResponse(200, {"secrets": [{"name": "X"}]})],
    )
    assert (
        mod.repo_secret_exists("owner/repo", "Y", token="ghs_secrets_transport_test")
        is False
    )


def test_set_repo_secret_propagates_transport_errors(monkeypatch):
    import urllib.error

    err = urllib.error.HTTPError(
        url="https://api.github.com/repos/owner/repo/actions/secrets/public-key",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=io.BytesIO(b'{"message":"Not Found"}'),
    )
    _install_fake_urlopen(monkeypatch, [err])

    with pytest.raises(RestNotFoundError):
        mod.set_repo_secret(
            "owner/missing", "X", "v", token="ghs_secrets_transport_test"
        )
