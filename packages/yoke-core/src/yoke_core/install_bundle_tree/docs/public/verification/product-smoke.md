# Manual product smoke on Linux and macOS

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Product smoke
<!-- /yoke:breadcrumbs -->

Product smoke verifies installation and onboarding in a disposable environment, then exercises the installed harness hooks. It complements [real-harness QA](real-harness.md), which uses signed-in native agent sessions on persistent Test Machines.

A smoke case should name the candidate commit, operating system, architecture, and captured assertions. Check both allowed and denied shell decisions, the stored session's executor and workspace, and cleanup. A successful CLI exit without these assertions is insufficient evidence; missing diagnostic telemetry means the result is unproved.

Yoke's source-maintainer smoke runs manually on disposable Ubuntu x86_64, Ubuntu arm64, and macOS arm64 runners. It installs candidate wheels and replays native hook recordings without provider credentials. It does not verify self-host bring-up or relay supervision, and it is not automatically attached to project changes or deployment gates.

For your own project, define a smoke plan around its installation and critical user path. Preserve command captures and failure diagnostics in the case evidence, and inspect the saved execution before choosing a retry.

For project QA, use `yoke qa plan run --plan PLAN --project P`; read its `--help` for candidate and machine bindings.

## Related

- [Verification](index.md)
- [QA platform](platform.md)
