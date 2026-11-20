# Native Windows settings journal

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows settings journal
<!-- /yoke:breadcrumbs -->

The fixed SYSTEM task `YokeQaMachineSettings` accepts lease-bound capture and restore.
Administrators and SYSTEM own its program and journal under `C:\ProgramData\YokeQa\private`.
The test user can submit requests and read protected receipts. Every serial lease
first restores any interrupted journal and verifies the Windows feature state.

In a native case that changes machine settings, declare the setup operation
`{"id":"machine.windows-settings-journal","parameters":{"mutations":["tools"]}}`.
List the affected settings using `applocker`, `long_paths`, `certificates` or
`tools`. The journal saves all four inventories before a declared case begins
and verifies restore in cleanup. Cases without the operation use the bind check
alone. Restore per-user tools with the profile golden.

Read `tools.saved_only` and `tools.current_only` in the refusal or the protected
receipt at `C:\ProgramData\YokeQa\receipts\receipt.json`. Rows keep Name, Version
and ProviderName, including duplicate occurrences. The receipt and QA evidence
show each reported attempt's status and the installer process exit code when
available. `Uninstall-Package` reports a command outcome and has no process exit
code. `windows_tool_uninstall_ineffective` means its package still appears after
the command. Administrators can read the full `private\last-restore-diff.json`
when the shared receipt truncates rows.

Before removing a baseline tool, provide a hash-verified installer in the
private cache. Its `tool-installers.json` entry uses `Name`, `Version`,
`ProviderName`, `path`, `sha256` and `arguments`. For a test-added package that
the task may remove, add an entry with the same identity fields and
`"allow_uninstall": true`. Keep OS and vendor auto-update packages outside that
allowlist. Private-key certificate removal requires a project-approved
recovery procedure.

Keep a failed machine out of QA. Re-provision the fixed SYSTEM program from the
release you are validating, preserving the private journal and task ACL.
For a verified vendor or OS update, open elevated Windows PowerShell (or use
Azure Run Command as SYSTEM while no lease owns the machine):

```powershell
$program = 'C:\ProgramData\YokeQa\private\machine-settings.ps1'
& $program -InspectTools
& $program -AcceptToolsFingerprint '<fingerprint from inspection>' -ApprovalReason '<verified vendor, version, and source>'
```

Inspect and verify every differing tool before approval. Approval changes only
the saved tool inventory and writes the private `tool-rebaseline-*.approval.json`
audit receipt and `tool-rebaseline-*.before.json` original journal. Retry the
next serial lease and confirm restore passes before resuming QA. Preserve the
journal if any setting still differs. Never delete it or recapture a dirty host.
