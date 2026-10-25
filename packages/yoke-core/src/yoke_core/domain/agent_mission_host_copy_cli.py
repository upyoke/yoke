"""Lease-authorized copy of one Test Machine file for exploratory walkers."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.qa_artifact_limits import MAX_ARTIFACT_BYTES
from yoke_contracts.qa_mission_scratch import MISSION_SCRATCH_ROOT
from yoke_harness.remote_file_copy import HostCopyRefused

from yoke_core.domain.agent_mission_host_command_cli import (
    add_mission_subject_arguments,
    resolve_mission_contract,
)

PROG = "yoke qa mission host-copy"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def execute_agent_mission_host_copy(
    raw_contract: dict[str, Any],
    *,
    source: str,
    destination: Path,
) -> dict[str, Any]:
    """Write one Test Machine file's exact bytes to a local path.

    The host refuses any path that resolves inside the mission scratch root,
    because that directory holds staged secrets.
    """
    from yoke_core.domain.machine_qa_execution_contract import (
        HostControlExecutionContract,
    )
    from yoke_core.domain.machine_qa_local_execution import (
        _execution,
        _mission_contract,
    )

    if raw_contract.get("operation") == "host_command":
        contract = HostControlExecutionContract.model_validate(raw_contract)
    else:
        contract = _mission_contract(raw_contract)
    execution = _execution(contract)
    written = execution.control.copy_file_to(
        source,
        destination,
        max_bytes=MAX_ARTIFACT_BYTES,
        refused_root=MISSION_SCRATCH_ROOT,
    )
    return {
        "from": source,
        "to": str(destination),
        "bytes": written,
        "sha256": _sha256(destination),
    }


def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Copy one file's exact bytes from an awaiting mission's retained "
            "Test Machine lease to a path on this machine."
        ),
        epilog=(
            f"Files up to {MAX_ARTIFACT_BYTES} bytes, the QA artifact limit, "
            "copy. Paths inside the mission scratch directory are refused: it "
            "holds staged secrets. Upload the copy with `yoke qa artifact add "
            "... --content-file LOCAL_PATH`."
        ),
    )
    add_mission_subject_arguments(parser)
    parser.add_argument(
        "--test-machine",
        metavar="TEST_MACHINE",
        help="Declared case host to copy from; defaults to the retained driver host.",
    )
    parser.add_argument(
        "--from",
        dest="source",
        required=True,
        metavar="TARGET_PATH",
        help="Absolute path of the file on the Test Machine.",
    )
    parser.add_argument(
        "--to",
        dest="destination",
        required=True,
        metavar="LOCAL_PATH",
        help="Path on this machine; an existing file there is replaced.",
    )
    parsed = parser.parse_args(args)
    contract = resolve_mission_contract(parsed, prog=PROG)
    if contract is None:
        return 2
    try:
        from yoke_core.domain.machine_qa_host_control import (
            register_test_machine_host_control,
        )

        register_test_machine_host_control()
        result = execute_agent_mission_host_copy(
            contract,
            source=parsed.source,
            destination=Path(parsed.destination),
        )
    except HostCopyRefused as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 2
    except HostControlLocalError as exc:
        print(
            f"{PROG}: {exc.code}: {exc} Recovery: {exc.recovery_hint}", file=sys.stderr
        )
        return 2
    except Exception as exc:
        print(
            f"{PROG}: local execution failed ({type(exc).__name__}). Recovery: "
            "check the host with `yoke test-machine verify`, then retry the copy.",
            file=sys.stderr,
        )
        return 2
    payload = {
        "execution_id": parsed.execution_id,
        "requirement_id": parsed.requirement_id,
        **result,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["execute_agent_mission_host_copy", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
