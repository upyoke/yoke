"""Item create/update CLI commands.

Owns ``create-item`` and ``validate-update`` — both are **internal
validators for the ``/yoke idea`` workflow**, not agent-facing
ticket-creation entrypoints. They only call ``mutations.prepare_*``
to return the planned field writes; they do not insert rows, sync to
GitHub, or release a draft claim. Production callers always enter
through ``/yoke idea``; ``create-item`` is gated outside sanctioned
idea-intake (or test isolation) with a recovery hint that names the
skill — see :mod:`yoke_core.domain.ticket_intake_provenance`.
"""

from __future__ import annotations

import json
import sys

from yoke_core.domain import db_backend
from yoke_core.domain.ticket_intake_provenance import (
    enforce_public_create_allowed,
)
from yoke_core.api.service_client_shared import (
    _get_db_path,
    _get_db_readonly,
    _load_gate_context,
    _load_item_state,
    _mutation_result_to_dict,
    mutations,
)


def cmd_create_item(args: list[str]) -> int:
    """Validate and prepare an item creation — internal idea-intake validator.

    Usage: create-item --title TITLE --type TYPE [--priority PRIORITY]
                       [--project PROJECT] [--deployment-flow FLOW]
                       [--status STATUS] [--idea-intake]

    This is NOT a ticket-creation surface. It calls
    ``mutations.prepare_create`` and returns the planned field writes
    so the ``/yoke idea`` orchestrator can apply them; it does not
    insert rows, sync GitHub, or release a draft claim. Direct calls
    outside sanctioned idea intake (or a test-isolated DB) are
    rejected with the same recovery hint the persistent-create surface
    emits — agents enter via ``/yoke idea``.

    Exit 0: valid, JSON result on stdout
    Exit 1: validation error, JSON error on stdout
    """
    title = None
    item_type = "issue"
    priority = "medium"
    project = None
    deployment_flow = None
    status = None
    provenance = None

    i = 0
    while i < len(args):
        if args[i] == "--title" and i + 1 < len(args):
            title = args[i + 1]
            i += 2
        elif args[i] == "--type" and i + 1 < len(args):
            item_type = args[i + 1]
            i += 2
        elif args[i] == "--priority" and i + 1 < len(args):
            priority = args[i + 1]
            i += 2
        elif args[i] == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif args[i] == "--deployment-flow" and i + 1 < len(args):
            deployment_flow = args[i + 1]
            i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            status = args[i + 1]
            i += 2
        elif args[i] == "--idea-intake":
            provenance = "idea"
            i += 1
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    if title is None:
        print("Usage: create-item --title TITLE [--type TYPE] [--priority PRIORITY] "
              "[--project PROJECT] [--deployment-flow FLOW] "
              "[--status STATUS] [--idea-intake]",
              file=sys.stderr)
        return 2

    try:
        intake_db = _get_db_path()
    except Exception:
        intake_db = None
    intake_block = enforce_public_create_allowed(
        provenance=provenance, db_path=intake_db,
    )
    if intake_block:
        print(json.dumps({
            "success": False,
            "error": intake_block,
            "error_code": "IDEA_INTAKE_REQUIRED",
        }))
        return 1

    from yoke_core.domain.deployment_flow_validator import (
        normalize_deployment_flow_value,
        validate_and_lookup_flow_project,
    )

    deployment_flow = normalize_deployment_flow_value(deployment_flow)
    conn = _get_db_readonly()
    try:
        flow_project, flow_err = validate_and_lookup_flow_project(
            conn, deployment_flow, project
        )
    finally:
        conn.close()

    if flow_err:
        print(json.dumps({
            "success": False,
            "error": flow_err,
            "error_code": "VALIDATION_ERROR",
        }))
        return 1

    result = mutations.prepare_create(
        title=title,
        item_type=item_type,
        priority=priority,
        project=project,
        deployment_flow=deployment_flow,
        flow_project=flow_project,
        status=status,
    )

    print(json.dumps(_mutation_result_to_dict(result)))
    return 0 if result.success else 1


def cmd_update_item(args: list[str]) -> int:
    """Validate and prepare a single-field item update via the shared mutation layer.

    Usage: validate-update <item-id> --field FIELD --value VALUE
                           [--done-nonce-verified] [--force] [--qa-bypass]

    Returns JSON on stdout with the mutation result (field_writes, events).
    The caller (shell adapter) is responsible for applying the DB writes
    and post-update side effects.

    Exit 0: valid, JSON result on stdout
    Exit 1: validation/gate error, JSON error on stdout
    """
    if len(args) < 1:
        print("Usage: validate-update <item-id> --field FIELD --value VALUE "
              "[--done-nonce-verified] [--force] [--qa-bypass]",
              file=sys.stderr)
        return 2

    try:
        item_id = int(args[0])
    except ValueError:
        print(json.dumps({
            "success": False,
            "error": f"Item ID must be an integer, got '{args[0]}'",
            "error_code": "VALIDATION_ERROR",
        }))
        return 1

    field_name = None
    value = None
    done_nonce_verified = False
    force = False
    qa_bypass = False

    i = 1
    while i < len(args):
        if args[i] == "--field" and i + 1 < len(args):
            field_name = args[i + 1]
            i += 2
        elif args[i] == "--value" and i + 1 < len(args):
            value = args[i + 1]
            i += 2
        elif args[i] == "--done-nonce-verified":
            done_nonce_verified = True
            i += 1
        elif args[i] == "--force":
            force = True
            i += 1
        elif args[i] == "--qa-bypass":
            qa_bypass = True
            i += 1
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    if field_name is None or value is None:
        print("Usage: validate-update <item-id> --field FIELD --value VALUE "
              "[--done-nonce-verified] [--force] [--qa-bypass]",
              file=sys.stderr)
        return 2

    conn = _get_db_readonly()
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT i.*, pr.slug AS project FROM items i "
            "JOIN projects pr ON pr.id = i.project_id "
            f"WHERE i.id = {p}",
            (item_id,),
        ).fetchone()
        if row is None:
            print(json.dumps({
                "success": False,
                "error": f"Item YOK-{item_id} not found",
                "error_code": "NOT_FOUND",
            }))
            return 1

        item_dict = dict(row)
        item_state = _load_item_state(conn, item_id)
        if item_state is None:
            print(json.dumps({
                "success": False,
                "error": f"Item YOK-{item_id} not found",
                "error_code": "NOT_FOUND",
            }))
            return 1

        if field_name == "deployment_flow" and value:
            from yoke_core.domain.deployment_flow_validator import (
                validate_and_lookup_flow_project,
            )

            _flow_project, flow_err = validate_and_lookup_flow_project(
                conn, value, item_dict.get("project")
            )
            if flow_err:
                print(json.dumps({
                    "success": False,
                    "error": flow_err,
                    "error_code": "VALIDATION_ERROR",
                    "preflight_only": True,
                }))
                return 1

        target_status = value if field_name == "status" else None

        gate = _load_gate_context(
            conn,
            item_dict,
            target_status=target_status,
            deployment_flow_value=value if field_name == "deployment_flow" else None,
            deployed_to_value=value if field_name == "deployed_to" else None,
            done_nonce_verified=done_nonce_verified,
            force=force,
            qa_bypass=qa_bypass,
        )

        result = mutations.prepare_update(
            item=item_state,
            field_name=field_name,
            value=value,
            gate=gate,
        )

        payload = _mutation_result_to_dict(result)
        payload["preflight_only"] = True
        print(json.dumps(payload))
        return 0 if result.success else 1
    finally:
        conn.close()
