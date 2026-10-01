# Separate browser profile baseline

Keep the clean home golden free of Yoke, including `~/.yoke`. Browser
authorization belongs in a separate private snapshot beside that golden.
This component currently supports Linux test machines only.

After the operator has authorized the project's browser, have them log out of
the desktop. Stop the installed browser daemon through its registered service
surface. Before any host reset, capture the stopped profile:

```text
yoke test-machine golden-capture --project P --machine NAME --component browser-profile --json
```

Read the command's `--help` before execution. It uses the ordinary host lease,
digest-bound contract and capture receipt. Its default destination is a new
timestamped sibling of the declared clean home golden; `--destination` may
name a new sibling explicitly. It refuses active profile writers, existing
destinations, unsafe entries or foreign ownership. It omits Chromium singleton
locks and sockets, preserving the persistent profile databases. No probe file
is required for this component.

A successful receipt records `browser_profile_baseline_path` on the machine
without changing `golden_baseline_path`. The archive and manifest stay private
on that host, bound to its user ID, home, project and archive digest. Never copy
them into source control, the control plane, QA artifacts or transcripts.
This receipt proves a sealed capture; it does not prove a signed-in application.

Fresh-host and shell-preconfigured resets restore only the clean home golden.
For a browser-authenticated mission, install the candidate Yoke first, keep its
browser daemon stopped, and explicitly declare this setup operation:

```json
{
  "id": "machine.browser-profile-restore",
  "parameters": {
    "project": "canonical-project-slug",
    "baseline_path": "/var/lib/yoke-golden/testuser/sealed-browser-profile"
  }
}
```

Use the machine's recorded snapshot path and the case's canonical project.
The fixture runs through the installed launcher's interpreter, verifies the
sealed snapshot before restoring, and refuses an existing profile or active
writers. Include it only in missions needing browser authorization. It leaves
the restored profile available to the mission; the next ordinary host reset
removes it again while the external snapshot survives.

Start the candidate daemon and actually open the application. Record the
signed-in UI state as the proof. Cookie counts, successful archive receipts and
CLI authentication probes cannot establish browser authentication. If sealing
fails, retain the profile and fix the named refusal before any reset.
