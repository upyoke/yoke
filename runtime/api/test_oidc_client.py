"""Unit coverage for the OIDC door client: config, flow state, provider."""

from __future__ import annotations

import time
import urllib.parse

import pytest

from runtime.api.oidc_provider_test_helpers import StubOidcProvider
from yoke_core.api.oidc_client import (
    OidcDiscoveryError,
    OidcExchangeError,
    OidcVerificationError,
    authorization_request_url,
    discover,
    exchange_code,
    verify_id_token,
)
from yoke_core.api.oidc_config import (
    OidcConfig,
    OidcConfigError,
    callback_url,
    resolve_oidc_config,
)
from yoke_core.api.oidc_flow_state import (
    OidcFlowStateError,
    _signature,
    mint_flow_state,
    verify_flow_state,
)


_ENV_KEYS = (
    "YOKE_OIDC_ISSUER",
    "YOKE_OIDC_CLIENT_ID",
    "YOKE_OIDC_CLIENT_SECRET_FILE",
    "YOKE_OIDC_CLIENT_SECRET",
    "YOKE_OIDC_REDIRECT_URL",
    "YOKE_OIDC_ALLOW_UNVERIFIED_EMAIL",
)


def _config(**overrides) -> OidcConfig:
    base = dict(
        issuer="https://issuer.example",
        client_id="door-client",
        client_secret="door-client-secret-value",
        redirect_base_url="https://yoke.example",
        allow_unverified_email=False,
    )
    base.update(overrides)
    return OidcConfig(**base)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class TestResolveConfig:
    def test_all_unset_means_door_disabled(self):
        assert resolve_oidc_config({}) is None

    def test_blank_values_count_as_unset(self):
        env = {key: "" for key in _ENV_KEYS}
        assert resolve_oidc_config(env) is None

    def test_partial_set_names_missing_vars(self):
        with pytest.raises(OidcConfigError) as excinfo:
            resolve_oidc_config({"YOKE_OIDC_ISSUER": "https://issuer.example"})
        message = str(excinfo.value)
        assert "YOKE_OIDC_CLIENT_ID" in message
        assert "YOKE_OIDC_REDIRECT_URL" in message
        assert "YOKE_OIDC_CLIENT_SECRET_FILE" in message

    def test_secret_file_wins_and_is_stripped(self, tmp_path):
        secret_file = tmp_path / "client-secret"
        secret_file.write_text("  sekrit-value \n", encoding="utf-8")
        config = resolve_oidc_config(
            {
                "YOKE_OIDC_ISSUER": "https://issuer.example/",
                "YOKE_OIDC_CLIENT_ID": "door-client",
                "YOKE_OIDC_CLIENT_SECRET_FILE": str(secret_file),
                "YOKE_OIDC_REDIRECT_URL": "https://yoke.example/",
            }
        )
        assert config is not None
        assert config.client_secret == "sekrit-value"
        # Trailing slashes are normalized off for URL building.
        assert config.issuer == "https://issuer.example"
        assert config.redirect_base_url == "https://yoke.example"
        assert config.allow_unverified_email is False

    def test_unreadable_secret_file_is_a_config_error(self, tmp_path):
        with pytest.raises(OidcConfigError):
            resolve_oidc_config(
                {
                    "YOKE_OIDC_ISSUER": "https://issuer.example",
                    "YOKE_OIDC_CLIENT_ID": "door-client",
                    "YOKE_OIDC_CLIENT_SECRET_FILE": str(tmp_path / "absent"),
                    "YOKE_OIDC_REDIRECT_URL": "https://yoke.example",
                }
            )

    def test_empty_secret_file_is_a_config_error(self, tmp_path):
        secret_file = tmp_path / "client-secret"
        secret_file.write_text("\n", encoding="utf-8")
        with pytest.raises(OidcConfigError):
            resolve_oidc_config(
                {
                    "YOKE_OIDC_ISSUER": "https://issuer.example",
                    "YOKE_OIDC_CLIENT_ID": "door-client",
                    "YOKE_OIDC_CLIENT_SECRET_FILE": str(secret_file),
                    "YOKE_OIDC_REDIRECT_URL": "https://yoke.example",
                }
            )

    def test_inline_secret_and_unverified_email_opt_in(self):
        config = resolve_oidc_config(
            {
                "YOKE_OIDC_ISSUER": "https://issuer.example",
                "YOKE_OIDC_CLIENT_ID": "door-client",
                "YOKE_OIDC_CLIENT_SECRET": "inline-secret",
                "YOKE_OIDC_REDIRECT_URL": "http://yoke.example",
                "YOKE_OIDC_ALLOW_UNVERIFIED_EMAIL": "true",
            }
        )
        assert config is not None
        assert config.client_secret == "inline-secret"
        assert config.allow_unverified_email is True

    def test_cleartext_remote_issuer_is_refused(self):
        # discovery / JWKS / the secret-carrying token exchange all hit the
        # issuer, so a cleartext hop to a remote host is refused.
        with pytest.raises(OidcConfigError) as excinfo:
            resolve_oidc_config(
                {
                    "YOKE_OIDC_ISSUER": "http://issuer.example",
                    "YOKE_OIDC_CLIENT_ID": "door-client",
                    "YOKE_OIDC_CLIENT_SECRET": "inline-secret",
                    "YOKE_OIDC_REDIRECT_URL": "https://yoke.example",
                }
            )
        assert "YOKE_OIDC_ISSUER" in str(excinfo.value)

    def test_loopback_http_issuer_is_allowed(self):
        # A local/stub provider on loopback never leaves the machine.
        config = resolve_oidc_config(
            {
                "YOKE_OIDC_ISSUER": "http://127.0.0.1:9099",
                "YOKE_OIDC_CLIENT_ID": "door-client",
                "YOKE_OIDC_CLIENT_SECRET": "inline-secret",
                "YOKE_OIDC_REDIRECT_URL": "http://127.0.0.1:9099",
            }
        )
        assert config is not None
        assert config.issuer == "http://127.0.0.1:9099"

    def test_cookie_secure_tracks_redirect_scheme(self):
        assert _config(redirect_base_url="https://yoke.example").cookie_secure
        assert not _config(redirect_base_url="http://10.0.0.5:8765").cookie_secure

    def test_callback_url_derived_from_base(self):
        assert callback_url(_config()) == (
            "https://yoke.example/v1/auth/oidc/callback"
        )


class TestFlowState:
    def test_roundtrip_returns_nonce(self):
        config = _config()
        flow = mint_flow_state(config)
        nonce = verify_flow_state(
            config, cookie_value=flow.cookie_value, state_param=flow.state,
        )
        assert nonce == flow.nonce

    def test_state_mismatch_rejected(self):
        config = _config()
        flow = mint_flow_state(config)
        with pytest.raises(OidcFlowStateError):
            verify_flow_state(
                config, cookie_value=flow.cookie_value, state_param="other",
            )

    def test_tampered_record_rejected(self):
        config = _config()
        flow = mint_flow_state(config)
        head, _, signature = flow.cookie_value.rpartition(".")
        flipped = ("0" if signature[0] != "0" else "1") + signature[1:]
        with pytest.raises(OidcFlowStateError):
            verify_flow_state(
                config,
                cookie_value=f"{head}.{flipped}",
                state_param=flow.state,
            )

    def test_record_signed_by_other_secret_rejected(self):
        flow = mint_flow_state(_config(client_secret="other-secret"))
        with pytest.raises(OidcFlowStateError):
            verify_flow_state(
                _config(), cookie_value=flow.cookie_value, state_param=flow.state,
            )

    def test_expired_record_rejected(self):
        config = _config()
        payload = f"the-state.the-nonce.{int(time.time()) - 5}"
        cookie_value = payload + "." + _signature(config, payload)
        with pytest.raises(OidcFlowStateError):
            verify_flow_state(
                config, cookie_value=cookie_value, state_param="the-state",
            )

    @pytest.mark.parametrize("bad", ["", "a.b", "a.b.c.d.e", "no-dots-here"])
    def test_malformed_record_rejected(self, bad):
        with pytest.raises(OidcFlowStateError):
            verify_flow_state(_config(), cookie_value=bad, state_param="x")


class TestProviderClient:
    @pytest.fixture()
    def provider(self):
        stub = StubOidcProvider()
        yield stub
        stub.close()

    def _door(self, provider: StubOidcProvider) -> OidcConfig:
        return _config(
            issuer=provider.issuer,
            client_id=provider.client_id,
            client_secret=provider.client_secret,
            redirect_base_url="http://yoke.example",
        )

    def test_discover_reads_and_caches_endpoints(self, provider):
        endpoints = discover(provider.issuer)
        assert endpoints.token_endpoint == provider.issuer + "/token"
        assert discover(provider.issuer) is endpoints

    def test_discovery_issuer_mismatch_rejected(self):
        stub = StubOidcProvider(
            declared_issuer_override="https://somewhere-else.example",
        )
        try:
            with pytest.raises(OidcDiscoveryError):
                discover(stub.issuer)
        finally:
            stub.close()

    def test_authorization_url_carries_flow_but_never_the_secret(self, provider):
        config = self._door(provider)
        endpoints = discover(provider.issuer)
        flow = mint_flow_state(config)
        url = authorization_request_url(config, endpoints, flow)
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        assert query["state"] == flow.state
        assert query["nonce"] == flow.nonce
        assert query["client_id"] == provider.client_id
        assert query["redirect_uri"] == (
            "http://yoke.example/v1/auth/oidc/callback"
        )
        assert provider.client_secret not in url

    def test_exchange_and_verify_roundtrip(self, provider):
        config = self._door(provider)
        endpoints = discover(provider.issuer)
        flow = mint_flow_state(config)
        code = provider.issue_code(
            provider.standard_claims(nonce=flow.nonce, email="pat@example.com")
        )
        response = exchange_code(config, endpoints, code=code)
        claims = verify_id_token(
            config, endpoints, id_token=response["id_token"], nonce=flow.nonce,
        )
        assert claims["email"] == "pat@example.com"
        assert provider.token_requests[-1]["redirect_uri"] == (
            "http://yoke.example/v1/auth/oidc/callback"
        )

    def test_exchange_with_wrong_secret_fails_without_leaking_it(self, provider):
        config = self._door(provider)
        wrong = OidcConfig(
            issuer=config.issuer,
            client_id=config.client_id,
            client_secret="not-the-registered-secret",
            redirect_base_url=config.redirect_base_url,
            allow_unverified_email=False,
        )
        endpoints = discover(provider.issuer)
        code = provider.issue_code(provider.standard_claims(nonce="n"))
        with pytest.raises(OidcExchangeError) as excinfo:
            exchange_code(wrong, endpoints, code=code)
        assert "not-the-registered-secret" not in str(excinfo.value)

    def test_unknown_code_rejected(self, provider):
        config = self._door(provider)
        endpoints = discover(provider.issuer)
        with pytest.raises(OidcExchangeError):
            exchange_code(config, endpoints, code="never-issued")

    @pytest.mark.parametrize(
        "skew",
        [
            {"aud": "some-other-client"},
            {"iss": "https://somewhere-else.example"},
            {"exp": int(time.time()) - 30},
        ],
    )
    def test_claim_skew_rejected(self, provider, skew):
        config = self._door(provider)
        endpoints = discover(provider.issuer)
        claims = provider.standard_claims(nonce="the-nonce")
        claims.update(skew)
        with pytest.raises(OidcVerificationError):
            verify_id_token(
                config, endpoints,
                id_token=provider.sign(claims), nonce="the-nonce",
            )

    def test_nonce_mismatch_rejected(self, provider):
        config = self._door(provider)
        endpoints = discover(provider.issuer)
        token = provider.sign(provider.standard_claims(nonce="minted-elsewhere"))
        with pytest.raises(OidcVerificationError):
            verify_id_token(config, endpoints, id_token=token, nonce="expected")

    def test_missing_nonce_rejected(self, provider):
        config = self._door(provider)
        endpoints = discover(provider.issuer)
        token = provider.sign(provider.standard_claims())
        with pytest.raises(OidcVerificationError):
            verify_id_token(config, endpoints, id_token=token, nonce="expected")

    def test_symmetric_token_rejected(self, provider):
        """HS256 signed with the shared client secret must never pass
        JWKS-based verification (algorithm confusion hardening)."""
        config = self._door(provider)
        endpoints = discover(provider.issuer)
        token = provider.sign_symmetric(
            provider.standard_claims(nonce="the-nonce")
        )
        with pytest.raises(OidcVerificationError):
            verify_id_token(config, endpoints, id_token=token, nonce="the-nonce")
