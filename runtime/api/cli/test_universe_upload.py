"""Destination admission, bounded direct upload and URL renewal."""

import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.error import HTTPError
from xml.etree import ElementTree as ET

import pytest

from yoke_cli.commands import universe_upload as upload
from yoke_cli.transport.https import HttpsConnection


class Response(io.BytesIO):
    def __init__(self, body=b"", headers=None):
        super().__init__(body)
        self.headers = headers or {}


def admission(size, *, numbers=None, generation=1, width=2 << 20):
    count = (size + width - 1) // width
    url = f"https://bucket.s3.us-east-1.amazonaws.com/archive?signature={generation}"
    return {
        "upload_id": "same-upload",
        "source_url": url + "&get=1",
        "complete": url + "&complete=1",
        "abort": url + "&abort=1",
        "part_bytes": width,
        "max_bytes": 1 << 30,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "parts": [
            {
                "number": n,
                "bytes": min(width, size - (n - 1) * width),
                "url": url + f"&part={n}",
            }
            for n in (numbers if numbers is not None else range(1, count + 1))
        ],
    }


def setup_upload(monkeypatch, tmp_path, *, failure=None, expired_part=False):
    connection = HttpsConnection(
        "https://app.upyoke.com/api/orgs/destination", "private-token"
    )
    monkeypatch.setattr(upload, "resolve_https_connection", lambda: connection)
    archive = tmp_path / "source.tar"
    body = b"a" * (2 << 20) + b"tail"
    archive.write_bytes(body)
    calls, requests, parts = [], [], []

    def relay(request, actual_connection, **kwargs):
        assert actual_connection == connection
        assert request.function == "universe.upload.create"
        assert kwargs["max_attempts"] == 1
        calls.append(request.payload)
        result = admission(
            len(body),
            numbers=request.payload.get("part_numbers"),
            generation=len(calls),
        )
        return SimpleNamespace(success=True, result=result)

    def open_request(request, **kwargs):
        assert "Authorization" not in request.headers
        assert kwargs["timeout"] <= 60
        requests.append(request)
        if request.method == "PUT":
            if expired_part and len(requests) == 1:
                raise HTTPError(request.full_url, 403, "expired", {}, None)
            chunks = list(request.data)
            assert all(0 < len(chunk) <= 1 << 20 for chunk in chunks)
            assert sum(map(len, chunks)) == int(request.headers["Content-length"])
            parts.append(b"".join(chunks))
            if failure == "put":
                raise OSError("signed-url-must-stay-private")
            return Response(headers={"ETag": f'"etag-{len(parts)}"'})
        if request.method == "POST":
            xml = ET.fromstring(request.data)
            assert [(p.findtext("PartNumber"), p.findtext("ETag")) for p in xml] == [
                ("1", '"etag-1"'),
                ("2", '"etag-2"'),
            ]
            return Response(
                b"<Error><Code>InternalError</Code></Error>"
                if failure == "complete"
                else b"<CompleteMultipartUploadResult/>"
            )
        assert request.method == "DELETE"
        return Response()

    monkeypatch.setattr(upload, "relay_https", relay)
    monkeypatch.setattr(upload, "_STORAGE", SimpleNamespace(open=open_request))
    return archive, body, calls, requests, parts


def test_upload_streams_and_prints_fresh_link_and_import_destination(
    monkeypatch, tmp_path, capsys
):
    archive, body, calls, requests, parts = setup_upload(monkeypatch, tmp_path)
    assert upload.universe_upload([str(archive), "--org", "destination", "--json"]) == 0
    assert b"".join(parts) == body
    assert calls == [
        {"size": len(body)},
        {"size": len(body), "upload_id": "same-upload", "part_numbers": [2]},
    ]
    assert [r.method for r in requests] == ["PUT", "PUT", "POST"]
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert (
        result["dashboard_url"]
        == "https://app.upyoke.com/orgs/destination/organization"
    )
    assert "signature=2" in result["source_url"]
    assert "private-token" not in output.out + output.err


def test_expired_part_refreshes_same_upload_and_replays_remaining_parts(
    monkeypatch, tmp_path
):
    archive, body, calls, _, parts = setup_upload(
        monkeypatch, tmp_path, expired_part=True
    )
    assert upload.universe_upload([str(archive), "--org", "destination"]) == 0
    assert calls[1] == {
        "size": len(body),
        "upload_id": "same-upload",
        "part_numbers": [1, 2],
    }
    assert b"".join(parts) == body


def test_slow_upload_refreshes_before_part(monkeypatch, tmp_path):
    archive, _, calls, _, _ = setup_upload(monkeypatch, tmp_path)
    due = iter([False, True])
    monkeypatch.setattr(upload, "_refresh_due", lambda _: next(due))
    assert upload.universe_upload([str(archive), "--org", "destination"]) == 0
    assert calls[1]["part_numbers"] == [2]
    assert calls[1]["upload_id"] == "same-upload"


@pytest.mark.parametrize("failure", ["put", "complete"])
def test_failure_aborts_and_never_reports_success_or_signed_diagnostics(
    monkeypatch, tmp_path, capsys, failure
):
    archive, _, _, requests, _ = setup_upload(monkeypatch, tmp_path, failure=failure)
    assert upload.universe_upload([str(archive), "--org", "destination"]) == 1
    assert requests[-1].method == "DELETE"
    output = capsys.readouterr()
    assert not output.out
    assert "upload_" in output.err
    assert "signature=" not in output.err
    assert "must-stay-private" not in output.err


@pytest.mark.parametrize(
    "url,org,code",
    [
        (None, "destination", "upload_hosted_connection_required"),
        (
            "https://self-host.example",
            "destination",
            "upload_hosted_connection_required",
        ),
        ("https://app.upyoke.com/api/orgs/other", "destination", "upload_org_mismatch"),
    ],
)
def test_upload_refuses_wrong_destination_before_admission(
    monkeypatch, tmp_path, capsys, url, org, code
):
    monkeypatch.setattr(
        upload,
        "resolve_https_connection",
        lambda: HttpsConnection(url, "secret") if url else None,
    )
    monkeypatch.setattr(
        upload, "relay_https", lambda *_a, **_k: pytest.fail("must not admit")
    )
    assert upload.universe_upload([str(tmp_path / "missing"), "--org", org]) == 1
    assert code in capsys.readouterr().err


def test_changed_file_aborts_before_completion(monkeypatch, tmp_path):
    archive, _, _, requests, _ = setup_upload(monkeypatch, tmp_path)
    original = upload._put

    def put(*args):
        result = original(*args)
        with archive.open("ab") as sink:
            sink.write(b"changed")
        return result

    monkeypatch.setattr(upload, "_put", put)
    assert upload.universe_upload([str(archive), "--org", "destination"]) == 1
    assert requests[-1].method == "DELETE"
    assert not any(r.method == "POST" for r in requests)
