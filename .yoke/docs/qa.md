# QA

Workbench **QA** tabs:

| Tab | Meaning |
|---|---|
| **Methods** | Registered contracts cases use to prove a claim (command, browser, …) |
| **Plans** | Project-scoped ordered cases and attachments |
| **Activity** | Readable outcomes from requirements, runs, evidence |

## How gates work

Workflows attach plans to transitions (for example reviewing-implementation).
The case run **is** the verdict-producing execution — do not hand-run the same
full suite and then re-run it through QA.

```bash
yoke qa case run --requirement-id <id>
```

When the project binds CI for quick/full scopes, commit and let the case
runner push the lane branch; the verdict names the CI run URL and head sha.

## Local iteration

While implementing, use impacted selection:

```bash
yoke watch pytest --impacted main --bounded
```

Full-suite authority on protected merges is CI (when configured). Local full
sweeps are the CI-outage fallback.

## Browser QA

Browser methods use the packaged browser runtime. Scenario schemas live under
reference. See [reference/qa-platform.md](reference/qa-platform.md) and
[reference/browser-scenarios.md](reference/browser-scenarios.md).
