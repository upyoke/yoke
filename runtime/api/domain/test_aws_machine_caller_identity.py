"""Machine-local AWS caller identity without an AWS CLI subprocess."""

from __future__ import annotations

from typing import Any

import pytest

from yoke_core.domain import aws_machine_caller_identity as caller_identity

ACCESS_KEY = "AKIAEXAMPLEEXAMPLE12"
SECRET_KEY = "never-print-this-secret"
SESSION_TOKEN = "never-print-this-session-token"


class _StsClient:
    def __init__(self, result: Any = None, failure: BaseException | None = None):
        self._result = result
        self._failure = failure

    def get_caller_identity(self) -> Any:
        if self._failure is not None:
            raise self._failure
        return self._result


def _capability_env(*_args: Any, **_kwargs: Any) -> dict[str, str]:
    return {
        "AWS_ACCESS_KEY_ID": ACCESS_KEY,
        "AWS_SECRET_ACCESS_KEY": SECRET_KEY,
        "AWS_SESSION_TOKEN": SESSION_TOKEN,
        "AWS_REGION": "eu-west-1",
    }


def test_verifier_passes_explicit_machine_credentials_to_boto3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        caller_identity.deploy_remote,
        "aws_machine_capability_env",
        _capability_env,
    )
    monkeypatch.setenv("PATH", "")
    captured: dict[str, Any] = {}

    def factory(service_name: str, **kwargs: Any) -> _StsClient:
        captured["service_name"] = service_name
        captured.update(kwargs)
        return _StsClient({
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/existing-deployer",
            "UserId": "AIDAEXAMPLE",
        })

    identity = caller_identity.verify_machine_caller_identity(
        "acme-app", "ignored-by-resolver", client_factory=factory,
    )

    assert identity == caller_identity.CallerIdentity(
        account="123456789012", identity="existing-deployer",
    )
    assert captured["service_name"] == "sts"
    assert captured["aws_access_key_id"] == ACCESS_KEY
    assert captured["aws_secret_access_key"] == SECRET_KEY
    assert captured["aws_session_token"] == SESSION_TOKEN
    assert captured["region_name"] == "eu-west-1"
    assert captured["config"].connect_timeout == 5
    assert captured["config"].read_timeout == 15
    assert SECRET_KEY not in repr(identity)
    assert SESSION_TOKEN not in repr(identity)


def test_session_token_is_omitted_when_the_resolver_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _capability_env()
    env.pop("AWS_SESSION_TOKEN")
    monkeypatch.setattr(
        caller_identity.deploy_remote,
        "aws_machine_capability_env",
        lambda *_args, **_kwargs: env,
    )
    captured: dict[str, Any] = {}

    def factory(_service_name: str, **kwargs: Any) -> _StsClient:
        captured.update(kwargs)
        return _StsClient({
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/deployer",
        })

    caller_identity.verify_machine_caller_identity(
        "acme-app", "eu-west-1", client_factory=factory,
    )

    assert "aws_session_token" not in captured


def test_aws_failure_names_only_the_safe_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidCredential(RuntimeError):
        response = {
            "Error": {
                "Code": "InvalidClientTokenId",
                "Message": f"request included {SECRET_KEY}",
            }
        }

    monkeypatch.setattr(
        caller_identity.deploy_remote,
        "aws_machine_capability_env",
        _capability_env,
    )

    with pytest.raises(
        caller_identity.CallerIdentityVerificationError,
        match="InvalidClientTokenId",
    ) as failure:
        caller_identity.verify_machine_caller_identity(
            "acme-app",
            "eu-west-1",
            client_factory=lambda *_args, **_kwargs: _StsClient(
                failure=InvalidCredential(f"leaked {SESSION_TOKEN}")
            ),
        )

    assert SECRET_KEY not in str(failure.value)
    assert SESSION_TOKEN not in str(failure.value)


def test_connectivity_failure_is_named_without_raw_request_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NetworkUnavailable(RuntimeError):
        pass

    monkeypatch.setattr(
        caller_identity.deploy_remote,
        "aws_machine_capability_env",
        _capability_env,
    )

    with pytest.raises(
        caller_identity.CallerIdentityVerificationError,
        match="NetworkUnavailable",
    ) as failure:
        caller_identity.verify_machine_caller_identity(
            "acme-app",
            "eu-west-1",
            client_factory=lambda *_args, **_kwargs: _StsClient(
                failure=NetworkUnavailable(f"endpoint request used {SECRET_KEY}")
            ),
        )

    assert SECRET_KEY not in str(failure.value)


@pytest.mark.parametrize("payload", [None, {}, {"Account": "123456789012"}])
def test_malformed_identity_is_rejected_without_echoing_payload(
    monkeypatch: pytest.MonkeyPatch,
    payload: Any,
) -> None:
    monkeypatch.setattr(
        caller_identity.deploy_remote,
        "aws_machine_capability_env",
        _capability_env,
    )

    with pytest.raises(caller_identity.CallerIdentityVerificationError):
        caller_identity.verify_machine_caller_identity(
            "acme-app",
            "eu-west-1",
            client_factory=lambda *_args, **_kwargs: _StsClient(payload),
        )
