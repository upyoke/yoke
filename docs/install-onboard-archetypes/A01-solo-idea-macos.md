# A01 — Alex, solo, idea-only, macOS, no remote, no deploy

**Vector:** solo · idea-only · hosting none · macOS · no remote · deploy none.

Alex has a product idea, no repo yet, a MacBook, and does not want a cloud
account. Goal: get Yoke locally and start capturing work.

## Fit / break / gaps

| | |
|---|---|
| Fits | Local destination ("This machine", free, no account). Create-new project with no GitHub. Hosting skip. Confirm merge-only or no default and seed work without a live deploy. |
| Breaks | No delivery mismatch: the profile does not offer a persistent environment while hosting is deferred. |
| Gaps | The remaining setup question is an honest test posture for an idea-only repository. |

## Transcript — public installer

Command: `curl -fsSL https://upyoke.com/install | sh`

OS check in the shim: `Darwin|Linux` — macOS passes.

If `uv` is missing:

```
[branded figlet welcome]
☀  Your operating system for software delivery

☀ Installing uv
☀ uv installed
```

uv installs automatically via the official Astral installer — no
confirmation prompt. The shim then runs
`uv run --isolated --no-project python` on the downloaded `install.py`.

```
☀ Setting up Yoke…
☀ Yoke v{channel version} is ready
☀ Starting Yoke onboard…
```

The shim launches `yoke onboard --post-install` with no extra consent.

## Transcript — `yoke onboard` wizard

### Install / PATH (`onboard_wizard_path.py`)

The wizard starts directly at PATH readiness and shows the installed version
as compact status. If PATH needs a fix:

```
Add {brand} to your PATH.
Yoke lives in {tool_bin_dir} (your zsh shell).
This shell sees: …
A new Terminal login shell sees: …
  Add yoke to my PATH     (updates your shell startup file)
  See exactly what changes
  Skip
```

**User:** Add yoke to my PATH.

The write and fresh-shell verification happen immediately after that one
confirmation. **See exactly what changes** remains optional.

### Account (`DESTINATION_ROWS`)

```
Where should this Yoke universe live?
Keep the engine and database on your machine, or use a server for team collab.
  This machine                                   free · best for solo dev
  A team server                    the URL of your team's self-hosted Yoke server
  Set this machine up as a self-hosting server   Docker Compose · guided first boot
  upyoke.com                                          hosted by Yoke · private beta
```

**User:** This machine.

```
Your Yoke lives on this machine.
Free, no account — everything stays on this computer.
  • Apply creates a private local universe under ~/.yoke
    (embedded Postgres, the full Yoke schema).
  Continue
```

**User:** Continue.

### GitHub (`MACHINE_GITHUB_TITLE`)

```
Connect GitHub?
Use the Yoke GitHub App to authorize this machine for local repo
operations, or stay disabled.
  Connect GitHub     open the Yoke GitHub App flow
  Skip GitHub        connect later
```

**User:** Skip GitHub. (no remote)

### Project (`MODE_ROWS`)

```
Set up a project.
Where's the code? You can change this later.
  Existing folder on my machine     git repo or not
  Clone a project from GitHub       into a new folder
  Create a new project              new folder, optionally also created on GitHub
  Edit Yoke source               use a checkout or clone any fork · dogfood or contribute
  Don't set up a project now        just the machine
```

**User:** Create a new project.

```
Name your new project folder.
Where should Yoke create it? It makes the folder and a git repo.
  ~/code/my-project
```

**User:** `~/code/notebook-app`

```
Project details.
Enter advances fields; Enter on the last field validates the form.
  Project ID       notebook-app
  Display name     notebook-app
  Default branch   main
  Item prefix      NOTEBO
```

**User:** Changes the display name to `Notebook App`, keeps the prefilled
values, and submits the form.

```
Also publish to GitHub?
Yoke creates the repo with GitHub authorization and connects it as your remote.
  Yes — publish to GitHub     create + connect the repo
  No — keep it local          you can publish later
```

**User:** No — keep it local.

### Board art

```
Preview your board map.
The map spelling starts from your project details and can be edited here.
  Looks good — continue
  Edit the map word
```

**User:** Accepts the map spelling, picks ASCII, then chooses **Save and
continue** on the header preview. The gallery appears only after deliberately
saving more than one header.

### Hosting

```
Connect your hosting provider?
AWS is the one Yoke can run for you; hosting it yourself is a fine answer.
  AWS                    Yoke can manage its infrastructure
  I host this myself     Yoke applies no infrastructure
  Decide later           /yoke onboard asks again
```

**User:** Decide later. (no AWS, no hosting)

### Review

```
Review what Yoke will save.
Nothing is written until you choose Apply. The default view shows counts and
one concise machine/core/project row.
  Apply               writes the summarized plan
  Show all changes    exact complete plan
  Cancel              nothing is saved
```

**User:** Apply.

Apply creates the local universe, writes machine config, creates
`~/code/notebook-app` as a git repo on `main`, registers project
`notebook-app` with prefix `NOTE`, GitHub adoption disabled.

### Setup complete

```
✓ Setup complete.
Everything in the Review plan was applied.
✓ Board art ready
✓ Session relay ready
  Exit
  Show report
```

After **Exit**, the installer prints its execution-ready handoff (reload the
current shell only if needed, open a supported harness in the project, then run
`/yoke onboard`). This is terminal guidance after completion, not a TUI
congratulations click-through.

**User** opens Cursor in `~/code/notebook-app` and runs `/yoke onboard`.

## Transcript — `/yoke onboard` skill

Init: `yoke onboard checklist init --project notebook-app --checkout ~/code/notebook-app --json`

1. Strategy: `yoke strategy seed-defaults`, then drafts MISSION / VISION /
   MASTER-PLAN / LANDSCAPE / CURRENT-PLAN. Agent asks only what the empty
   repo cannot answer. Writes via `yoke strategy doc replace`.
2. Profile confirmation (stop 1 of 2). Proposal from
   `profile-and-scaffold.md`: keep or skip the local scaffold, omit AWS Packs
   and `aws-admin`, and choose exactly one delivery outcome. Alex chooses
   **merge-only**: local merge, no environment, and no deployment pipeline.
   No default is the equally valid alternative.
3. **User** confirms the named delivery choice rather than deleting a stock
   persistent environment from the proposal.
4. Hosting remains undecided, so no `aws-admin` probe runs. Operator records
   `hosting-setup=deferred`; step 7 is unreachable and step 8 still runs.
5. Step 5 creates `notebook-app-merge-only`, verifies its empty target tier,
   and reads it back as the project default without creating a site or
   environment. Seeded issues receive that flow; Usher routes it through
   Route A without `deployment-runs start-for-item`. If Alex chose no default,
   the empty readback instead makes seed-work omit `--deployment-flow`.

## Test setup

**Reality:** empty repo — **no tests**. If they accept `webapp-scaffold`,
pytest / Vitest / Playwright examples and `.github/workflows/ci.yml` land
unregistered.

**Bind today:** after scaffold, `registered-command-quick` names the Pack's
test argv and carries a project target; `ci_workflow_file` can name `ci.yml`.
No hosting environment or stage/prod placeholder is required.

**Onboard:** wizard never asks. Profile never proposes a command or
`ci_workflow_file`. Seed attaches a plan only if CURRENT-PLAN already names
one.

**Ask that should happen:** "No tests yet — install the scaffold suite,
attest no-tests, or stop?" Recommend scaffold, else attested no-tests
(`implementation_review`). Refuse inventing `command-ci`. See
[test-setup.md](test-setup.md).

## Crux

| Requirement | Where it should be declared | Refusal when absent | Instead |
|---|---|---|---|
| Deployment / environment | Execution-profile confirmation: hosting and env are optional; default flow may be merge-only (`target_tier` NULL) or unset | Usher Route A / omit `--deployment-flow`; never stamp a persistent flow | Local merge, no pipeline |
| GitHub merge target | Already optional (Skip GitHub / keep local) | GitHub automation disabled until App sees the repo | Local default branch `main` |
| Migration | Step-2 governed-database box | — | An empty repo answers "no governed database"; `migration-model-setup` records `not-needed` |
| Tests | Profile test-setup box (missing) | Do not register a command that is not in the tree | Scaffold suite or attested no-tests |

Ledger: G-installer-handoff-cursor, G-test-setup-unasked, G-no-tests-posture, G-scaffold-tests-unregistered, G-qa-plan-needs-env.
