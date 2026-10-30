"""Stream an archive to an org-bound signed multipart admission."""

import argparse
import http.client
import json
import os
import re
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from xml.etree import ElementTree as ET

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.config.onboard_destinations import is_hosted_url
from yoke_cli.transport.dispatcher import build_actor
from yoke_cli.transport.https import (
    TransportError,
    relay_https,
    resolve_https_connection,
)
from yoke_cli.transport.https_urlopen import NoRedirect
from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef

UPLOAD_USAGE = "yoke universe upload ARCHIVE --org SLUG [--json]"
_STORAGE = build_opener(ProxyHandler({}), NoRedirect())


class UploadRefused(RuntimeError):
    pass


def _invalid():
    return UploadRefused(
        "upload_contract_invalid: update the CLI and hosted service, then retry upload"
    )


def _signed_url(value):
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and not parsed.fragment
            and parsed.query
        ):
            return value
    except (TypeError, ValueError):
        pass
    raise _invalid()


def _admit(connection, size, *, previous=None, numbers=None):
    payload = {"size": size}
    if previous:
        payload.update(upload_id=previous["upload_id"], part_numbers=numbers)
    response = relay_https(
        FunctionCallRequest(
            function="universe.upload.create",
            actor=build_actor(),
            target=TargetRef(kind="global"),
            payload=payload,
            request_id=str(uuid.uuid4()),
        ),
        connection,
        max_attempts=1,
    )
    if not response.success:
        code = response.error.code if response.error else "upload_admission_failed"
        raise UploadRefused(
            f"{code}: check the destination connection, org admin permission and hosted service health, then retry upload"
        )
    result = response.result
    try:
        width = result["part_bytes"]
        if type(width) is not int or width <= 0:
            raise _invalid()
        count = (size + width - 1) // width
        expected = numbers if numbers is not None else list(range(1, count + 1))
        if (
            not isinstance(result["upload_id"], str)
            or not result["upload_id"]
            or type(result["max_bytes"]) is not int
            or size > result["max_bytes"]
            or [p["number"] for p in result["parts"]] != expected
        ):
            raise _invalid()
        for part in result["parts"]:
            if (
                type(part["number"]) is not int
                or type(part["bytes"]) is not int
                or part["bytes"] != min(width, size - (part["number"] - 1) * width)
            ):
                raise _invalid()
            _signed_url(part["url"])
        for name in ("source_url", "complete", "abort"):
            _signed_url(result[name])
        expiry = datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise _invalid()
        if previous and (
            result["upload_id"] != previous["upload_id"]
            or width != previous["part_bytes"]
        ):
            raise _invalid()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise _invalid() from None
    return result


def _refresh_due(admission):
    expiry = datetime.fromisoformat(admission["expires_at"].replace("Z", "+00:00"))
    return (expiry - datetime.now(timezone.utc)).total_seconds() < 300


def _chunks(source, length):
    while length:
        chunk = source.read(min(length, 1 << 20))
        if not chunk:
            raise UploadRefused(
                "upload_archive_changed: export a new archive and retry upload"
            )
        length -= len(chunk)
        yield chunk


def _put(source, admission, part):
    source.seek((part["number"] - 1) * admission["part_bytes"])
    request = Request(
        part["url"],
        method="PUT",
        data=_chunks(source, part["bytes"]),
        headers={"Content-Length": str(part["bytes"])},
    )
    with _STORAGE.open(request, timeout=60) as response:
        etag = response.headers.get("ETag")
        if not etag or len(etag) > 1024:
            raise UploadRefused(
                "upload_etag_missing: check storage access and retry upload"
            )
        return etag


def _complete(admission, etags):
    root = ET.Element("CompleteMultipartUpload")
    for number, etag in etags:
        part = ET.SubElement(root, "Part")
        ET.SubElement(part, "PartNumber").text = str(number)
        ET.SubElement(part, "ETag").text = etag
    request = Request(
        admission["complete"],
        method="POST",
        data=ET.tostring(root),
        headers={"Content-Type": "application/xml"},
    )
    with _STORAGE.open(request, timeout=60) as response:
        # S3 can send HTTP 200 before reporting a completion error in the body.
        body = response.read(65537)
    try:
        if (
            len(body) > 65536
            or ET.fromstring(body).tag.split("}")[-1] != "CompleteMultipartUploadResult"
        ):
            raise ValueError()
    except (ValueError, ET.ParseError):
        raise UploadRefused(
            "upload_complete_failed: check storage access and retry upload"
        ) from None


def _upload(source, connection, size):
    original = os.fstat(source.fileno())
    admission = _admit(connection, size)
    try:
        count = len(admission["parts"])
        etags = []
        for number in range(1, count + 1):
            remaining = list(range(number, count + 1))
            if _refresh_due(admission):
                admission = _admit(
                    connection, size, previous=admission, numbers=remaining
                )
            part = next(p for p in admission["parts"] if p["number"] == number)
            try:
                etag = _put(source, admission, part)
            except HTTPError as exc:
                if exc.code != 403:
                    raise
                # A slow part can outlive its signature. Refresh and replay only it.
                admission = _admit(
                    connection, size, previous=admission, numbers=remaining
                )
                etag = _put(source, admission, admission["parts"][0])
            etags.append((number, etag))
            print(f"Uploaded part {number} of {count}.", file=sys.stderr)
        current = os.fstat(source.fileno())
        if (current.st_size, current.st_mtime_ns) != (
            original.st_size,
            original.st_mtime_ns,
        ):
            raise UploadRefused(
                "upload_archive_changed: export a new archive and retry upload"
            )
        # Give Import a fresh link even after a multi-hour transfer.
        admission = _admit(connection, size, previous=admission, numbers=[count])
        _complete(admission, etags)
        return admission
    except BaseException:
        try:
            request = Request(admission["abort"], method="DELETE")
            with _STORAGE.open(request, timeout=30):
                pass
        except (OSError, http.client.HTTPException):
            print(
                "upload_abort_failed: storage lifecycle will remove unfinished parts; check storage access before retrying.",
                file=sys.stderr,
            )
        raise


def universe_upload(args):
    parser = argparse.ArgumentParser(
        prog="yoke universe upload",
        description=(
            "Upload an archive directly to storage, then finish Import on the destination dashboard. "
            "Select the destination org's hosted connection with yoke --env DESTINATION."
        ),
    )
    parser.add_argument(
        "archive",
        metavar="ARCHIVE",
        type=Path,
        help="Portable universe archive to upload.",
    )
    parser.add_argument(
        "--org",
        metavar="SLUG",
        required=True,
        help="Destination org matching the selected hosted connection.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="Print the signed link, expiry and dashboard URL as JSON.",
    )
    parsed = parse_or_usage_error(parser, args, UPLOAD_USAGE)
    if parsed is None:
        return 2
    try:
        connection = resolve_https_connection()
        if connection is None or not is_hosted_url(connection.api_url):
            raise UploadRefused(
                "upload_hosted_connection_required: connect to the destination org, then use `yoke --env DESTINATION universe upload ARCHIVE --org SLUG`"
            )
        url = urlsplit(connection.api_url)
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9-]*", parsed.org)
            or url.path.rstrip("/") != f"/api/orgs/{parsed.org}"
        ):
            raise UploadRefused(
                "upload_org_mismatch: select the hosted connection for --org with `yoke --env DESTINATION universe upload ARCHIVE --org SLUG`"
            )
        if not stat.S_ISREG(parsed.archive.stat().st_mode):
            raise UploadRefused(
                "upload_archive_invalid: choose a nonempty archive file and retry upload"
            )
        with parsed.archive.open("rb") as source:
            size = os.fstat(source.fileno()).st_size
            if size <= 0 or not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise UploadRefused(
                    "upload_archive_invalid: choose a nonempty archive file and retry upload"
                )
            admission = _upload(source, connection, size)
        dashboard = f"{url.scheme}://{url.netloc}/orgs/{parsed.org}/organization"
        report = {
            "source_url": admission["source_url"],
            "expires_at": admission["expires_at"],
            "dashboard_url": dashboard,
            "bytes": size,
        }
    except (UploadRefused, TransportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (OSError, URLError, http.client.HTTPException, ValueError):
        print(
            "error: upload_failed: check the archive file, network and storage access, then retry upload; the source stays paused until Resume.",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(report)
        if parsed.json_mode
        else (
            f"Archive uploaded. Link expires at {report['expires_at']}.\n"
            f"{report['source_url']}\nOpen {dashboard}, choose Import and paste this link."
        )
    )
    return 0
