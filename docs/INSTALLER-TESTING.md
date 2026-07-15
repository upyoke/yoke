# Installer Testing

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately -- before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

This guide preserves the Live TUI campaign mechanics for the public installer
and `yoke onboard`. Use it when starting a new installer campaign, extending the
scenario catalog, retaining evidence, or importing campaign results into QA.

## Evidence Root

Before creating files or running a campaign, choose a retained evidence root
under `~/.yoke`. The standard root for installer smoke campaigns is:

```text
$HOME/.yoke/installer-smoke-evidence/<campaign-id>/
```

All retained installer evidence belongs under `~/.yoke`, never inside the repo
checkout. In particular, do not create or reuse repo-local paths such as
`.yoke/installer-smoke-evidence/`; project `.yoke/` directories are for Yoke
contract files and generated project views, not campaign evidence. `/tmp` and
remote host staging directories are scratch only.

Ask the operator for the campaign id and any non-standard `~/.yoke` subdirectory
to use for the retained campaign root. Do not hardcode personal, iCloud, `/tmp`,
or worktree paths in the campaign instructions.

Use explicit variables in every command:

```bash
CATALOG_DOC=docs/INSTALLER-TESTING.md
CAMPAIGN_ID=<operator-approved-campaign-id>
CAMPAIGN_ROOT="$HOME/.yoke/installer-smoke-evidence/$CAMPAIGN_ID"
ENDPOINT=stage
LEDGER="$CAMPAIGN_ROOT/host-ledger.json"
```

Ask for these values at campaign start:

- Campaign id and retained evidence root under `~/.yoke`.
- Endpoint and channel to test, usually `stage` / `latest` or `prod` / `stable`.
- Scenario subset from the embedded catalog in this guide.
- Host lane: physical Mac, manual SSH host, EC2 fleet, or mixed.
- Token-file paths to stage onto hosts. Never ask for raw token values.
- Cleanup policy for any EC2 resources and local private-key files.
- Whether results should be imported into QA, and the numeric item id or
  epic/task target if so.

## Source Surfaces

The Live TUI campaign helpers are source-checkout tools, not the public product
installer surface:

- `packages/yoke-core/src/yoke_core/tools/installer_live_tui_harness.py`
- `packages/yoke-core/src/yoke_core/tools/installer_live_tui_fleet.py`
- `packages/yoke-core/src/yoke_core/tools/installer_live_tui_capture.py`
- `packages/yoke-core/src/yoke_core/tools/installer_live_tui_runner.py`
- `packages/yoke-core/src/yoke_core/tools/installer_live_tui_coordinator.py`
- `packages/yoke-core/src/yoke_core/tools/installer_live_tui_qa_ingest.py`

Related surfaces:

- Public installer entrypoints:
  `packaging/public-installer/install` and
  `packaging/public-installer/install.py`.
- Installer tests and goldens: `tests/installer/`.
- Public setup docs: `docs/local-setup.md` and
  `docs/onboard-external-project.md`.

## Campaign Layout

Every retained campaign root should use this shape:

```text
<campaign-root>/
  harness-manifest.json
  host-ledger.json
  campaign-plan.json
  assignments/
  recipe-stubs/
  run-specs/
  captures/
  screenshots/
  post-apply/
  raw-host-staging/
  reports/
  summaries/
  logs/
  evidence-archive/
```

Evidence pairing is intentional. A retained screen step should have matching
text and image evidence whenever screenshots are available:

```text
captures/A001/<scenario-id>/000-initial.txt
screenshots/A001/<scenario-id>/000-initial.png
```

If screenshots are blocked, keep the text capture or bridge log and record why
image evidence is absent in the report.

## Scenario Catalog

This guide is the catalog source. The campaign parser reads Markdown tables from
`$CATALOG_DOC`; it recognizes scenario sections headed `### Wave ...`, then table
rows with these columns:

- `id`
- `profile` or `host`
- `flow`
- `assertions`

Scenario ids must look like `NAME-001`: uppercase letters, digits, hyphens, and
a three-digit suffix.

Inspect the catalog:

```bash
python3 -m yoke_core.tools.installer_live_tui_harness catalog \
  --plan "$CATALOG_DOC" \
  --json
```

Keep related scenarios together when assigning work so one host state can serve
several checks without contaminating unrelated cases. Fault-injection scenarios
should usually run alone because they may intentionally leave partial state.

### Wave 1: Installer And First Wizard Smoke

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `INSTALL-SMOKE-001` | `bare-no-uv` | Interactive installer, accept uv, auto-launch onboard | Welcome renders; uv consent default is Yes; `Starting Yoke onboard` appears; install summary appears |
| `INSTALL-SMOKE-002` | `bare-no-uv` | Installer `--yes` | No TUI launch; prints `Run yoke onboard`; `yoke --version` works |
| `INSTALL-SMOKE-003` | `prepared-yoke` | Launch `yoke onboard` directly | PATH screen or install summary appears; no crash |
| `INSTALL-SMOKE-004` | `prepared-yoke` | Machine-only stage onboarding | Apply succeeds; report written; `yoke status` reaches stage |
| `INSTALL-SMOKE-005` | `prepared-yoke` | Machine-only prod onboarding | Apply succeeds against prod with prod token; active env is prod |

### Wave 2: Installer Branches

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `INSTALL-UV-001` | `bare-no-uv` | Accept Astral uv path | uv installed; helper downloaded; product install succeeds |
| `INSTALL-UV-002` | `bare-no-uv` | Decline uv consent | Friendly decline screen names manual install and rerun command |
| `INSTALL-UV-003` | `bare-no-uv` | Default Enter on uv consent | Proceeds as Yes |
| `INSTALL-UV-004` | `bare-no-curl` | Missing curl with no uv | Fails with actionable uv/curl message |
| `INSTALL-UV-005` | `bare-no-uv` | Script-file invocation with piped `y\n` | Prompt reads stdin safely; no `/dev/tty` noise |
| `INSTALL-UV-006` | `bare-no-uv` | Piped shell invocation without `--yes` and no tty | Friendly failure/decline behavior; no raw tty errors |
| `INSTALL-UV-007` | `bare-no-uv` | `YOKE_INSTALL_YES=1` | No welcome prompt; installs quietly |
| `INSTALL-UV-008` | `bare-no-uv` | `YOKE_NO_ONBOARD=1` | Installs but never offers or launches onboard |
| `INSTALL-UV-009` | `prepared-yoke` | Re-run installer | Already-installed or reinstall success screen; no duplicate PATH damage |
| `INSTALL-UV-010` | `fault-injection` | Bad channel pointer | Failure screen names reason and rerun path |
| `INSTALL-UV-011` | `fault-injection` | Package index unreachable | Failure screen is actionable; no Python traceback |
| `INSTALL-UV-012` | `prepared-screen-term` | Installer in screen/dumb terminal | ASCII/plain glyphs; no unsafe glyphs |

### Wave 3: PATH Front Door

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `PATH-001` | `prepared-path-broken` | Default `Add yoke to my PATH` | Writes managed block; verified screen lists login and SSH command results |
| `PATH-002` | `prepared-path-broken` | Preview then Add | Preview names exact startup files and block; apply succeeds |
| `PATH-003` | `prepared-path-broken` | Skip PATH repair | Account destination picker still reachable; no write |
| `PATH-004` | `prepared-yoke` | Already on PATH | All-clear screen; Continue advances |
| `PATH-005` | `prepared-path-broken` | SSH-only PATH missing | Writes `.zshenv` or SSH startup file when needed |
| `PATH-006` | `prepared-path-broken` | Re-run after path fix | Block not duplicated |
| `PATH-007` | `prepared-screen-term` | PATH screens in plain glyph mode | ASCII text only; no box drawing artifacts |
| `PATH-008` | `prepared-yoke` | Quit from post-install summary | Exits through the terminal interrupt path with durable code 130 |

### Wave 4: Account And Yoke Token

The Account step opens on the deployment-destination picker: `Where should this
Yoke live?` with choices for this machine, a team server, and upyoke.com. Enter
keeps the hosted lane, while the team-server lane asks for a Yoke server URL.

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `AUTH-001` | `prepared-yoke` | Stage env, token file | Token verified; actor/org/project summary renders; token-file placeholder reflects selected env; no token leak |
| `AUTH-002` | `prepared-yoke` | Prod env, token file | Prod API verified; active env prod after Apply |
| `AUTH-003` | `prepared-yoke` | Team-server URL via the picker's team-server lane | Server URL accepted; token verification uses it |
| `AUTH-004` | `prepared-yoke` | Token paste | Password field masks value; no capture leak |
| `AUTH-005` | `prepared-yoke` | Missing token file path | Inline/actionable error; can retry |
| `AUTH-006` | `prepared-yoke` | Empty token file | Friendly error; no crash |
| `AUTH-007` | `prepared-yoke` | Invalid token | HTTP 401 friendly error; retry path works |
| `AUTH-008` | `fault-injection` | Valid token but no org/project access | Permission copy is actionable |
| `AUTH-009` | `prepared-stored-state` | Stored token reuse | Stored credential offered and verified, not blindly trusted |
| `AUTH-010` | `prepared-stored-state` | Stored token invalid | Replacement route is available |
| `AUTH-011` | `prepared-yoke` | Token sees many projects/orgs | Projects and orgs lists truncate consistently and do not overflow |

### Wave 5: Machine GitHub App Connection

The canonical append-only `GITHUB-*` table lives in [Installer GitHub App live testing](installer-github-app-testing.md); the campaign loader composes that sibling catalog with this guide and rejects duplicate scenario ids across both documents.

### Wave 6: Project Source Picker

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `PROJECT-SOURCE-001` | `prepared-git` | Machine-only | Finish review has only machine/account writes |
| `PROJECT-SOURCE-002` | `prepared-git` | Create new project folder | Folder input accepts `~/code/name`; next metadata screen appears |
| `PROJECT-SOURCE-003` | `prepared-git` | Existing local checkout | Local path accepted; project metadata flow appears |
| `PROJECT-SOURCE-004` | `prepared-git` | Create-new points at existing code | Redirect screen says existing project setup instead |
| `PROJECT-SOURCE-005` | `prepared-git` | Clone public repo URL | Source reachable; default branch detected |
| `PROJECT-SOURCE-006` | `prepared-git` | Clone private repo with connected App | Refreshed App user access authenticates the clone without persisting in git config |
| `PROJECT-SOURCE-007` | `prepared-git` | Clone URL unreachable | Friendly reachability error, not traceback |
| `PROJECT-SOURCE-008` | `prepared-git` | Clone source default branch `master` | Branch source recorded as source repo |
| `PROJECT-SOURCE-009` | `prepared-git` | Clone destination already non-empty conflict | Inline/path error before Apply |
| `PROJECT-SOURCE-010` | `prepared-no-git` | Any checkout mode with no Git | Git prerequisite screen appears before project details |
| `PROJECT-SOURCE-011` | `prepared-no-git` | Missing Git, install with package manager | Install action runs; returns to flow when Git is available |
| `PROJECT-SOURCE-012` | `prepared-no-git-no-sudo` | Missing Git with no package manager/sudo | Manual-only guidance; no dead-end |
| `PROJECT-SOURCE-013` | `prepared-git` | Develop Yoke denied | Access-gate error friendly |
| `PROJECT-SOURCE-014` | `prepared-git` | Develop Yoke allowed | Routes to source-dev/admin plan without accidental product writes |
| `PROJECT-SOURCE-015` | `prepared-git` | Develop Yoke into a fresh folder | Post-apply: real clone with expected tree and git history; source-link symlinks and hooks present |
| `PROJECT-SOURCE-016` | `prepared-git` | Develop Yoke into an existing Yoke checkout | Detected and reused; post-apply source-link install has symlinks and hooks, no product-copy dirs |
| `PROJECT-SOURCE-017` | `prepared-git` | Develop Yoke into a non-empty non-Yoke folder | Refused before Apply; no product scaffold written; no `done` |
| `PROJECT-SOURCE-018` | `prepared-git` | Develop Yoke default folder and review wording | Default folder and review copy are correct for source-dev |
| `PROJECT-SOURCE-019` | `prepared-git` | Develop Yoke push credential | Post-apply: origin names Yoke repo and `git push --dry-run` authenticates |

### Wave 7: Project Metadata Inputs

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `PROJECT-META-001` | `prepared-git` | Valid slug/name/prefix/default branch | Reaches review |
| `PROJECT-META-002` | `prepared-git` | Empty slug | Inline validation blocks |
| `PROJECT-META-003` | `prepared-git` | Slug with invalid chars | Inline validation message |
| `PROJECT-META-004` | `prepared-git` | Very long slug | Validation/wrapping is readable |
| `PROJECT-META-005` | `prepared-git` | Empty display name | Inline validation blocks |
| `PROJECT-META-006` | `prepared-git` | Branch prefix invalid | Inline validation blocks |
| `PROJECT-META-007` | `prepared-git` | Public item prefix invalid | Inline validation blocks |
| `PROJECT-META-008` | `prepared-git` | Multiple orgs visible | Owner/org picker is clear |
| `PROJECT-META-009` | `fault-injection` | `board.data.get` failure during board-art write | Apply failure text is friendly and names the failing function and write step |
| `PROJECT-META-010` | `prepared-git` | Leading `~` immediate typing | First char preserved in input |
| `PROJECT-META-011` | `prepared-git` | Leading `~` settled typing | Path accepted; validates baseline |

### Wave 8: Publish And GitHub Adoption

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `PUBLISH-001` | `prepared-git` | Create project, no GitHub publish | No repo create planned |
| `PUBLISH-002` | `prepared-git` | Publish to user owner | Owner picker, repo name, visibility, review plan correct |
| `PUBLISH-003` | `prepared-git` | Publish to org owner | Org owner renders and applies |
| `PUBLISH-004` | `prepared-git` | Repo exists and empty | Review note says Yoke will reuse/adopt |
| `PUBLISH-005` | `prepared-git` | Repo exists non-empty | Block before Apply |
| `PUBLISH-006` | `prepared-git` | App cannot create private repo | Block before Apply |
| `PUBLISH-007` | `prepared-git` | App can create but cannot push | Block before orphaning empty repo |
| `PUBLISH-008` | `fault-injection` | Repo created then push fails | Failure report names repo, start-over cleanup, and retry resumes push |
| `PUBLISH-009` | `prepared-git` | Project uses backlog-only mode | No binding stored |
| `PUBLISH-010` | `prepared-git` | Project GitHub App binding | Project records the selected App installation/repository |
| `PUBLISH-011` | `prepared-git` | Project GitHub App binding unavailable | Project remains backlog-only; no credential secret is stored |
| `PUBLISH-012` | `prepared-git` | Project GitHub App binding reuse | Project binding traces to the installed App repository |

### Wave 9: Review, Apply, Resume

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `APPLY-001` | `prepared-yoke` | Machine-only review | Plan groups machine/account writes; Apply success |
| `APPLY-002` | `prepared-git` | Full create-project review | Machine, account, control-plane, repo-local groups visible |
| `APPLY-003` | `prepared-git` | Full clone/import review | Clone/install/board steps visible |
| `APPLY-004` | `fault-injection` | Machine config write failure | Report path and resume command shown |
| `APPLY-005` | `fault-injection` | Token store failure | No token leak; resume possible |
| `APPLY-006` | `fault-injection` | Project create failure | Friendly permission/HTTP text |
| `APPLY-007` | `fault-injection` | Clone failure | Target folder recovery instructions |
| `APPLY-008` | `fault-injection` | Publish failure | Empty repo recovery guidance if relevant; matching-origin retry does not skip push |
| `APPLY-009` | `fault-injection` | Board-art/write-board failure | Failure is grouped under repo-local write |
| `APPLY-010` | `prepared-git` | Resume after partial failure | Resume completes or reports exact remaining blocker |
| `APPLY-011` | `prepared-git` | Apply report audit | Report has `secret_free: true`; captures have no secrets |
| `APPLY-012` | `prepared-git` | Ctrl-C during Apply | Blocked or handled cleanly; no partial silent teardown |

### Wave 10: Terminal Interaction And Layout

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `TERM-001` | `prepared-git` | 80x24 terminal | Readable or scrollable; no fatal layout |
| `TERM-002` | `prepared-git` | 100x32 terminal | Matches golden-sized expectations |
| `TERM-003` | `prepared-git` | 140x40 terminal | Wide layout readable |
| `TERM-004` | `prepared-screen-term` | `TERM=screen-256color` | Plain glyphs; no unsafe glyphs |
| `TERM-005` | `prepared-screen-term` | `TERM=dumb` | Plain fallback; no unsafe glyphs; no crash |
| `TERM-006` | `prepared-git` | Up/Down on single Continue action | Selection remains stable without exposing a fake Quit action |
| `TERM-007` | `prepared-git` | Space selects | Same as Enter |
| `TERM-008` | `prepared-git` | Ctrl-J selects | Same as Enter |
| `TERM-009` | `prepared-git` | Escape backs out of each step | History works; no dead ends |
| `TERM-010` | `prepared-git` | Ctrl-C before Apply | Exits cleanly |
| `TERM-011` | `prepared-git` | Mouse reporting off under screen compat | No garbled mouse escape noise |
| `TERM-012` | `prepared-git` | Very long repo/org/project names | Wrap is readable; no overlap |

### Wave 11: Stored State And Repeatability

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `STATE-001` | `prepared-stored-state` | Reuse active Yoke connection | Verifies stored token; no blind trust |
| `STATE-002` | `prepared-stored-state` | Reuse machine GitHub App authorization | Verifies stored authorization; no blind trust |
| `STATE-003` | `prepared-stored-state` | One stored project checkout | Auto-routes to project verification |
| `STATE-004` | `prepared-stored-state` | Multiple stored project checkouts | Picker appears |
| `STATE-005` | `prepared-stored-state` | Stored project no longer visible | Friendly lookup error and alternate path |
| `STATE-006` | `prepared-stored-state` | Stage and prod credentials on same machine | Env switch works; `YOKE_ENV` override works |
| `STATE-007` | `prepared-stored-state` | Re-run onboarding after success | No duplicate config; no duplicate PATH block |
| `STATE-008` | `prepared-stored-state` | One-shot SSH command after PATH repair | `ssh host 'command -v yoke; yoke --version'` works |
| `STATE-009` | `prepared-stored-state` | Reset script then reinstall | Host returns to clean state and smoke passes |

### Wave 12: macOS Lane

These are not EC2 assignments. Use one reusable physical Mac host, one agent at a
time. Keep this lane small: the macOS happy path plus macOS-only behavior
around Apple Command Line Tools, PATH startup files, Terminal rendering, and
Screen Recording.

| ID | Host | Flow | Assertions |
| --- | --- | --- | --- |
| `MAC-001` | test Mac | Stage installer in real SSH TTY | Auto-launches wizard; PATH repair works |
| `MAC-002` | test Mac | `ssh -tt -e none` leading `~` path input | Leading `~` is preserved |
| `MAC-003` | test Mac | No Command Line Tools, no Homebrew | Apple Tools handoff screen; Check again works |
| `MAC-004` | test Mac | No Command Line Tools with sudo session | `softwareupdate` path installs tools and continues |
| `MAC-005` | test Mac | Homebrew present | Git recovery chooses `brew install git` |
| `MAC-006` | test Mac | Visible Terminal PTY bridge | Log captures TUI while child sees real terminal size; per-screen region screenshots through Terminal.app succeed |
| `MAC-007` | test Mac | One-shot SSH PATH after full onboard | `command -v uv; command -v uvx; command -v yoke` works once the wizard wrote `.zprofile` and `.zshenv` |
| `MAC-008` | test Mac | Stage + prod credentials | Env switching works without reinstalling project |
| `MAC-009` | test Mac | Develop Yoke into a fresh `~/code/yoke` | Post-apply: real clone, source-link symlinks, git hooks, and `git push --dry-run` authenticates |
| `MAC-010` | test Mac | PATH repair writes both startup files | Fresh login shell and one-shot SSH command both resolve `yoke` |

### Wave 13: Open Source Mode Closing Regression

This wave closes the public-launch mode tracks after the screen-by-screen pilot.
Every pass requires the listed post-apply state checks; a completed TUI alone is
not a pass.

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `LOCAL-BIRTH-001` | `prepared-yoke` | `yoke init --local`, then open the local universe | Post-apply: local Postgres and API are healthy; one human actor exists; no user table or signup step appears; `yoke status` and the two-view UI both reach the new universe |
| `MODE-PICKER-001` | `prepared-yoke` | Onboard destination = this machine | Post-apply: local birth completes; active connection is `local-postgres`; no hosted credential is written |
| `MODE-PICKER-002` | `prepared-yoke` | Onboard destination = team server | Server URL and OIDC sign-in are required; Post-apply: connection uses `https`; no local universe is born |
| `MODE-PICKER-003` | `prepared-yoke` | Onboard destination = upyoke.com | Post-apply: hosted sign-in completes; existing hosted projects are listed for clone/map; no duplicate project is created |
| `SELF-HOST-001` | `prepared-yoke` | Initialize the published self-host bundle, Compose up, then `yoke connect` | Post-apply: server and Postgres containers are healthy; OIDC door signs in; connected CLI reports the exact server release; mounted App key is file-only and absent from retained evidence |
| `HOSTED-CONNECT-001` | `prepared-yoke` | Sign in to upyoke.com, create an org/project backlog-only, then connect the CLI | Post-apply: platform membership maps to one tenant actor; board skeleton exists before machine mapping; CLI reuses the hosted project instead of creating another |
| `HOSTED-GITHUB-001` | `prepared-yoke` | Install the hosted GitHub App, choose a repository, create and bind its project | Post-apply: platform installation and repository inventory exist; tenant binding is active; issue sync uses installation-token auth; no user token appears in browser, reports, or project settings |
| `PORTABILITY-001` | `prepared-yoke` | Export a populated local universe and upload it to a fresh hosted org | Post-apply: stable-table digest and row counts match; hosted actor/token identities are regenerated; imported items, strategy, and projects render |
| `PORTABILITY-002` | `prepared-yoke` | Download a hosted universe and import it into a fresh local universe | Post-apply: stable-table digest and row counts match; platform identities are absent; local bootstrap actor can read the imported work |
| `UPGRADE-001` | `prepared-yoke` | Upgrade an existing local universe to the next signed release | Post-apply: release pin changes exactly once; migrations complete; data and API token remain usable; second upgrade is idempotent |
| `UPGRADE-002` | `prepared-yoke` | Pull the next signed self-host server image and restart Compose | Post-apply: image digest and version endpoint match the target release; migrate-on-boot completes; OIDC sign-in and existing project reads remain healthy |

## Render A Campaign

For a simple assignment bundle:

```bash
python3 -m yoke_core.tools.installer_live_tui_harness render-assignments \
  --plan "$CATALOG_DOC" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --endpoint "$ENDPOINT" \
  --assignment-size 5 \
  --json
```

For a coordinator-managed campaign, render the manifest, assignments, host
demand, and recipe stubs:

```bash
python3 -m yoke_core.tools.installer_live_tui_coordinator plan-campaign \
  --plan "$CATALOG_DOC" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --endpoint "$ENDPOINT" \
  --assignment-size 5 \
  --slots-per-host 1 \
  --json
```

Use `--max-scenarios N` for a small proof run. Use `--include-mac` only when the
physical Mac lane is intentionally part of the campaign run.

## Prepare Hosts

EC2 is the broad Linux lane. Use tiny hosts by default:

- Amazon Linux 2023 x86_64: `t3.micro` or `t3.small`.
- Amazon Linux 2023 arm64: `t4g.micro` or `t4g.small`.
- Ubuntu 24.04 x86_64: `t3.micro` or `t3.small`.
- Ubuntu 24.04 arm64: `t4g.micro` or `t4g.small`.

Use `small` rather than `micro` for scenarios that compile or install browser
runtime or run large Apply flows. A normal broad campaign leases about 20 hosts
in waves, runs five scenario waves, and produces about 100 assignment slots. A
stress campaign can use 60 hosts and 120 assignment slots after the collector is
stable.

Each EC2 host gets exactly one starting profile:

| Profile | Purpose | Prep |
| --- | --- | --- |
| `bare-linux` | Public installer from nothing | Shell and curl only |
| `bare-no-curl` | Missing prerequisite failure | Remove or hide curl from PATH |
| `bare-no-uv` | Missing uv consent/install path | Curl present, uv absent |
| `prepared-yoke` | Start directly at wizard | Install Yoke with onboarding disabled |
| `prepared-no-git` | Git prerequisite branch | Yoke installed, Git absent |
| `prepared-no-git-no-sudo` | Manual Git prerequisite branch | Yoke installed, Git and sudo absent |
| `prepared-git` | Project checkout branches | Yoke and Git installed |
| `prepared-path-broken` | PATH repair | Yoke installed but startup files lack managed PATH block |
| `prepared-stored-state` | Stored token/project reuse | Preloaded machine config and token files |
| `prepared-screen-term` | Plain glyphs | Run under `TERM=screen-256color`, GNU screen, or tmux screen mode |
| `fault-injection` | Expected failures | Local proxy, fake endpoint, or constrained token |

Provisioning rules:

- All AWS calls go through the project `aws-admin` capability resolver, not
  ambient AWS shell credentials.
- Restrict SSH ingress to the coordinator/operator IP or a private network route.
- Tag every resource with `Purpose=yoke-installer-tui-test`,
  `Campaign=<campaign-id>`, and `ExpiresAt=<timestamp>`.
- Terminate instances and delete temporary security groups/key pairs after the
  campaign.
- Never log raw AWS credential values.

For EC2 host work, preview first:

```bash
python3 -m yoke_core.tools.installer_live_tui_fleet fleet-plan \
  --campaign-id "$CAMPAIGN_ID" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --count 1 \
  --profile prepared-git \
  --endpoint "$ENDPOINT" \
  --json
```

Create hosts only after operator approval:

```bash
python3 -m yoke_core.tools.installer_live_tui_fleet fleet-prepare \
  --campaign-id "$CAMPAIGN_ID" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --count 1 \
  --profile prepared-git \
  --endpoint "$ENDPOINT" \
  --yoke-token-file <local-yoke-token-file> \
  --github-repo <owner/repo> \
  --execute \
  --json
```

`fleet-prepare` writes `host-ledger.json` under `CAMPAIGN_ROOT`. If a campaign
needs multiple independently prepared fleets, preserve each returned ledger path
before running another prepare command that could replace the root ledger.

Prepared hosts should record:

```bash
/home/ec2-user/.local/bin/yoke --version
/home/ec2-user/.local/bin/yoke status --json
```

Fresh status may exit nonzero before onboarding; only unexpected status error
codes should fail bootstrap.

Reset a ledgered host before reusing it:

```bash
python3 -m yoke_core.tools.installer_live_tui_fleet fleet-reset \
  --ledger "$LEDGER" \
  --target-profile bare-no-uv \
  --execute \
  --json
```

## Compile And Run Specs

The coordinator can seed known recipe stubs, compile ready recipes into
run-spec JSON, and execute them.

```bash
python3 -m yoke_core.tools.installer_live_tui_coordinator seed-recipes \
  --campaign-root "$CAMPAIGN_ROOT" \
  --endpoint "$ENDPOINT" \
  --json
```

```bash
python3 -m yoke_core.tools.installer_live_tui_coordinator compile-recipes \
  --campaign-root "$CAMPAIGN_ROOT" \
  --runs-per-spec 1 \
  --json
```

Run one compiled spec after reviewing it:

```bash
python3 -m yoke_core.tools.installer_live_tui_coordinator run-batch \
  --spec "$CAMPAIGN_ROOT/run-specs/run-spec-001.json" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --ledger "$LEDGER" \
  --execute \
  --json
```

Run multiple specs with a concurrency cap:

```bash
python3 -m yoke_core.tools.installer_live_tui_coordinator run-waves \
  --spec-dir "$CAMPAIGN_ROOT/run-specs" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --ledger "$LEDGER" \
  --max-parallel 4 \
  --execute \
  --json
```

For long runs, capture command output to a log file under
`$CAMPAIGN_ROOT/logs/` and inspect that captured file on failure. Do not stream
secrets or token file contents.

## Manual Capture

Use capture helpers for live tmux panes when a scenario is driven manually or
semi-manually.

Capture a local tmux pane:

```bash
python3 -m yoke_core.tools.installer_live_tui_capture capture \
  --campaign-root "$CAMPAIGN_ROOT" \
  --assignment-id A001 \
  --scenario-id <scenario-id> \
  --step 000-initial \
  --json
```

Capture a ledgered SSH host's tmux pane:

```bash
python3 -m yoke_core.tools.installer_live_tui_capture ssh-capture \
  --campaign-root "$CAMPAIGN_ROOT" \
  --assignment-id A001 \
  --scenario-id <scenario-id> \
  --step 000-initial \
  --ledger "$LEDGER" \
  --json
```

Send small key transitions:

```bash
python3 -m yoke_core.tools.installer_live_tui_capture ssh-send-keys \
  --ledger "$LEDGER" \
  Enter \
  --json
```

Backfill image evidence from an already retained text capture:

```bash
python3 -m yoke_core.tools.installer_live_tui_capture file-capture \
  --campaign-root "$CAMPAIGN_ROOT" \
  --assignment-id A001 \
  --scenario-id <scenario-id> \
  --step 010-after-enter \
  --source "$CAMPAIGN_ROOT/captures/A001/<scenario-id>/010-after-enter.txt" \
  --json
```

## Direct Scenario Runner

For one ledgered SSH scenario, use `run-ssh`. This starts the command, performs
capture/action steps, records expectations and post-checks, and writes a report.

```bash
python3 -m yoke_core.tools.installer_live_tui_runner run-ssh \
  --ledger "$LEDGER" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --assignment-id A001 \
  --scenario-id <scenario-id> \
  --command 'curl -fsSL https://api.stage.upyoke.com/install | bash' \
  --action 000-initial \
  --action 010-after-enter:Enter \
  --expect 'Yoke' \
  --post-check 'command -v yoke' \
  --post-check 'find "$HOME/.yoke/onboarding-runs" -maxdepth 3 -type f -name "*.json" -print' \
  --execution-mode tmux \
  --json
```

Use `--stage-file LOCAL=REMOTE` and `--stage-url URL=REMOTE` to stage token
files, fixtures, or installer scripts without printing their contents.

## Reports And Validation

Each assignment report belongs under:

```text
reports/A001.json
```

Minimum report content:

- Assignment id, host id, profile, endpoint, start and finish time.
- Scenario ids and pass/fail result per scenario.
- Paths to retained captures, screenshots, post-apply checks, and raw staging.
- Observed screen titles or key assertions.
- Failure kind, last capture, last screenshot, and repro keys when failing.
- Secret-scan result.

Validate one report:

```bash
python3 -m yoke_core.tools.installer_live_tui_harness validate-report \
  --report "$CAMPAIGN_ROOT/reports/A001.json" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --json
```

Scan retained evidence for obvious secret markers:

```bash
python3 -m yoke_core.tools.installer_live_tui_harness secret-scan \
  "$CAMPAIGN_ROOT/captures" \
  "$CAMPAIGN_ROOT/screenshots" \
  "$CAMPAIGN_ROOT/logs" \
  "$CAMPAIGN_ROOT/post-apply" \
  "$CAMPAIGN_ROOT/raw-host-staging" \
  --json
```

Collect the whole campaign:

```bash
python3 -m yoke_core.tools.installer_live_tui_harness collect-reports \
  --campaign-root "$CAMPAIGN_ROOT" \
  --json
```

A retained campaign is not green until `collect-reports` reports no evidence
issues and the secret scan is clean.

## QA Import

When campaign evidence belongs to a concrete QA gate, import it after the
campaign collector is green. Use bare numeric item ids.

Preview:

```bash
python3 -m yoke_core.tools.installer_live_tui_qa_ingest \
  --campaign-root "$CAMPAIGN_ROOT" \
  --item-id <numeric-item-id> \
  --json
```

Write QA rows:

```bash
python3 -m yoke_core.tools.installer_live_tui_qa_ingest \
  --campaign-root "$CAMPAIGN_ROOT" \
  --item-id <numeric-item-id> \
  --execute \
  --json
```

For epic task evidence, use `--epic-id <numeric-epic-id> --task-num <number>`.
For deployment-run evidence, use `--deployment-run-id <run-id>`.

## Mac Lane

The Mac lane is a serial physical-host lane. Do not fold it into an EC2 fleet
run. It exists because macOS-specific behavior cannot be reproduced on EC2:
Apple Command Line Tools prompts, `.zprofile`/`.zshenv` PATH repair,
Terminal.app rendering, Screen Recording permissions, and SSH TTY edge cases.

Use prod only for explicit release smoke. Keep trials inside the dedicated test
user's home; the reset recipe deletes Yoke, uv, token files, PATH blocks, and
`~/code` children.

### Mac Host

Current physical host:

```bash
MAC_SSH_HOST=testy@100.117.161.86
MAC_HOME=/Users/testy
```

The host is reachable by Tailscale private address, has host name `Mac`, uses
`/bin/zsh`, and is Apple Silicon `arm64`.

Use Tailscale for private reachability and macOS Remote Login for SSH. Do not
expose SSH with router port forwarding. Ordinary macOS SSH over Tailscale is
enough; Tailscale SSH is not required. Drive acceptance through a real SSH TTY or
a visible Terminal.app session, not a scripted pseudo-run.

One-time setup:

1. Install Tailscale, sign into the operator tailnet, and allow the VPN prompt.
2. Create a dedicated macOS user, for example `yoke-tester`.
3. Enable Remote Login for that user.
4. Add the operator public key to `~/.ssh/authorized_keys`.
5. Disable sleep while testing.
6. Install/unlock Claude Code for remote agent smokes; use Screen Sharing or
   Remote Management for visual observation and GUI permission prompts.

Homebrew is optional. If `brew` is on `PATH`, installer `uv` setup and project
Git recovery can use it; otherwise Yoke uses Astral `uv` and Apple Tools Git.

Preferred Remote Login path: System Settings -> General -> Sharing -> Remote
Login, then allow either all users or the dedicated test user. CLI path:

```bash
sudo systemsetup -setremotelogin on
```

Current macOS may require Full Disk Access for that CLI command. If prompted, use
the GUI path or enable Terminal under System Settings -> Privacy & Security ->
Full Disk Access and rerun it.

Run this in Terminal.app as the test user, replacing the placeholder key:

```bash
/bin/zsh <<'YOKE_SSH_SETUP'
set -eu
PUBKEY='PASTE_OPERATOR_PUBLIC_KEY_HERE'
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
if ! /usr/bin/grep -qxF "$PUBKEY" "$HOME/.ssh/authorized_keys"; then
  printf '%s\n' "$PUBKEY" >> "$HOME/.ssh/authorized_keys"
fi
/usr/sbin/chown -R "$USER":staff "$HOME/.ssh"
sudo /usr/sbin/systemsetup -setremotelogin on || echo "Enable Remote Login in System Settings or grant Terminal Full Disk Access."
sudo /bin/launchctl enable system/com.openssh.sshd 2>/dev/null || true
sudo /bin/launchctl kickstart -k system/com.openssh.sshd 2>/dev/null || true
echo "DONE: SSH key installed for $USER"
YOKE_SSH_SETUP
```

Verify from the operator machine:

```bash
ssh -tt -e none -o BatchMode=yes -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=accept-new "$MAC_SSH_HOST" \
  'printf "YOKE_SSH_OK user=%s host=%s shell=%s\n" "$USER" "$(hostname)" "$SHELL"; uname -a; id'
```

Use `-tt` for a real TTY. Use `-e none` so a leading `~` typed into the wizard is
delivered to the remote terminal instead of swallowed by the local SSH client.
Keep the host awake:

```bash
ssh "$MAC_SSH_HOST" 'sudo pmset -a sleep 0 disksleep 0 displaysleep 0 powernap 0'
```

### Mac Tokens

Stage short-lived Yoke token files on the Mac, never raw token values:

```bash
scp ./yoke-stage.token "$MAC_SSH_HOST":/tmp/yoke-stage.token
scp ./yoke-prod.token "$MAC_SSH_HOST":/tmp/yoke-prod.token
ssh "$MAC_SSH_HOST" 'chmod 600 /tmp/yoke-stage.token /tmp/yoke-prod.token'
```

In the wizard, choose token-from-file and use `/tmp/yoke-stage.token` for
stage auth. GitHub uses the Yoke GitHub App connection flow or backlog-only
skip.

### Claude Code SSH Smoke

Install Claude Code while logged into the Mac as the test user:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Complete Claude login in the Mac's GUI Terminal. Claude stores the login in the
macOS keychain; plain SSH may not read that item. Export it to Claude's
SSH-readable file:

```bash
mkdir -p ~/.claude
security find-generic-password -a "$USER" -s "Claude Code-credentials" -w \
  > ~/.claude/.credentials.json
chmod 600 ~/.claude/.credentials.json
```

If SSH gets keychain status `36`, ask the logged-in Terminal.app to run it:

```bash
ssh "$MAC_SSH_HOST" \
  'osascript -e '\''tell application "Terminal" to do script "mkdir -p ~/.claude; security find-generic-password -a \"$USER\" -s \"Claude Code-credentials\" -w > ~/.claude/.credentials.json; chmod 600 ~/.claude/.credentials.json"'\'''
```

Smoke from the operator machine:

```bash
ssh "$MAC_SSH_HOST" \
  '/bin/zsh -lc '\''export PATH="$HOME/.local/bin:$PATH"; claude -p "Reply exactly: CLAUDE_SSH_OK"'\'''
```

Operator-side hooks require `lint_db_cmd_remote_claude_cli=warn` in
`.yoke/lint-config`; local `claude` CLI invocations remain blocked.

### Stage Installer Smoke

Stage installer smoke:

```bash
ssh -tt -e none "$MAC_SSH_HOST"
curl -fsSL https://api.stage.upyoke.com/install | bash
```

Manual proof path: accept uv install if missing, accept PATH repair, confirm
handoff into `yoke onboard`, pick upyoke.com on the destination picker, choose
stage, use `/tmp/yoke-stage.token`, choose the GitHub App connection or
backlog-only skip, clone/import under `~/code`, apply, and record the report
path.

Post-run checks:

```bash
source "$HOME/.zprofile" 2>/dev/null || true
command -v uv; command -v uvx; command -v yoke; yoke --version
find "$HOME/.yoke/onboarding-runs/apply-reports" -maxdepth 1 -type f -print
grep -R '"final_status": "done"\|"secret_free": true' "$HOME/.yoke/onboarding-runs/apply-reports" || true
cd "$HOME/code/<project>"
git remote -v
git status --short --branch
test -f .yoke/install-manifest.json
test -f .yoke/BOARD.md
yoke status
yoke board
```

PATH repair must also work in one-shot SSH after full onboard:

```bash
ssh "$MAC_SSH_HOST" 'command -v uv; command -v uvx; command -v yoke; yoke --version'
```

### Stage And Prod

Stage and prod can coexist on one Mac:

```bash
yoke auth set stage --token-file /tmp/yoke-stage.token
yoke auth set prod --token-file /tmp/yoke-prod.token
yoke env use prod
yoke status
YOKE_ENV=stage yoke status
YOKE_ENV=prod yoke status
```

Interactive fallback for configuring prod without touching a project:

```bash
yoke onboard --env prod --api-url https://app.upyoke.com/api/orgs/yoke-production \
  --token-file /tmp/yoke-prod.token --project-mode machine-only --yes
yoke env use prod
```

Expected: no-env `yoke status` uses prod after `yoke env use prod`, while
`YOKE_ENV=stage yoke status` still reaches stage. A stage installer proof may
leave active env on stage; restore prod before normal operator use.

### Prod Local-Mode Cold Start

Prod local-mode cold-start smoke starts from the reset below, then runs the
product installer without launching the wizard:

```bash
ssh -tt -e none "$MAC_SSH_HOST"
curl -fsSL https://api.upyoke.com/install | bash -s -- --yes --no-onboard
export PATH="$HOME/.local/bin:$PATH"
yoke --version
yoke init --local --json
mkdir -p "$HOME/code/my-project"
cd "$HOME/code/my-project"
git init
yoke onboard project "$HOME/code/my-project" \
  --slug my-project \
  --name "My Project" \
  --default-branch main \
  --public-item-prefix MYPR \
  --github-adoption backlog-only \
  --config "$HOME/.yoke/config.json" \
  --yes \
  --json
yoke local demo seed --project my-project --json
yoke board rebuild --print --no-pager
```

Capture the live TTY after each major step. For the installer and any visible TUI
step, use the region screenshot procedure below; the bridge log or SSH transcript
is the fallback when macOS blocks image capture.

Then prove the local dashboard:

```bash
cd "$HOME/code/my-project"
yoke ui --host 127.0.0.1 --port 8787
```

From the operator machine:

```bash
ssh -N -L 8787:127.0.0.1:8787 "$MAC_SSH_HOST"
```

Open `http://127.0.0.1:8787`, verify seeded items and board data are visible, and
save a screenshot under the campaign root. If Browser QA is available on the Mac,
`yoke qa browser screenshot` is acceptable; otherwise the SSH tunnel plus local
browser screenshot is the required fallback.

### Session Registration And Telemetry

Use this after a stage or prod publish that touches hooks, auth, session identity,
lane routing, telemetry, or board rendering. Run from visible Terminal or a real
SSH TTY so the user can watch the same terminal.

```bash
cd "$HOME/code/buzz"
YOKE_ENV=stage yoke status
YOKE_ENV=stage claude -p 'Reply exactly: YOKE_STAGE_SESSION_SMOKE_OK'
YOKE_ENV=stage yoke board rebuild --print --no-pager
```

The board should show a fresh Buzz session. Verify the control plane:

```bash
YOKE_ENV=stage yoke db read "SELECT session_id, project_id, actor_id, executor, display_name, model, execution_lane, workspace, ended_at FROM harness_sessions WHERE project_id = 2 ORDER BY started_at DESC LIMIT 5"
YOKE_ENV=stage yoke events query --project buzz --since '20 minutes ago' --limit 50
```

Expected stage evidence: `project_id=2`, executor/model/lane populated,
DB-backed lane such as `DARIUS`, no hook-denied errors, session events carrying
the same project id, and visible board newest session matching the DB row.
Angle-bracket Claude model values are temporary SDK placeholders and should be
upgraded by later concrete registration.

For hosted API logs, check CloudWatch from the operator machine with AWS operator
credentials, not from the test Mac:

```bash
aws logs filter-log-events --log-group-name /yoke/stage/core \
  --start-time <epoch-ms-before-smoke> --filter-pattern '"POST /v1/hooks/evaluate"'
aws logs filter-log-events --log-group-name /yoke/stage/core \
  --start-time <epoch-ms-before-smoke> --filter-pattern '?ERROR ?Error ?error ?Traceback ?Exception'
```

Expected CloudWatch evidence: hook relay requests return HTTP `200`, include the
expected actor/token/request ids, and the error scan is clean.

### Visual User Testing Mode

Use this mode when the question is, "What would a person see on the Mac?" It is
the preferred evidence path for installer/wizard walkthroughs. The wizard runs
directly in Terminal.app, input is delivered as macOS keystrokes, and each step is
captured from the Terminal window region. Do not substitute text-rendered PNGs or
local browser captures for this mode unless Terminal.app capture is blocked.

Before starting, set the campaign variables and keep the Mac unlocked with the
display awake:

```bash
MAC_SSH_HOST=testy@100.117.161.86
MAC_HOME=/Users/testy
CAMPAIGN_ROOT="$HOME/.yoke/installer-smoke-evidence/<campaign-id>"
ASSIGNMENT_ID=A001
SCENARIO_ID=MAC-STAGE-UI-001
mkdir -p "$CAMPAIGN_ROOT/screenshots/$ASSIGNMENT_ID/$SCENARIO_ID" \
  "$CAMPAIGN_ROOT/logs" "$CAMPAIGN_ROOT/reports"
ssh "$MAC_SSH_HOST" 'caffeinate -u -t 1 || true'
```

Install or reinstall from the target channel before opening the wizard. For a
stage publish smoke, install from the stage public installer and skip automatic
onboarding so the visual run starts from a clean Terminal.app command:

```bash
ssh "$MAC_SSH_HOST" \
  'curl -fsSL https://api.stage.upyoke.com/install | bash -s -- --yes --no-onboard'
ssh "$MAC_SSH_HOST" \
  "$MAC_HOME/.local/bin/yoke --version; $MAC_HOME/.local/bin/yoke status"
```

Launch the wizard in a real Terminal.app window. Set the final window bounds
before the command starts; resizing after Textual has painted can leave an old
screen visible below the current one. Keep the lower bound above the Dock so
screenshots do not include it.

```bash
ssh "$MAC_SSH_HOST" '/bin/zsh -s' <<'REMOTE'
set -eu
rm -f /tmp/yoke-installer-window-id
/usr/bin/osascript <<'OSA'
tell application "Terminal"
  activate
  set wizardTab to do script ""
  set wizardWindow to front window
  set bounds of wizardWindow to {66, 90, 1566, 820}
  do shell script "printf %s " & quoted form of ((id of wizardWindow) as text) & " > /tmp/yoke-installer-window-id"
  delay 0.5
  do script "printf '\\033c'; exec $HOME/.local/bin/yoke onboard --post-install" in wizardTab
end tell
OSA
cat /tmp/yoke-installer-window-id
REMOTE
```

Drive the wizard the way a user would. Use System Events key codes against the
front Terminal window. If macOS blocks System Events with an Accessibility prompt,
grant Terminal.app access under System Settings -> Privacy & Security ->
Accessibility, or drive the same keys manually through Screen Sharing.

```bash
# Return
ssh "$MAC_SSH_HOST" '/usr/bin/osascript <<OSA
tell application "Terminal"
  set index of window id (do shell script "cat /tmp/yoke-installer-window-id") to 1
  activate
end tell
tell application "System Events" to key code 36
OSA'

# Down, then Return
ssh "$MAC_SSH_HOST" '/usr/bin/osascript <<OSA
tell application "Terminal"
  set index of window id (do shell script "cat /tmp/yoke-installer-window-id") to 1
  activate
end tell
tell application "System Events"
  key code 125
  key code 36
end tell
OSA'

# Up, Up, then Return
ssh "$MAC_SSH_HOST" '/usr/bin/osascript <<OSA
tell application "Terminal"
  set index of window id (do shell script "cat /tmp/yoke-installer-window-id") to 1
  activate
end tell
tell application "System Events"
  key code 126
  key code 126
  key code 36
end tell
OSA'
```

For typed input, use `keystroke` after focusing the wizard window. Never type raw
secret values into a command or transcript; use token-file flows and type only
the token file path.

```bash
ssh "$MAC_SSH_HOST" '/usr/bin/osascript <<OSA
tell application "Terminal"
  set index of window id (do shell script "cat /tmp/yoke-installer-window-id") to 1
  activate
end tell
tell application "System Events"
  keystroke "/tmp/yoke-stage.token"
  key code 36
end tell
OSA'
```

Capture every screen after a short render wait. Run `screencapture` from
Terminal.app through a helper Terminal window; direct SSH `screencapture` often
fails with `could not create image` and may not show a permissions dialog. The
helper window must sit outside the captured rectangle, and the screenshot region
should come from the wizard Terminal window bounds rather than
`screencapture -l`, because Terminal AppleScript ids are not CoreGraphics window
ids.

```bash
STEP=000-installed-summary
ssh "$MAC_SSH_HOST" "/bin/zsh -s" <<REMOTE
set -eu
STEP="$STEP"
TARGET_ID=\$(cat /tmp/yoke-installer-window-id)
OUT=/tmp/yoke-installer-\${STEP}.png
rm -f "\$OUT"
/usr/bin/osascript <<OSA
tell application "Terminal"
  set targetWindow to window id \$TARGET_ID
  set bounds of targetWindow to {66, 90, 1566, 820}
  delay 0.2
  set b to bounds of targetWindow
  set leftPos to item 1 of b
  set topPos to item 2 of b
  set rightPos to item 3 of b
  set bottomPos to item 4 of b
  set widthVal to rightPos - leftPos
  set heightVal to bottomPos - topPos
  set shotCmd to "/bin/sleep 0.5; /usr/sbin/screencapture -R" & leftPos & "," & topPos & "," & widthVal & "," & heightVal & " -o " & quoted form of "\$OUT" & "; /usr/bin/sips -Z 1500 " & quoted form of "\$OUT" & " >/dev/null 2>&1; echo YOKE_SCREENSHOT_DONE"
  do script shotCmd
  set helperWindow to front window
  set bounds of helperWindow to {40, 850, 1540, 900}
  set index of targetWindow to 1
  activate
end tell
OSA
for i in 1 2 3 4 5 6 7 8; do
  [ -s "\$OUT" ] && break
  sleep 0.5
done
ls -l "\$OUT"
REMOTE
scp -q "$MAC_SSH_HOST:/tmp/yoke-installer-$STEP.png" \
  "$CAMPAIGN_ROOT/screenshots/$ASSIGNMENT_ID/$SCENARIO_ID/$STEP.png"
file "$CAMPAIGN_ROOT/screenshots/$ASSIGNMENT_ID/$SCENARIO_ID/$STEP.png"
```

Name screenshots in traversal order with stable, descriptive step names, for
example:

```text
000-installed-summary.png
010-path-status.png
020-destination-picker.png
030-local-universe.png
040-github-choice.png
050-existing-project-reuse.png
060-project-token-error.png
070-project-choice.png
080-review-apply.png
090-setup-complete.png
```

For a local-mode reinstall smoke, the current expected visual path is: continue
from the installed summary, continue past PATH status, choose `This machine` on
the destination picker, continue from the local-universe explanation, skip
GitHub, inspect existing-project reuse, capture any project-reuse error, go
Back, choose `Don't set up a project now`, review, Apply, and capture the setup
complete report path. If existing local-project reuse requires a Yoke API token
while the destination is `This machine`, record it as a product bug and finish
through the machine-only path.

For each visual run, retain:

- The exact installed `yoke --version` and `yoke status`.
- The public installer URL/channel used.
- Every Terminal-window screenshot under `screenshots/<assignment>/<scenario>/`.
- The apply report JSON under `reports/`.
- Any product bug field-note ids and the screenshot step that proves them.

### Visible Terminal Capture

This is the fallback/debug path when the operator needs machine-readable screen
text, FIFO-driven input, or an unattended run. For user-facing visual testing,
prefer the real Terminal.app recipe above. SSH TTY output is authoritative.
Screenshots depend on macOS Screen Recording and Automation permissions; if
direct SSH `screencapture` fails, ask the logged-in Terminal.app to run it
through `osascript`. For visible TUI probes, keep the TUI attached to the
Terminal TTY; redirecting stdout through `tee` before Textual starts can make
Textual paint a smaller rectangle.

For visible TUI runs after Yoke is installed, use the packaged bridge so the TUI
sees the real terminal size while input comes from a FIFO:

```bash
"$MAC_HOME/.local/share/uv/tools/yoke-cli/bin/python" \
  -m yoke_cli.config.visible_terminal_pty_bridge \
  --fifo /tmp/yoke-visible-tui.fifo --log /tmp/yoke-visible-tui-pty.log \
  --status /tmp/yoke-visible-tui.status -- \
  /usr/bin/env TERM=xterm-256color YOKE_ENV=stage \
"$MAC_HOME/.local/bin/yoke" onboard --post-install
```

To run `yoke onboard` from the operator machine with no human at the keyboard
while seeing each rendered screen:

1. Install non-interactively so no consent prompt blocks the run:
   `curl -fsSL https://api.stage.upyoke.com/install | bash -s -- --yes --no-onboard`.
   Then invoke `yoke` by absolute path because `--no-onboard` skips PATH repair.
2. Run `yoke onboard` under the bridge above inside a Terminal.app window. Input
   comes from the FIFO, not the keyboard. Create the wizard window, set its final
   bounds, and only then launch the bridge in that existing window:

   ```bash
   osascript <<'OSA'
   tell application "Terminal"
     activate
     set wizardTab to do script "printf wizard-ready"
     delay 1
     set wizardWindow to front window
     set bounds of wizardWindow to {40, 60, 1540, 980}
     set wizardWindowId to id of wizardWindow

     set helperTab to do script "printf helper-ready"
     delay 1
     set helperWindow to front window
     set bounds of helperWindow to {40, 1000, 1540, 1220}
     set helperWindowId to id of helperWindow

     do script "zsh /tmp/launch.sh" in window id wizardWindowId
     return (wizardWindowId as string) & "," & (helperWindowId as string)
   end tell
   OSA
   ```

   Do not launch the bridge and resize the window afterward: Textual may keep the
   initial short terminal height for the active screen and leave the previous
   screen visible below it.
3. Send keystrokes by writing raw bytes to the FIFO: `printf '\r' >
   /tmp/yoke-visible-tui.fifo` for Enter, `printf '\033[B' >
   /tmp/yoke-visible-tui.fifo` for Down, and plain text for input fields.
4. Screenshot each screen after a brief render wait.

Screenshot rules:

- SSH TTY output is authoritative; screenshots are optional when macOS
  permissions block them.
- The Mac must be unlocked and the display awake. A locked Mac captures only the
  lock screen; an asleep display can produce a black frame or `could not create
  image`. Wake it with `caffeinate -u -t 1`; a locked Mac needs a human to unlock
  it once.
- Do not use `screencapture -l <window-id>` with Terminal AppleScript ids.
  Terminal's AppleScript window id is not a CoreGraphics window number. Capture
  the Terminal window's region: get `left,top,right,bottom` bounds through
  AppleScript, calculate width and height, then run
  `screencapture -R<left>,<top>,<width>,<height> -o /tmp/shot.png` through
  Terminal.app. Terminal.app holds Screen Recording permission; direct SSH often
  does not.
- Downscale with `sips -Z 1500 /tmp/shot.png`, then `scp` the image back.
- The bridge log is the authoritative fallback when screenshots are blocked.
  Strip ANSI to read the current screen as text:

  ```bash
  tr -d '\000' < /tmp/yoke-visible-tui-pty.log | perl -pe 's/\x1b\[[0-9;?]*[A-Za-z]//g'
  ```

- Wait for the next screen before typing into input fields; network checks can
  drop early keystrokes. Read the bridge log to confirm the expected screen is
  up before typing.
- In the Claude harness, a short sleep before capture may trip the long-command
  polling guard. Use `# lint:no-polling-check` on those per-screen capture
  commands; they are interactive render waits, not background-command polling.

### Source-Dev Post-Apply

After a "Develop Yoke itself" Apply reaches `final_status: done` and the TUI
exits, the deferred editable install prints `Dev environment ready`. Verify the
on-disk ground truth:

- The tool-venv python resolves `yoke_core` from
  `<checkout>/packages/yoke-core/src`.
- `.yoke/install-manifest.json` is `mode: source-link`.
- `.claude/agents` is a symlink.
- `.git/hooks/pre-commit` exists.
- The checkout is registered under `projects` in `~/.yoke/config.json`, not a
  stray `yoke-machine-config.json`.
- `YOKE_ENV=stage yoke status` reaches stage.
- The Review screen shows distinct `On this machine (~/.yoke)` and
  `Already on this machine (~/.yoke)` sections, not a duplicated header.

Two gotchas:

- `--no-onboard` skips the wizard's PATH repair. A bare `--no-onboard` install
  leaves `yoke`/`uv` visible only to interactive shells because the managed block
  lands in `~/.zshrc`. The wizard's PATH step writes `.zprofile` and `.zshenv`,
  and only then does a one-shot non-interactive SSH command resolve `yoke`.
- Preserve tokens across a cold-start reset. The reset wipes `/tmp/yoke-*.token`.
  To reset-then-reinstall while keeping auth, copy token files to a reset-safe
  directory first, such as `~/yoke-smoke-tokens/`, and restore them to `/tmp`
  after install. Never re-type the token value. When wiping the backup directory,
  remove it with an explicit path, not a trailing glob: zsh aborts the whole `rm`
  line when a glob like `/tmp/yoke*.log` has no match.

Board rendering caveat: Terminal.app and iTerm2-style terminals render rich art.
GNU Screen, dumb terminals, and one-shot SSH commands with no `TERM` render plain
ASCII plus a terminal-mode explanation. This applies only to terminal board
commands such as `yoke board` and `yoke board rebuild --print`; it must not block
`yoke onboard`. Use `--no-pager` for one-shot SSH smokes so the command cannot
stop inside `less`.

### Git And Xcode

macOS Git may be an Apple developer-tools shim. Do not use `git --version` or
`xcode-select -p` as no-Command-Line-Tools preflight checks; either can open
Apple's installer prompt before Yoke shows its recovery screen. Also avoid
`/usr/bin/python3` during no-Command-Line-Tools preflight because it can route
through the same shim. Use noninvasive checks first:

```bash
printf 'git shim: '; command -v git || true
printf 'clt git: '; test -x /Library/Developer/CommandLineTools/usr/bin/git && echo present || echo missing
printf 'brew: '; command -v brew || echo missing
printf 'sudo -n: '; sudo -n true >/dev/null 2>&1; printf '%s\n' "$?"
```

Cases to prove:

- Already installed: `clt git: present`; project setup should not show Git
  recovery.
- No Command Line Tools, no Homebrew, no noninteractive sudo: project setup shows
  `Git is required for project setup`; `Install Apple Tools` opens
  `/usr/bin/xcode-select --install`; Yoke waits on `Finish Apple's installer`;
  `Check again` verifies.
- No Command Line Tools, no Homebrew, noninteractive sudo: after `sudo -v` in the
  same visible Terminal process tree, Yoke installs `Command Line Tools for
  Xcode-*` with `softwareupdate -i`, switches to
  `/Library/Developer/CommandLineTools`, and verifies Git.
- Homebrew present: Yoke uses `brew install git`.

Evidence after a real install:

```bash
xcode-select -p
git --version
find "$HOME/.yoke/onboarding-runs" -maxdepth 3 -type f -name '*.json' -print
```

Returning to no-Command-Line-Tools is system-level destructive setup and needs
explicit operator approval:

```bash
sudo rm -rf /Library/Developer/CommandLineTools
sudo xcode-select --reset || true
```

### Mac Reset

Run as the dedicated test user:

```bash
set -eu
rm -rf "$HOME/.yoke" "$HOME/.yoke-e2e-logs" "$HOME/.local/share/uv" \
  "$HOME/.local/state/uv" "$HOME/.cache/uv" "$HOME/.config/uv" \
  "$HOME/Library/Caches/uv" "$HOME/Library/Application Support/uv" \
  "$HOME/Library/Application Support/yoke"
rm -f "$HOME/.local/bin/yoke" "$HOME/.local/bin/uv" "$HOME/.local/bin/uvx" \
  "$HOME/.local/bin/env" /tmp/yoke-install /tmp/yoke-token \
  /tmp/yoke-stage.token /tmp/yoke-prod.token
[ ! -d "$HOME/code" ] || /usr/bin/find "$HOME/code" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
if [ -x /opt/homebrew/bin/brew ] && /opt/homebrew/bin/brew list --versions uv >/dev/null 2>&1; then
  /opt/homebrew/bin/brew uninstall uv
fi
for file in "$HOME/.zprofile" "$HOME/.zshenv" "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.bashrc" "$HOME/.profile"; do
  [ -e "$file" ] || continue
  tmp="${file}.tmp.$$"
  /usr/bin/awk '/BEGIN YOKE MANAGED PATH/ {skip=1; next} /END YOKE MANAGED PATH/ {skip=0; next} /uv was installed/ {next} /\. "\$HOME\/\.local\/bin\/env"/ {next} /source "\$HOME\/\.local\/bin\/env"/ {next} !skip {print}' "$file" > "$tmp"
  mv "$tmp" "$file"
done
echo "YOKE_MAC_WIPE_OK"
```

Verify the wipe:

```bash
/bin/zsh -lic 'command -v yoke || echo yoke-not-found; command -v uv || echo uv-not-found; command -v uvx || echo uvx-not-found'
/bin/zsh -c 'command -v yoke || echo ssh-yoke-not-found'
```

Mac evidence belongs in the operator-approved campaign root and should be
validated by the same `secret-scan`, `validate-report`, and `collect-reports`
commands where practical.

## Cleanup

Clean up EC2 resources with the ledger that created them:

```bash
python3 -m yoke_core.tools.installer_live_tui_fleet fleet-cleanup \
  --ledger "$LEDGER" \
  --execute \
  --json
```

Use `--keep-key-file` only when the operator explicitly wants to retain the
generated private key file for later host access.

Archive superseded evidence by moving it under:

```text
<campaign-root>/evidence-archive/<timestamp-or-reason>/
```

Do not delete retained evidence unless the operator explicitly says it is
scratch or duplicate material.

## Closeout Checklist

Before calling a campaign complete:

- Campaign root was chosen by the operator and recorded in the summary.
- Endpoint, channel, source commit/version, and public installer URL were
  recorded.
- Every scenario has a report row with pass, fail, or blocked.
- Every pass has retained evidence and post-apply truth checks.
- Secret scan is clean.
- `collect-reports` is green or remaining issues are explicitly explained.
- Confirmed product bugs have scenario ids, host profile, endpoint version,
  capture path, screenshot path if available, repro keys, and expected vs
  observed behavior.
- EC2 resources are cleaned up or intentionally retained with operator approval.
- QA import is complete when the campaign is tied to a QA gate.
