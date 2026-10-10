# A05 — Dana, agency, per-client GitHub repos, macOS, manual deploy

**Vector:** agency · vibe-coded client work · hosting none yet · macOS ·
GitHub without CI · manual deploy.

Dana onboarded Yoke once for the agency machine, then adds a client repo per
engagement. Each client is a separate Yoke project. Deploys are FTP or
"send a ZIP".

## Fit / break / gaps

| | |
|---|---|
| Fits | Re-run `yoke setup` / existing folder. Stored destination picker if a token exists. Machine GitHub reuse. Skip hosting. Multiple projects on one local universe. |
| Breaks | One wizard hosting credential is **per project slug** (`capability-secrets/<project>/aws-admin`). FTP/ZIP is not a flow. Agency org vs personal GitHub owner picker. |
| Gaps | Multi-project teaching. "Client has no deploy environment" as a first-class profile. |

## Transcript — installer (second client; yoke already installed)

Re-run `curl -fsSL https://upyoke.com/install | sh` upgrades lockstep packages
(`yoke-cli`, `yoke-contracts`, `yoke-harness`, `yoke-core`) then
`Starting Yoke setup…` again.

Or she runs `yoke setup` directly.

If a stored connection exists (`_stored_yoke_token_available`):

```
Use this saved Yoke connection?
Yoke found a connection in machine config. Reuse it, or choose another home.
  Use existing local connection     (or hosted env URL)
  This machine
  A team server
  Set this machine up as a self-hosting server
  upyoke.com
```

**User:** This machine (local already). Universe summary:
`Yoke found an existing local universe connection in ~/.yoke.`
`Apply verifies the existing database and preserves its projects, items, settings, and secrets.`

GitHub: Connect (reuse saved authorization — "Refreshing the saved
authorization.").

Project: Existing folder `~/Clients/northstar-web`. Origin
`github.com/dana-agency/northstar-web`.

If the App cannot see a **private** client repo:

```
GitHub App repo binding is required.
Use a repository already available to the Yoke GitHub App, add repository
access in GitHub, or keep this project disabled.
  Check access
  Skip GitHub
  Back
```

Or private picker empty:

```
  Manage repository access in GitHub     choose private repos
  Check again
  Back
```

**User:** Manage access, then Check access, then **Use connected repo**.

Skip hosting. Apply. New project `northstar-web`, prefix `NORT`.

Hand-off again names Claude/Codex.

## Transcript — `/yoke onboard --project northstar-web`

Empty-ish marketing site. Strategy conversation per client. The no-host
profile omits AWS Packs and offers merge-only or no default. Dana chooses
**no default** for manual client delivery; step 5 removes any stale project
attachment and verifies an empty readback without creating environments.

Seeded items omit `--deployment-flow`. A prior client default is project-local
and cannot leak into this slug.

## Test setup

**Reality:** per-client marketing/site repos. Often **no tests**, or a
Playwright check nobody runs. GitHub without Actions.

**Onboard:** confirm each client's test posture explicitly. Survey an existing
suite, offer a minimal scaffold when absent, or record the operator's reason
for no-tests; an undecided posture blocks completion. The agency business
model does not choose no-tests. Review-only needs blocking review and advisory
legacy-command evidence. With no eligible Actions test workflow, do not bind
`command-ci` or a merge queue. A registered command uses this project's exact
argv and reusable QA plan; seeded items attach its immutable snapshot at the
required transition. Follow the current
[profile](../../.agents/skills/yoke/onboard/profile-and-scaffold.md),
[verification binding](../../.agents/skills/yoke/onboard/verification-binding.md)
and [work seeding](../../.agents/skills/yoke/onboard/seed-work.md) contracts.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| Per-client deploy | Profile: "no Yoke-managed environment" | Do not create stage/prod | Manual delivery; Usher Route A |
| Private GitHub | App installation must include the client repo | Pending binding; project GitHub `disabled` | Issues stay in Yoke DB only (`github_sync_mode` disabled) |
| Agency identity | Owner picker "Where on GitHub?" / `your account` vs `organization` | Cannot publish under the wrong owner | Pick org; do not paste tokens |

Ledger: G-forge-github-only (private App access friction).
