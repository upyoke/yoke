"""SigV4 presigning pinned against the documented AWS worked example."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from yoke_core.domain.s3_presign import (
    AwsCredentials,
    bucket_host,
    presign_for_host,
    presign_s3_url,
)

# The worked presigned-GET example from the AWS Signature Version 4
# documentation ("Authenticating Requests: Using Query Parameters").
_DOC_CREDS = AwsCredentials(
    access_key_id="AKIAIOSFODNN7EXAMPLE",
    secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
)
_DOC_NOW = datetime(2013, 5, 24, 0, 0, 0, tzinfo=timezone.utc)
_DOC_SIGNATURE = (
    "aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
)


class TestDocumentedVector:
    def test_signature_matches_aws_documentation(self) -> None:
        url = presign_for_host(
            method="GET",
            host="examplebucket.s3.amazonaws.com",
            canonical_uri="/test.txt",
            region="us-east-1",
            credentials=_DOC_CREDS,
            expires_s=86400,
            now=_DOC_NOW,
        )
        query = parse_qs(urlsplit(url).query)
        assert query["X-Amz-Signature"] == [_DOC_SIGNATURE]
        assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
        assert query["X-Amz-Credential"] == [
            "AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request"
        ]
        assert query["X-Amz-Date"] == ["20130524T000000Z"]
        assert query["X-Amz-Expires"] == ["86400"]
        assert query["X-Amz-SignedHeaders"] == ["host"]


class TestPresignS3Url:
    def test_put_url_shape(self) -> None:
        url = presign_s3_url(
            method="PUT",
            bucket="yoke-prod-artifacts",
            key="qa-artifacts/yoke/9/12/home.png",
            region="us-east-1",
            credentials=_DOC_CREDS,
            expires_s=900,
            now=_DOC_NOW,
        )
        parts = urlsplit(url)
        assert parts.scheme == "https"
        assert parts.netloc == (
            "yoke-prod-artifacts.s3.us-east-1.amazonaws.com"
        )
        assert parts.path == "/qa-artifacts/yoke/9/12/home.png"
        query = parse_qs(parts.query)
        assert query["X-Amz-Expires"] == ["900"]
        assert len(query["X-Amz-Signature"][0]) == 64

    def test_deterministic_for_fixed_inputs(self) -> None:
        kwargs = dict(
            method="PUT", bucket="b", key="k/x.png", region="eu-west-1",
            credentials=_DOC_CREDS, expires_s=600, now=_DOC_NOW,
        )
        assert presign_s3_url(**kwargs) == presign_s3_url(**kwargs)

    def test_session_token_is_signed_in(self) -> None:
        creds = AwsCredentials(
            access_key_id="AKIDEXAMPLE",
            secret_access_key="secret",
            session_token="tok/with+special=chars",
        )
        url = presign_s3_url(
            method="PUT", bucket="b", key="k.png", region="us-east-1",
            credentials=creds, now=_DOC_NOW,
        )
        query = parse_qs(urlsplit(url).query)
        assert query["X-Amz-Security-Token"] == ["tok/with+special=chars"]

    def test_key_segments_are_uri_encoded(self) -> None:
        url = presign_s3_url(
            method="PUT", bucket="b", key="qa-artifacts/p/1/2/home page.png",
            region="us-east-1", credentials=_DOC_CREDS, now=_DOC_NOW,
        )
        assert "/qa-artifacts/p/1/2/home%20page.png?" in url

    def test_bucket_host_is_regional_virtual_hosted(self) -> None:
        assert bucket_host("bkt", "ap-southeast-2") == (
            "bkt.s3.ap-southeast-2.amazonaws.com"
        )
