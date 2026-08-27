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

## Binding your project's command

Bind the command the gate runs — one call per scope, no environment needed:

```bash
yoke qa registered-command set --project <p> --scope quick --command "<argv>"
```

That converges the whole binding: the `registered-command-quick` plan, its
case, the runner the case uses, and the project-default attachments at the
gating transitions. The command is arbitrary shell argv: Maven, PHPUnit,
`xcodebuild`, and `docker compose run --rm tests` are as valid as pytest.
Register a reliable documented slice as `quick`; add `--scope full` with the
broader argv only when the two commands genuinely differ.

Test roots are independent Project Structure entries. Record each monorepo
tree with a keyed `test_roots` `put`; the quick command may intentionally cover
one slice while the full command aggregates all suites.

Declaring a GitHub Actions **test** workflow routes those scopes to CI:

```bash
yoke projects capability-settings set --project <p> --cap-type ci_workflow_file \
  --new --settings-json '{"workflow_file":"ci.yml"}'
```

Without that declaration the scopes run locally in the item's worktree, which
is a correct configuration rather than a downgrade. A project-structure
`verification_profiles.test_command` entry is descriptive and is never the
gate command. Jenkins, GitLab CI, Bitbucket Pipelines, `fastlane`, and an
XCTest or container command without an Actions test workflow stay on the local
`command` method; they are not `ci_workflow_file` declarations.

## Known-red and flaky suites

Do not bind a known-red or materially flaky suite as a blocking project
default merely to make it visible. Preserve its roots, exact argv, and known
condition. Seed each relevant item with a blocking `implementation_review`
requirement and a non-blocking `command` case for the suite. The advisory case
records the current result without manufacturing a green gate or making a
known baseline failure block every item.

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
