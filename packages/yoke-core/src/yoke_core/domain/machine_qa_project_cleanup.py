"""Host-side cleanup through the registered retirement surface.

Run on the leased host so local, self-hosted, and hosted onboarding all
resolve the same control plane the project was born on. Ownership stays in
the project's capability document; telemetry is never consulted.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def _call(argv):
    result = subprocess.run(["yoke", *argv, "--json"], text=True, capture_output=True)
    try:
        envelope = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError(
            "qa_project_cleanup_response_invalid: "
            + " ".join(argv)
            + "; inspect the host CLI and retry mission teardown"
        ) from exc
    if result.returncode or not envelope.get("success", True):
        error = envelope.get("error") or {}
        if error.get("code") == "not_found":
            return None
        raise RuntimeError(
            "qa_project_cleanup_refused: "
            + str(error or result.stderr)
            + "; resolve the named blocker and retry mission teardown"
        )
    return envelope.get("result", envelope)


def cleanup(owner: str, owner_file: str, owner_capability: str) -> dict:
    marker = Path.home() / ".yoke" / owner_file
    if not marker.exists():
        return {"retired_projects": [], "owner_marker_removed": True}
    claimed = json.loads(marker.read_text())
    if claimed.get("owner") != owner:
        raise RuntimeError(
            "qa_project_owner_conflict: another case owns this host; "
            "use its lease and do not remove its ownership marker"
        )
    # A continued mission inherits the walk it resumed, projects included.
    owners = {owner, *(claimed.get("inherited_owners") or [])}
    inventory = _call(["projects", "list", "--include-retired"])
    retired, failures = [], []
    for row in inventory["rows"]:
        project = str(row["id"])
        try:
            settings = _call(
                [
                    "projects",
                    "capability-settings",
                    "get",
                    "--project",
                    project,
                    "--cap-type",
                    owner_capability,
                ]
            )
            if (
                settings is None
                or json.loads(settings.get("settings_json") or "{}").get("owner")
                not in owners
            ):
                continue
            _call(
                [
                    "projects",
                    "retire",
                    "--project",
                    project,
                    "--reason",
                    f"Machine QA case {owner} finished",
                ]
            )
            retired.append(row["slug"])
        except RuntimeError as exc:
            failures.append(str(exc))
    if failures:
        raise RuntimeError("qa_project_cleanup_incomplete: " + "; ".join(failures))
    marker.unlink()
    return {"retired_projects": retired, "owner_marker_removed": True}


def main():
    try:
        print(json.dumps(cleanup(*sys.argv[1:4])))
    except Exception as exc:
        print(
            f"qa_project_cleanup_failed: {exc}; retry mission scratch-teardown",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
