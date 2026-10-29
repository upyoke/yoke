"""Read-only release evidence for project retirement and tenant-move clients."""

import argparse
import json
import subprocess

from yoke_contracts.machine_config.schema import connection_is_protected
from yoke_core.domain.universe_import_artifacts import rewrite_imported_artifacts
from yoke_core.domain.universe_import_credentials import revoke_imported_credentials


def _projects(environment, *, include_retired=False):
    command = ["yoke", "--env", environment, "projects", "list", "--json"]
    if include_retired:
        command.append("--include-retired")
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    envelope = json.loads(result.stdout)
    if not envelope.get("success"):
        raise ValueError(
            "project_inventory_unavailable: restore the selected connection and retry"
        )
    return envelope["result"]["rows"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True)
    args = parser.parse_args()
    active = _projects(args.env)
    inventory = _projects(args.env, include_retired=True)
    if any("retired_at" not in row for row in inventory):
        raise ValueError(
            "retirement_field_unavailable: deploy the retirement-capable build and retry"
        )
    retired = {row["id"] for row in inventory if row["retired_at"] is not None}
    if retired.intersection(row["id"] for row in active):
        raise ValueError(
            "retired_project_selected: repair active inventory filtering and retry"
        )
    assert connection_is_protected({"protected": True})
    assert connection_is_protected({"prod": True})
    assert callable(rewrite_imported_artifacts) and callable(
        revoke_imported_credentials
    )
    help_text = subprocess.run(
        ["yoke", "connection", "set", "--help"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if "--protected" not in help_text or "--non-prod" in help_text:
        raise ValueError(
            "protected_cli_unavailable: update the CLI to the candidate release and retry"
        )
    print(
        json.dumps(
            {
                "active_projects": len(active),
                "retired_projects_excluded": len(retired),
                "protected_client": True,
                "import_helpers": True,
            }
        )
    )


if __name__ == "__main__":
    main()
