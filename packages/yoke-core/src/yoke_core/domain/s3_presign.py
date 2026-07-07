"""Stdlib AWS SigV4 presigned-URL minting for S3 (no boto dependency).

Yoke's dependency set is deliberately small; presigning is a pure
computation (HMAC chain + canonical request), so this module implements
the documented AWS Signature Version 4 query-parameter flow directly with
``hmac``/``hashlib``/``urllib``. Deterministic given fixed credentials and
``now`` — the unit suite pins the worked example from the AWS SigV4
documentation byte-for-byte.

Only the QA artifact-evidence path consumes this today (server-minted
presigned PUTs in the ``qa.artifact.presign`` handler; the client uploads
with plain HTTPS). Credentials come from the project's ``aws-admin``
capability — never ambient shell.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import quote


_ALGORITHM = "AWS4-HMAC-SHA256"
_UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"
DEFAULT_EXPIRES_S = 900


@dataclass(frozen=True)
class AwsCredentials:
    access_key_id: str
    secret_access_key: str
    # STS/instance-profile credentials carry a session token; long-lived
    # capability keys leave it None.
    session_token: Optional[str] = None


def _uri_encode(value: str, *, encode_slash: bool = True) -> str:
    safe = "-._~" if encode_slash else "-._~/"
    return quote(value, safe=safe)


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, date: str, region: str, service: str) -> bytes:
    k_date = _hmac_sha256(f"AWS4{secret}".encode("utf-8"), date)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "aws4_request")


def bucket_host(bucket: str, region: str) -> str:
    """Virtual-hosted-style regional S3 endpoint for *bucket*."""
    return f"{bucket}.s3.{region}.amazonaws.com"


def presign_for_host(
    *,
    method: str,
    host: str,
    canonical_uri: str,
    region: str,
    credentials: AwsCredentials,
    expires_s: int = DEFAULT_EXPIRES_S,
    now: Optional[datetime] = None,
    service: str = "s3",
) -> str:
    """Mint a SigV4 presigned URL against an explicit *host* + URI.

    ``canonical_uri`` is the already-URI-encoded absolute path
    (``/`` + encoded key). The public :func:`presign_s3_url` wrapper builds
    both from a bucket/key pair; this seam exists so the signing math can
    be pinned against the documented AWS example verbatim.
    """
    moment = now or datetime.now(timezone.utc)
    amz_date = moment.strftime("%Y%m%dT%H%M%SZ")
    datestamp = moment.strftime("%Y%m%d")
    scope = f"{datestamp}/{region}/{service}/aws4_request"

    query: Dict[str, str] = {
        "X-Amz-Algorithm": _ALGORITHM,
        "X-Amz-Credential": f"{credentials.access_key_id}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(int(expires_s)),
        "X-Amz-SignedHeaders": "host",
    }
    if credentials.session_token:
        query["X-Amz-Security-Token"] = credentials.session_token
    canonical_query = "&".join(
        f"{_uri_encode(k)}={_uri_encode(v)}" for k, v in sorted(query.items())
    )

    canonical_request = "\n".join(
        (
            method.upper(),
            canonical_uri,
            canonical_query,
            f"host:{host}\n",
            "host",
            _UNSIGNED_PAYLOAD,
        )
    )
    string_to_sign = "\n".join(
        (
            _ALGORITHM,
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        )
    )
    signature = hmac.new(
        _signing_key(
            credentials.secret_access_key, datestamp, region, service
        ),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return (
        f"https://{host}{canonical_uri}?{canonical_query}"
        f"&X-Amz-Signature={signature}"
    )


def presign_s3_url(
    *,
    method: str,
    bucket: str,
    key: str,
    region: str,
    credentials: AwsCredentials,
    expires_s: int = DEFAULT_EXPIRES_S,
    now: Optional[datetime] = None,
) -> str:
    """Mint a presigned ``PUT``/``GET`` URL for ``s3://bucket/key``."""
    return presign_for_host(
        method=method,
        host=bucket_host(bucket, region),
        canonical_uri="/" + _uri_encode(key, encode_slash=False),
        region=region,
        credentials=credentials,
        expires_s=expires_s,
        now=now,
    )


__all__ = [
    "AwsCredentials",
    "DEFAULT_EXPIRES_S",
    "bucket_host",
    "presign_for_host",
    "presign_s3_url",
]
