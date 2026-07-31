"""Machine-state and service validators for Machine QA fixtures."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any
from urllib.parse import urlsplit

from yoke_core.domain.machine_qa_fixture_constants import (
    CAMPAIGN_WORKSPACE_PATHS,
    EMPTY_TOKEN_PATH,
    FAKE_TOKEN_PATH,
    HOSTED_STAGE_API_URL,
    INVALID_TOKEN_PATH,
    MANAGED_BLOCK_MARKER,
    MISSING_TOKEN_PATH,
    PATH_IDEMPOTENCE_STARTUP_FILES,
    STAGE_TOKEN_PATH,
    YOKE_BIN,
)
from yoke_core.domain.machine_qa_fixture_assets import FAKE_SERVICE_VARIANTS
from yoke_core.domain.machine_qa_fixture_validation_common import (
    Validator,
    boolean,
    bounded_integer,
    bounded_text,
    exact_keys,
    exact_value,
    operation_error,
)
from yoke_core.domain.machine_qa_fixture_validation_constants import (
    EVIDENCE_NAME_PATTERN,
    EXPECTED_CONNECTIONS,
    PRODUCT_STATE_PATHS,
)


_RELEASE_CHANNEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _distribution_base_url(
    operation_id: str,
    parameters: Mapping[str, Any],
) -> str:
    value = bounded_text(operation_id, parameters, "base_url", max_length=2000)
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise operation_error(
            operation_id,
            "base_url must be a credential-free HTTP(S) endpoint",
        )
    return value.rstrip("/")


def _release_channel(
    operation_id: str,
    parameters: Mapping[str, Any],
) -> str:
    value = bounded_text(operation_id, parameters, "channel", max_length=64)
    if _RELEASE_CHANNEL_PATTERN.fullmatch(value) is None:
        raise operation_error(operation_id, "channel is not a safe release label")
    return value


def _workspace_reset(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "installer-campaign.workspace-reset"
    exact_keys(operation_id, parameters, {"paths"})
    paths = parameters.get("paths")
    if not isinstance(paths, list) or tuple(paths) != CAMPAIGN_WORKSPACE_PATHS:
        raise operation_error(
            operation_id,
            "paths must equal the campaign workspace roster",
        )
    return {"paths": list(CAMPAIGN_WORKSPACE_PATHS)}


def _current_release(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "installer.current-release-prepare"
    exact_keys(
        operation_id,
        parameters,
        {
            "base_url",
            "channel",
            "evidence_name",
            "no_onboard",
            "remove_existing_launcher",
        },
    )
    evidence_name = bounded_text(
        operation_id,
        parameters,
        "evidence_name",
        max_length=80,
    )
    if EVIDENCE_NAME_PATTERN.fullmatch(evidence_name) is None:
        raise operation_error(
            operation_id,
            "evidence_name is not a safe fixture label",
        )
    return {
        "base_url": _distribution_base_url(operation_id, parameters),
        "channel": _release_channel(operation_id, parameters),
        "evidence_name": evidence_name,
        "no_onboard": exact_value(
            operation_id,
            parameters,
            "no_onboard",
            True,
        ),
        "remove_existing_launcher": exact_value(
            operation_id,
            parameters,
            "remove_existing_launcher",
            True,
        ),
    }


def _product_state(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "installer.product-state-reset"
    exact_keys(operation_id, parameters, {"paths"})
    paths = parameters.get("paths")
    if not isinstance(paths, list) or tuple(paths) != PRODUCT_STATE_PATHS:
        raise operation_error(
            operation_id,
            "paths must equal the product-owned roster",
        )
    return {"paths": list(PRODUCT_STATE_PATHS)}


def _path_prepare(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "machine.path-prepare"
    exact_keys(
        operation_id,
        parameters,
        {"apply", "evidence_name", "yoke_bin"},
    )
    evidence_name = bounded_text(
        operation_id,
        parameters,
        "evidence_name",
        max_length=80,
    )
    if EVIDENCE_NAME_PATTERN.fullmatch(evidence_name) is None:
        raise operation_error(
            operation_id,
            "evidence_name is not a safe fixture label",
        )
    return {
        "apply": exact_value(operation_id, parameters, "apply", True),
        "evidence_name": evidence_name,
        "yoke_bin": exact_value(operation_id, parameters, "yoke_bin", YOKE_BIN),
    }


def _path_idempotence(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "machine.path-idempotence-prepare"
    expected = {
        "emit_evidence": True,
        "expected_block_count": 1,
        "managed_block_marker": MANAGED_BLOCK_MARKER,
        "repeats": 2,
        "startup_files": list(PATH_IDEMPOTENCE_STARTUP_FILES),
        "yoke_bin": YOKE_BIN,
    }
    if dict(parameters) != expected:
        raise operation_error(
            operation_id,
            "parameters do not match the registered rerun",
        )
    return expected


def _token_file(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "machine.token-file-prepare"
    exact_keys(
        operation_id,
        parameters,
        {"path", "restore_after", "state"},
        {"source_path"},
    )
    path = bounded_text(operation_id, parameters, "path")
    state = bounded_text(operation_id, parameters, "state")
    restore_after = boolean(operation_id, parameters, "restore_after")
    source = parameters.get("source_path")
    registered = {
        (MISSING_TOKEN_PATH, "missing", False, None),
        (EMPTY_TOKEN_PATH, "empty", False, None),
        (INVALID_TOKEN_PATH, "synthetic-invalid", False, None),
        (FAKE_TOKEN_PATH, "synthetic-valid", False, None),
        ("~/.yoke/secrets/stage.token", "copy", False, STAGE_TOKEN_PATH),
        (
            "~/.yoke/secrets/stage.token",
            "synthetic-invalid",
            True,
            None,
        ),
    }
    if (path, state, restore_after, source) not in registered:
        raise operation_error(
            operation_id,
            "token state/path combination is not registered",
        )
    result = {
        "path": path,
        "restore_after": restore_after,
        "state": state,
    }
    if source is not None:
        result["source_path"] = source
    return result


def _auth_clear(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "machine.yoke-auth-clear"
    if parameters:
        raise operation_error(operation_id, "parameters must be empty")
    return {}


def _connection_prepare(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "machine.yoke-connection-prepare"
    exact_keys(
        operation_id,
        parameters,
        {"active_env", "api_url", "token_path", "transport"},
    )
    api_url = bounded_text(operation_id, parameters, "api_url")
    allowed = {f"http://127.0.0.1:{port}" for _profile, port in FAKE_SERVICE_VARIANTS}
    if api_url not in allowed:
        raise operation_error(
            operation_id,
            "api_url is not a registered fixture endpoint",
        )
    return {
        "active_env": exact_value(
            operation_id,
            parameters,
            "active_env",
            "stage",
        ),
        "api_url": api_url,
        "token_path": exact_value(
            operation_id,
            parameters,
            "token_path",
            FAKE_TOKEN_PATH,
        ),
        "transport": exact_value(
            operation_id,
            parameters,
            "transport",
            "http",
        ),
    }


def _connection_restore(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "machine.yoke-connection-restore"
    expected = {
        "active_env": "stage",
        "api_url": HOSTED_STAGE_API_URL,
        "require_existing_token": True,
        "token_path": "~/.yoke/secrets/stage.token",
    }
    if dict(parameters) != expected:
        raise operation_error(
            operation_id,
            "parameters do not match prepared state",
        )
    return expected


def _connections_prepare(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "machine.yoke-connections-prepare"
    expected = {
        "active_env": "stage",
        "connections": EXPECTED_CONNECTIONS,
    }
    if dict(parameters) != expected:
        raise operation_error(
            operation_id,
            "connections do not match the registered pair",
        )
    return expected


def _yoke_api(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "fixture.yoke-api-start"
    profile = bounded_text(operation_id, parameters, "profile")
    port = bounded_integer(
        operation_id,
        parameters,
        "port",
        minimum=1024,
        maximum=65535,
    )
    variant = FAKE_SERVICE_VARIANTS.get((profile, port))
    if variant is None or dict(parameters) != dict(variant.parameters):
        raise operation_error(
            operation_id,
            "parameters do not name a closed service variant",
        )
    return dict(variant.parameters)


MACHINE_SETUP_VALIDATORS: dict[str, Validator] = {
    "fixture.yoke-api-start": _yoke_api,
    "installer-campaign.workspace-reset": _workspace_reset,
    "installer.current-release-prepare": _current_release,
    "installer.product-state-reset": _product_state,
    "machine.path-idempotence-prepare": _path_idempotence,
    "machine.path-prepare": _path_prepare,
    "machine.token-file-prepare": _token_file,
    "machine.yoke-auth-clear": _auth_clear,
    "machine.yoke-connection-prepare": _connection_prepare,
    "machine.yoke-connection-restore": _connection_restore,
    "machine.yoke-connections-prepare": _connections_prepare,
}


__all__ = ["MACHINE_SETUP_VALIDATORS"]
