"""Prove production stores and reads back manual-wake QA marks.

Reads the plan cases and the directly authored requirement that were marked
``wake_path: manual`` through the registered production CLI. A build that
predates the field returns no ``wake_path`` at all, so the readback also
proves the serving build. Read-only; exits non-zero naming the first missing
proof.
"""

import json
import subprocess
import sys

#: Plan id -> case key of each plan case marked manual after this release.
MARKED_PLAN_CASES = {
    8518: "production-materialization-deadline",
    8713: "real-independent-relay-progress",
    9044: "relay-admission-production-observation",
}
#: The directly authored requirement behind a plan-less admitted copy.
MARKED_REQUIREMENT = 45742


def call(*args):
    completed = subprocess.run(
        ["yoke", "--env", "prod", *args, "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    return json.loads(completed.stdout or "{}"), completed


def fail(code, detail):
    sys.exit(
        f"{code}: {detail}. Mark it with the steps in "
        "docs/public/reference/qa-platform/standalone-plans.md#cases-that-wait-for-real-traffic "
        "and rerun this case."
    )


def require_manual(subject, fields):
    if fields.get("wake_path") != "manual" or not fields.get("wake_evidence"):
        fail(
            "manual_wake_mark_missing",
            f"{subject} reads wake_path={fields.get('wake_path')!r} "
            f"wake_evidence={fields.get('wake_evidence')!r}",
        )


def main():
    for plan_id, case_key in MARKED_PLAN_CASES.items():
        reply, completed = call("qa", "plan", "get", str(plan_id), "--project", "yoke")
        if not reply.get("success"):
            fail(
                "plan_read_refused",
                f"plan {plan_id}: {completed.stdout} {completed.stderr}",
            )
        cases = {case["case_key"]: case for case in reply["result"]["plan"]["cases"]}
        if case_key not in cases:
            fail("plan_case_missing", f"plan {plan_id} has no case {case_key!r}")
        require_manual(f"plan {plan_id} case {case_key}", cases[case_key])
        print(
            f"plan {plan_id} case {case_key}: manual — {cases[case_key]['wake_evidence']}"
        )
    reply, completed = call("qa", "requirement", "get", str(MARKED_REQUIREMENT))
    if not reply.get("success"):
        fail("requirement_read_refused", f"{completed.stdout} {completed.stderr}")
    requirement = reply["result"]
    requirement = requirement.get("requirement", requirement)
    require_manual(f"requirement {MARKED_REQUIREMENT}", requirement)
    print(f"requirement {MARKED_REQUIREMENT}: manual — {requirement['wake_evidence']}")


if __name__ == "__main__":
    main()
