"""Envelope and payload validation for the Project Structure aggregate.

Pure functions over the constants imported from
:mod:`yoke_core.domain.project_structure`. No DB access.
"""

from __future__ import annotations

from typing import Any, Dict

from yoke_contracts.hosting_posture import (
    DECLARED_HOSTING_POSTURES,
    HOSTING_POSTURE_FAMILY,
    POSTURE_UNDECIDED,
)
from yoke_core.domain.project_structure import (
    ALL_FAMILIES,
    EMPTY_SLOT,
    NET_NEW_FAMILIES,
    PATH_SELECTOR_KINDS,
    PROJECT_ATTACHMENT_TOKEN,
    ValidationError,
)


def _require_known_family(family: str) -> None:
    if family not in ALL_FAMILIES:
        raise ValidationError(
            f"Unknown family '{family}'. "
            f"Known families: {', '.join(ALL_FAMILIES)}."
        )


def _validate_envelope(
    family: str,
    attachment_value: str,
    attachment_kind: str,
    entry_key: str,
) -> None:
    """Validate that an op's envelope fits the family's declared vocabulary.

    Raises :class:`ValidationError` on any mismatch.
    """
    env = NET_NEW_FAMILIES[family]
    branch = env["attachment"]
    multiplicity = env["multiplicity"]
    locked_kind = env["locked_kind"]

    # Attachment branch validation
    if branch == "project":
        if attachment_value != PROJECT_ATTACHMENT_TOKEN:
            raise ValidationError(
                f"Family '{family}' has attachment branch 'project' — "
                f"attachment must be the literal token 'project' "
                f"(got '{attachment_value}')."
            )
        if attachment_kind not in ("", EMPTY_SLOT):
            raise ValidationError(
                f"Family '{family}' is project-attached; attachment_kind "
                f"must be omitted (got '{attachment_kind}')."
            )
    elif branch == "path_selector":
        if not attachment_value or attachment_value == PROJECT_ATTACHMENT_TOKEN:
            raise ValidationError(
                f"Family '{family}' has attachment branch 'path_selector' — "
                f"attachment must be a non-empty path/glob/subtree value "
                f"(got '{attachment_value}')."
            )
        if attachment_kind not in PATH_SELECTOR_KINDS:
            raise ValidationError(
                f"Family '{family}' is path_selector-attached; "
                f"attachment_kind must be one of "
                f"{', '.join(PATH_SELECTOR_KINDS)} (got '{attachment_kind}')."
            )
        if locked_kind is not None and attachment_kind != locked_kind:
            raise ValidationError(
                f"Family '{family}' is locked to attachment_kind "
                f"'{locked_kind}' (got '{attachment_kind}')."
            )
    else:  # pragma: no cover - constitution invariant
        raise ValidationError(
            f"Unknown attachment branch '{branch}' for family '{family}'."
        )

    # Multiplicity validation
    if multiplicity == "singleton":
        if entry_key not in ("", EMPTY_SLOT):
            raise ValidationError(
                f"Family '{family}' is singleton; entry_key must be omitted "
                f"(got '{entry_key}')."
            )
    elif multiplicity == "keyed_set":
        if not entry_key:
            raise ValidationError(
                f"Family '{family}' is keyed_set; entry_key is required."
            )
    else:  # pragma: no cover - constitution invariant
        raise ValidationError(
            f"Unknown multiplicity '{multiplicity}' for family '{family}'."
        )


def _validate_payload(family: str, payload: Any) -> Dict[str, Any]:
    """Validate per-family payload.

    Returns the normalized payload (a dict).  Raises :class:`ValidationError`
    on mismatch.  Payload validators are deliberately lightweight — they
    enforce structural expectations (dict) and the handful of semantic
    constraints called out by the constitution (for example, ``mappings``
    must carry an ``area_name``).
    """
    if not isinstance(payload, dict):
        raise ValidationError(
            f"Family '{family}' payload must be a JSON object (got "
            f"{type(payload).__name__})."
        )

    if family == "mappings":
        area_name = payload.get("area_name")
        if not isinstance(area_name, str) or not area_name:
            raise ValidationError(
                "Family 'mappings' payload must contain a non-empty "
                "'area_name' string referencing an 'areas' entry_key."
            )
    elif family == "integration_targets":
        # entry_key names the target; payload may declare branch patterns
        # or coordination metadata. Reject empty payloads so entries are
        # self-describing.
        if not payload:
            raise ValidationError(
                "Family 'integration_targets' payload must be non-empty; "
                "declare branch_pattern or coordination metadata."
            )
    elif family == "deploy_defaults":
        # Singleton per project. Payload must declare a non-empty
        # ``deployment_flow`` string naming a ``deployment_flows.id``.
        # Absence of the entry (no row) means "no project default" — callers
        # never write an empty payload to express that state; they omit the
        # entry entirely or remove it.
        flow = payload.get("deployment_flow")
        if not isinstance(flow, str) or not flow:
            raise ValidationError(
                "Family 'deploy_defaults' payload must contain a non-empty "
                "'deployment_flow' string referencing a deployment_flows.id."
            )
    elif family == "context_routing":
        # Keyed-set per project; entry_key="always" is the project-wide set,
        # any other entry_key is a topic name. Payload must contain a
        # non-empty list of project-relative file path strings under "docs".
        docs = payload.get("docs")
        if not isinstance(docs, list) or not docs:
            raise ValidationError(
                "Family 'context_routing' payload must contain a non-empty "
                "'docs' list of project-relative file path strings."
            )
        for idx, doc in enumerate(docs):
            if not isinstance(doc, str) or not doc.strip():
                raise ValidationError(
                    f"Family 'context_routing' payload 'docs'[{idx}] must "
                    f"be a non-empty string (got {type(doc).__name__})."
                )
    elif family == HOSTING_POSTURE_FAMILY:
        # Singleton per project. ``posture`` names one declared arrangement;
        # ``undecided`` is expressed by having no row at all, so storing it
        # would give one state two spellings. ``provider`` and ``note`` are
        # operator prose recording where the code actually runs — Yoke never
        # acts on them, so they are free text or absent.
        posture = payload.get("posture")
        if posture not in DECLARED_HOSTING_POSTURES:
            raise ValidationError(
                f"Family '{HOSTING_POSTURE_FAMILY}' payload must contain a "
                f"'posture' of "
                f"{' or '.join(repr(p) for p in DECLARED_HOSTING_POSTURES)}. "
                f"'{POSTURE_UNDECIDED}' is not stored — remove the entry "
                f"instead."
            )
        for key in ("provider", "note"):
            value = payload.get(key)
            if value is not None and not isinstance(value, str):
                raise ValidationError(
                    f"Family '{HOSTING_POSTURE_FAMILY}' payload '{key}' must "
                    f"be a string or absent (got {type(value).__name__})."
                )
    elif family == "architecture_model":
        # Sibling module owns the per-key validation tree to keep this
        # file under the 350-line cap.
        from yoke_core.domain.architecture_model import (
            validate_payload as _validate_architecture_model_payload,
        )
        _validate_architecture_model_payload(payload)

    return payload
