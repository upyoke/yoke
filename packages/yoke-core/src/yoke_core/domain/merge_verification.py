"""Project-level merge verification policy accessor.

The ``merge_verification`` Project Structure family stores at most one
pre-merge verification policy per project. The policy owns both the shell
command and its timeout budget because project-specific merge verification is
not complete if command selection is project-specific but timeout selection is
global. Absence of the entry is a valid state meaning "no merge verification
command configured"; the merge engine prints an explicit skip log line and
proceeds without running any project test command in that case. If an older or
manually edited row contains an empty ``command`` string, readers treat it as
absent; sanctioned writes remove the row instead of storing an empty command.

Why this is its own family rather than a scope on ``command_definitions``:
``command_definitions.{quick, full, e2e, smoke}`` is the agent-facing test
surface (Tester dispatch, Engineer dispatch, doctor health checks,
stale-string discovery). The merge gate verification is a separate concern
operated by the merge engine alone. Keeping it in its own family isolates
the two by construction so the merge command never leaks into agent
dispatch blocks or implicit test discovery.

CLI usage::

    python3 -m yoke_core.domain.merge_verification get <project-id>
    python3 -m yoke_core.domain.merge_verification set <project-id> <command>
      --timeout-seconds <seconds>
    python3 -m yoke_core.domain.merge_verification clear <project-id>

``get`` prints the policy JSON if configured and exits 0; it prints nothing
and exits 1 when no policy is set.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import List, Optional

from yoke_core.domain import project_structure as ps


FAMILY = "merge_verification"


@dataclass(frozen=True)
class MergeVerificationPolicy:
    """Project-specific merge command and timeout budget."""

    command: str
    timeout_seconds: int


def _valid_timeout(value: object) -> bool:
    return isinstance(value, int) and value > 0


def _policy_from_payload(payload: dict) -> Optional[MergeVerificationPolicy]:
    command = payload.get("command")
    timeout_seconds = payload.get("timeout_seconds")
    if not isinstance(command, str) or not command.strip():
        return None
    if not _valid_timeout(timeout_seconds):
        return None
    return MergeVerificationPolicy(
        command=command,
        timeout_seconds=timeout_seconds,
    )


def get_policy(
    project_id: str,
    db_path: Optional[str] = None,
) -> Optional[MergeVerificationPolicy]:
    """Return the configured merge verification policy, or ``None``."""
    slice_ = ps.read_structure(project_id, family=FAMILY, db_path=db_path)
    entries = slice_.get("entries") or []
    if not entries:
        return None
    payload = entries[0].get("payload") or {}
    if not isinstance(payload, dict):
        return None
    return _policy_from_payload(payload)


def get_command(
    project_id: str,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Return the configured merge verification command, or ``None``.

    Absence of an entry returns ``None``. An entry with an empty or
    whitespace-only ``command`` value also returns ``None`` so callers
    treat that as "no merge command configured" — the merge engine then
    emits the explicit skip log line.
    """
    policy = get_policy(project_id, db_path=db_path)
    return policy.command if policy else None


def set_command(
    project_id: str,
    command: str,
    timeout_seconds: int,
    db_path: Optional[str] = None,
    actor: Optional[str] = None,
) -> None:
    """Upsert the project's merge verification policy."""
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")
    if not _valid_timeout(timeout_seconds):
        raise ValueError("timeout_seconds must be a positive integer")
    ps.apply_patch(
        project_id,
        ops=[{
            "op": "put",
            "family": FAMILY,
            "attachment": "project",
            "payload": {
                "command": command,
                "timeout_seconds": timeout_seconds,
            },
        }],
        actor=actor,
        db_path=db_path,
    )


def clear_command(
    project_id: str,
    db_path: Optional[str] = None,
    actor: Optional[str] = None,
) -> bool:
    """Remove the project's merge verification command.

    Returns ``True`` when an entry was removed, ``False`` when no entry
    existed.
    """
    state = ps.read_structure(project_id, family=FAMILY, db_path=db_path)
    if not state.get("entries"):
        return False
    ps.apply_patch(
        project_id,
        ops=[{
            "op": "remove",
            "family": FAMILY,
            "attachment": "project",
        }],
        actor=actor,
        db_path=db_path,
    )
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_get(args: argparse.Namespace) -> int:
    policy = get_policy(args.project_id)
    if policy is None:
        return 1
    print(json.dumps({
        "command": policy.command,
        "timeout_seconds": policy.timeout_seconds,
    }, sort_keys=True))
    return 0


def _cmd_set(args: argparse.Namespace) -> int:
    try:
        set_command(
            args.project_id,
            args.command,
            args.timeout_seconds,
            actor=args.actor,
        )
    except (ValueError, ps.ProjectStructureError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Set merge_verification for '{args.project_id}'")
    return 0


def _cmd_clear(args: argparse.Namespace) -> int:
    try:
        removed = clear_command(args.project_id, actor=args.actor)
    except ps.ProjectStructureError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if removed:
        print(f"Cleared merge_verification for '{args.project_id}'")
    else:
        print(f"No merge_verification entry to clear for '{args.project_id}'")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.merge_verification",
        description=(
            "Read and write the project-level pre-merge verification policy."
        ),
    )
    sub = parser.add_subparsers(dest="subcmd")

    p_get = sub.add_parser("get", help="Print the project merge policy")
    p_get.add_argument("project_id")

    p_set = sub.add_parser("set", help="Upsert the project merge policy")
    p_set.add_argument("project_id")
    p_set.add_argument("command")
    p_set.add_argument("--timeout-seconds", type=int, required=True)
    p_set.add_argument("--actor")

    p_clear = sub.add_parser("clear", help="Remove the project merge entry")
    p_clear.add_argument("project_id")
    p_clear.add_argument("--actor")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.subcmd:
        parser.print_help(sys.stderr)
        return 2
    dispatch = {"get": _cmd_get, "set": _cmd_set, "clear": _cmd_clear}
    return dispatch[args.subcmd](args)


if __name__ == "__main__":
    sys.exit(main())
