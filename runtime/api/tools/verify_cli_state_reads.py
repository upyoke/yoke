"""Read-only production proof for session and item CLI state projections."""

import json
import subprocess


def read(*arguments):
    process = subprocess.run(
        ["yoke", *arguments, "--json"], capture_output=True, text=True, timeout=60,
    )
    if process.returncode:
        raise SystemExit(
            f"cli_state_read_failed: {' '.join(arguments)}: {process.stderr or process.stdout}. "
            "Check the serving release and CLI version, then rerun this case."
        )
    response = json.loads(process.stdout)
    if not response.get("success"):
        raise SystemExit(f"cli_state_read_failed: {response.get('error')}; repair the named refusal and rerun.")
    return response["result"]


def main():
    roster = read("sessions", "list", "--presence", "present", "--limit", "5")
    for row in roster["rows"]:
        assert row["presence"] == "present", "presence_filter_ignored: upgrade the serving release"
        for field in ("activity", "intent", "holds", "custody", "next_actor"):
            assert field in row, f"session_state_missing: {field}; upgrade the serving release"
        point = read("sessions", "get", row["session_id"])["rows"]
        assert len(point) == 1 and point[0]["session_id"] == row["session_id"]
    items = read("items", "list", "--project", "all", "--limit", "3")
    for row in items["rows"]:
        fields = read("items", "get", row["id"], "stage", "home_section", "next_actor", "progress")["fields"]
        assert fields["stage"]["id"], "item_stage_missing: check the pinned workflow"
        assert fields["home_section"] in {"waiting", "on_hold", "ready", "in_progress", "release", "done"}
        assert fields["next_actor"]["reason"], "next_actor_reason_missing: check durable action facts"
        assert fields["progress"]["stages"], "item_progress_missing: check the pinned workflow"
    frontier = read("frontier", "list")
    for row in [*frontier["ready_rows"], *frontier["blocked_rows"]]:
        assert row.get("stage") and row.get("next_actor") and row.get("home_section")
    print(f"CLI state reads passed: {len(roster['rows'])} sessions, {len(items['rows'])} items.")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, ValueError) as exc:
        raise SystemExit(f"cli_state_contract_failed: {exc}. Check the serving release and pinned workflow, then rerun this case.") from None
