"""Project-owned declarations for browser actions emitted by a QA flow."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from yoke_core.domain.project_checkout_locations import checkout_for_project_id

_LIST_FIELDS = frozenset({"origins", "paths", "rejected_statuses", "denial_text"})
_FIELDS = _LIST_FIELDS | {
    "url_label",
    "code_label",
    "code_pattern",
    "query_parameter",
    "approval_target",
}


def load_browser_flow(project_id: int, name: str) -> dict:
    """Read a project's registered checkout, using its current lane when present."""
    mapped = checkout_for_project_id(project_id)
    if not mapped:
        raise ValueError(
            "browser_flow_project_checkout_missing: register the project's checkout before machine QA"
        )
    root = Path(mapped).resolve()
    current = Path.cwd().resolve()
    if current == root or root in current.parents:
        root = next(
            (
                parent
                for parent in (current, *current.parents)
                if (parent / ".git").exists()
            ),
            root,
        )
    path = root / ".yoke" / "browser-flows.json"
    try:
        content = path.read_bytes()
        document = json.loads(content)
        sign_ins = document["required_sign_ins"]
        if (
            not isinstance(sign_ins, list)
            or not sign_ins
            or any(
                not isinstance(value, str) or not value.strip() or len(value) > 2048
                for value in sign_ins
            )
        ):
            raise ValueError("list the project's needed application sign-ins")
        flow = document[name]
        flow = validate_browser_flow(flow)
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError(
            f"browser_flow_declaration_missing_or_invalid: declare {name!r} in {path}, then retry this case"
        ) from None
    return {
        **flow,
        "required_sign_ins": sign_ins,
        "declaration_sha256": hashlib.sha256(content).hexdigest(),
    }


def validate_browser_flow(flow: object) -> dict:
    if not isinstance(flow, dict) or set(flow) != _FIELDS:
        raise ValueError("browser flow must declare every registered field")
    for key in _LIST_FIELDS:
        values = flow[key]
        if (
            not isinstance(values, list)
            or not values
            or any(
                not isinstance(value, str) or not value or len(value) > 2048
                for value in values
            )
        ):
            raise ValueError("browser flow lists must contain bounded nonempty strings")
    for origin in flow["origins"]:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("browser flow origins must be literal HTTPS origins")
    for path in flow["paths"]:
        parsed = urlsplit(path)
        if (
            not path.startswith("/")
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.scheme
        ):
            raise ValueError("browser flow paths must be literal application paths")
    for key in _FIELDS - _LIST_FIELDS:
        if not isinstance(flow[key], str) or not flow[key] or len(flow[key]) > 256:
            raise ValueError("browser flow text must be bounded and nonempty")
    try:
        re.compile(flow["code_pattern"])
    except re.error:
        raise ValueError(
            "browser flow code_pattern must be a valid regular expression"
        ) from None
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", flow["query_parameter"]) is None:
        raise ValueError(
            "browser flow query_parameter must be a literal parameter name"
        )
    return dict(flow)
