"""Test-mode fake-response loader for :mod:`gh_rest_transport`.

Production code never touches this module; the transport reaches in only
when :envvar:`YOKE_REST_FAKE_DIR` is set. Tests write a JSON file per
expected request keyed by ``<METHOD>_<sanitised-path-and-query>.json`` so
the merge engine's subprocess-driven tests have an analog of the legacy
``MOCK_GH_LOG`` infrastructure for the REST transport.

Each response JSON may also carry an optional top-level ``side_effect``
key whose value is a shell command. The loader runs it after returning
the canned response — useful for simulating server-side effects that
end-to-end tests rely on (for example, the GitHub merge endpoint
actually merging the head into the base; the side-effect command does
the equivalent ``git push origin`` so the engine's downstream
verification finds the merge in origin history).

When :envvar:`YOKE_REST_FAKE_LOG` is set, every request handled by
this loader is appended to the named log file in
``<METHOD> <path>[?query]`` form -- the REST analog of the legacy
``MOCK_GH_LOG`` so end-to-end tests can grep for expected REST calls.
When :envvar:`YOKE_REST_FAKE_DEFAULT_OK` is set, missing canned-response
files default to a 200 OK with an empty JSON body / empty list so
end-to-end tests do not need to pre-author a file per endpoint hit.
"""

from __future__ import annotations

import json as _json
import os
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yoke_core.domain.gh_rest_transport import RestRequest, RestResponse


FAKE_DIR_ENV = "YOKE_REST_FAKE_DIR"
FAKE_LOG_ENV = "YOKE_REST_FAKE_LOG"
FAKE_DEFAULT_OK_ENV = "YOKE_REST_FAKE_DEFAULT_OK"

_FAKE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")


def fake_response_filename(req: "RestRequest") -> str:
    """Map a request to a canned-response filename.

    Naming scheme: ``<METHOD>_<sanitised-path[?sanitised-query]>.json``.
    Tests write the file; the transport reads it when
    :envvar:`YOKE_REST_FAKE_DIR` is set.
    """
    method = req.method.upper()
    path = req.path
    if req.query:
        query_str = "&".join(f"{k}={v}" for k, v in sorted(req.query.items()))
        path = f"{path}?{query_str}"
    sanitised = _FAKE_FILENAME_RE.sub("_", path)
    sanitised = sanitised.strip("_") or "root"
    return f"{method}_{sanitised}.json"


def _record_request(req: "RestRequest") -> None:
    """Append a one-line ``<METHOD> <path>[?query]`` entry to the fake-log file."""
    log_path = os.environ.get(FAKE_LOG_ENV, "").strip()
    if not log_path:
        return
    line = f"{req.method.upper()} {req.path}"
    if req.query:
        query_str = "&".join(f"{k}={v}" for k, v in sorted(req.query.items()))
        line += f"?{query_str}"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_fake_response(req: "RestRequest", fake_dir: str) -> "RestResponse":
    """Read a canned response from ``fake_dir`` for ``req``.

    File format::

        {"status": int, "headers": {str: str}, "body": <json>}

    Missing files raise :class:`RestTransportError` so the test surfaces
    the missing canned response loudly instead of silently failing closed.
    Status >= 400 routes through :func:`gh_rest_transport._classify_http_error`
    so callers get the same typed-error envelope they would from real HTTP.
    """
    from yoke_core.domain.gh_rest_transport import (
        RestResponse,
        RestTransportError,
        _classify_http_error,
    )

    _record_request(req)

    name = fake_response_filename(req)
    path = Path(fake_dir) / name
    if not path.is_file():
        if os.environ.get(FAKE_DEFAULT_OK_ENV, "").strip():
            # Default-OK mode: empty list for GET, empty dict otherwise.
            body = [] if req.method.upper() == "GET" else {}
            return RestResponse(status=200, headers={}, body=body)
        raise RestTransportError(
            f"REST fake response file not found: {path} "
            f"(method={req.method!r} path={req.path!r})"
        )
    try:
        payload = _json.loads(path.read_text())
    except ValueError as exc:
        raise RestTransportError(
            f"REST fake response file is not valid JSON: {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise RestTransportError(
            f"REST fake response file must be a JSON object: {path}"
        )
    status = int(payload.get("status", 200))
    headers_raw = payload.get("headers") or {}
    headers = {str(k).lower(): str(v) for k, v in dict(headers_raw).items()}
    body = payload.get("body", "")
    side_effect = payload.get("side_effect")
    if isinstance(side_effect, str) and side_effect.strip():
        subprocess.run(side_effect, shell=True, check=False)
    if status >= 400:
        body_text = body if isinstance(body, str) else _json.dumps(body)
        raise _classify_http_error(status, body_text, headers)
    return RestResponse(status=status, headers=headers, body=body)
