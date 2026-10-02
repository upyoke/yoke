# Browser-authenticated host missions

Test-machine preparation, capture and restoration belong to the
[Machine QA Pack per-OS procedures](../../../../packs/machine-qa/versions/1.3.8/files/docs/packs/machine-qa/browser-profile-baseline.md).
After installation, read `docs/packs/machine-qa/host-provisioning.md`.

Authors declare the project's required sign-ins and own application flow in
`.yoke/browser-flows.json`. For example:

```json
{
  "required_sign_ins": ["An account at app.example.test able to approve this project's test machine"],
  "machine_browser_approval": {
    "origins": ["https://app.example.test"],
    "paths": ["/connect", "/machine"],
    "url_label": "Open:",
    "code_label": "One-time code:",
    "code_pattern": "[A-Z0-9]{4}-[A-Z0-9]{4}",
    "query_parameter": "user_code",
    "approval_target": "role=button[name=\"Approve device\"][exact=true]",
    "rejected_statuses": ["denied", "expired", "missing", "used"],
    "denial_text": ["authorization denied", "authorization expired"]
  }
}
```

Use the actual application's labels, code grammar, control and refusal text.
Origins must be literal HTTPS origins and paths must be literal entry paths;
the flow also has to match the QA case's immutable application target.
Capture proof lists each required sign-in beside actual signed-in application
UI evidence. Profile status or cookie counts cannot replace that evidence.

A typed `machine_browser_approval` recipe gate restores after installation,
opens the exact fresh URL/code its terminal emitted, proves the visible
approval control and waits for that terminal's declared completion. For an
exploratory mission, use the dispatch's `yoke qa mission browser-flow` command
with the live owner-only transcript under its own mission scratch directory
and the expected terminal completion text. Read its `--help`: no pasted link,
another run's transcript or manual token substitutes for this flow.

Authors must not mark these browser steps as human gates by default. A valid
saved sign-in lets the test finish its own approval. A missing/expired needed
personal sign-in returns a precise handoff naming machine, site, current state
and resumption with a fresh flow; agents never sign in or change security
settings. Denied or expired approval requests remain typed failures.

For the mission contract, see [Exploratory QA](../exploratory-qa.md).
For browser implementation details, see the project's browser-substrate docs.

Profile snapshot capture and restore create every missing directory with
owner-only permissions. Existing directories keep their permissions; an unsafe
credential directory is refused with its path, including in the onboarding
wizard, so the operator can inspect that directory before retrying.
A snapshot can sit beside a clean golden under a test-user-owned readable
parent, while the snapshot and its files remain owner-only. A parent writable
by other users is refused with its path; capture never chmods that parent.
