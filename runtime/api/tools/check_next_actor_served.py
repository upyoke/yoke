"""Read-only proof that the serving candidate exposes next-action facts."""

import json
import subprocess

ACTORS = {
    "this_session", "operator", "parent_or_steering", "another_item",
    "ci_or_deploy", "nobody",
}


def read_rows(arguments):
    reply = json.loads(subprocess.check_output(["yoke", *arguments, "--json"], text=True))
    if not reply.get("success"):
        raise RuntimeError(f"next_actor_read_failed: {reply.get('error')}; repair the registered read and retry")
    rows = reply["result"]["rows"]
    if not rows:
        raise RuntimeError("next_actor_roster_empty: retry when the production roster contains records")
    return rows


def check_rows(rows):
    for row in rows:
        next_action = row.get("next_actor")
        if not isinstance(next_action, dict):
            raise RuntimeError("next_actor_unavailable: release the candidate serving build and retry")
        assert next_action["actor"] in ACTORS, next_action
        assert next_action["reason"], next_action
        assert "since" in next_action, next_action
        if next_action["actor"] == "operator":
            assert next_action.get("people"), "next_actor_audience_empty: repair the decision audience"
            assert all(person.get("name") for person in next_action["people"])
        model = row.get("session_state")
        if model:
            assert model["next_actor"] == next_action
            if model["presence"] == "ended":
                assert next_action["actor"] == "nobody"
    return len(rows)


def main():
    sessions = check_rows(read_rows(["sessions", "list", "--limit", "25", "--full"]))
    items = check_rows(read_rows(["items", "overview", "list", "--limit", "25"]))
    print(f"Verified next actor, reason, state time and human audiences on {sessions} sessions and {items} items")


if __name__ == "__main__":
    main()
