"""Post-deploy CLI proof using an additive verification section on its member."""

from __future__ import annotations

import json
import os
import subprocess


def run(*args: str):
    completed = subprocess.run(
        ["yoke", "--env", "prod", *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode:
        raise RuntimeError(
            f"field_section_probe_failed: exit={completed.returncode}; "
            f"{completed.stdout} {completed.stderr}. Inspect the member before retrying."
        )
    return completed.stdout


def main():
    member = os.environ.get("DEPLOYMENT_MEMBER_REF")
    if not member:
        raise RuntimeError(
            "field_section_probe_member_missing: run as an item-scoped QA stage"
        )
    heading = "Field section verification"
    content = "Field-targeted section upsert verified through the deployed CLI."
    args = (
        "items",
        "structured-field",
        "section-upsert",
        member,
        "--field",
        "test_results",
        "--heading-level",
        "3",
        "--section",
        heading,
        "--content",
        content,
    )
    human = run(*args)
    if not human.strip():
        raise RuntimeError(
            "field_section_probe_receipt_missing: inspect the member write"
        )
    print("default receipt:", human.strip())
    response = json.loads(run(*args, "--json"))
    result = response.get("result") or {}
    assert response["success"], response
    assert result["field"] == "test_results", result
    assert result["heading_level"] == 3, result
    assert result["changed"] is False, result
    field_read = json.loads(run("items", "get", member, "test_results", "--json"))
    stored = field_read["result"]["fields"]["test_results"]
    assert f"### {heading}\n\n{content}" in stored, stored
    print(json.dumps({"success": True, "member": member, "receipt": result}))


if __name__ == "__main__":
    main()
