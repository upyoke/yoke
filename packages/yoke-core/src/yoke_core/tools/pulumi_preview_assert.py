"""Assert declared infra invariants hold in a ``pulumi preview --json``.

CI guard for the webapp environment stacks: the database-secret rotation
guard and the Aurora auto-pause window must remain *declared* in Pulumi
rather than drifting back to manual console settings. Reads the JSON a
``pulumi preview --json`` run wrote and fails loudly when:

- the ``databaseMasterSecretRotationDisabled`` dynamic resource is being
  deleted (rotation guard undeclared), or is absent from the plan
  entirely for a stack that declares a database;
- the Aurora cluster is planned without
  ``serverlessv2ScalingConfiguration.secondsUntilAutoPause`` (auto-pause
  undeclared) or with ``manageMasterUserPassword`` flipped off;
- the Aurora cluster or VPS instance is being *replaced* (the AMI pin
  and database identity must never churn from a routine preview).

Usage::

    pulumi preview --json > preview.json
    python3 -m yoke_core.tools.pulumi_preview_assert preview.json

Exit codes: 0 all assertions hold, 1 violation (named on stderr),
2 usage/parse error. Stacks without a database resource (registry,
domain, vps-only) pass trivially with a note.
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional

_ROTATION_GUARD_NAME = "databaseMasterSecretRotationDisabled"
_CLUSTER_TYPE = "aws:rds/cluster:Cluster"
_INSTANCE_TYPE = "aws:ec2/instance:Instance"
_REPLACE_OPS = ("replace", "create-replacement", "delete-replaced")


def _state(step: dict) -> dict:
    new_state = step.get("newState")
    return new_state if isinstance(new_state, dict) else {}


def _inputs(step: dict) -> dict:
    inputs = _state(step).get("inputs")
    return inputs if isinstance(inputs, dict) else {}


def assert_preview(payload: dict) -> List[str]:
    """Return violation messages for one parsed preview payload."""
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return ["preview JSON carries no steps list (not a --json preview?)"]

    violations: List[str] = []
    clusters = [
        s for s in steps if _state(s).get("type") == _CLUSTER_TYPE
    ]
    guards = [
        s for s in steps
        if str(s.get("urn", "")).endswith(f"::{_ROTATION_GUARD_NAME}")
    ]

    for step in guards:
        if step.get("op") in ("delete", *_REPLACE_OPS):
            violations.append(
                f"rotation guard {_ROTATION_GUARD_NAME} is planned for "
                f"{step.get('op')} — the secret-rotation-off declaration "
                "must stay in the stack"
            )

    for step in clusters:
        op = step.get("op")
        if op in _REPLACE_OPS or op == "delete":
            violations.append(
                f"Aurora cluster planned for {op} — database identity must "
                "never churn from a routine preview"
            )
        if op == "delete":
            continue
        inputs = _inputs(step)
        scaling = inputs.get("serverlessv2ScalingConfiguration")
        pause = (
            scaling.get("secondsUntilAutoPause")
            if isinstance(scaling, dict) else None
        )
        if not pause:
            violations.append(
                "Aurora cluster plan carries no serverlessv2Scaling"
                "Configuration.secondsUntilAutoPause — the auto-pause "
                "window must stay declared, not a console setting"
            )
        if inputs.get("manageMasterUserPassword") is False:
            violations.append(
                "Aurora cluster plan flips manageMasterUserPassword off"
            )

    if clusters and not guards:
        violations.append(
            "stack declares an Aurora cluster but no "
            f"{_ROTATION_GUARD_NAME} resource — the rotation guard must "
            "stay declared"
        )

    for step in steps:
        if (
            _state(step).get("type") == _INSTANCE_TYPE
            and step.get("op") in _REPLACE_OPS
        ):
            violations.append(
                "VPS instance planned for replacement — the AMI pin "
                "(ignore_changes) must hold; investigate before applying"
            )

    return violations


def main(argv: Optional[list] = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(
            "Usage: python3 -m yoke_core.tools.pulumi_preview_assert "
            "<preview-json-path>\nAsserts the rotation guard, auto-pause "
            "declaration, and no-replace invariants hold in a "
            "`pulumi preview --json` output.",
            file=sys.stderr,
        )
        return 2
    try:
        with open(args[0]) as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot parse preview JSON: {exc}", file=sys.stderr)
        return 2

    violations = assert_preview(payload)
    if violations:
        for line in violations:
            print(f"ASSERT FAILED: {line}", file=sys.stderr)
        return 1
    steps = payload.get("steps") or []
    has_db = any(_state(s).get("type") == _CLUSTER_TYPE for s in steps)
    print(
        "pulumi-preview-assert: ok "
        + ("(rotation guard + auto-pause declared)" if has_db
           else "(no database resource in this stack — trivially ok)")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
