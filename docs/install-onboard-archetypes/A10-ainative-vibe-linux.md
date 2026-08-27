# A10 — Riley, AI-native, vibe-coded mess, Linux, GitHub no CI, no deploy

**Vector:** AI-native · vibe-coded · hosting none · Linux · GitHub without CI ·
deploy none.

Riley generated an app in Cursor over a weekend, pushed to a public GitHub
repo, never deployed. They install Yoke to "make it real".

## Fit / break / gaps

| | |
|---|---|
| Fits | Linux install. Clone from GitHub **or** existing folder. Connect GitHub. Skip hosting. Scaffold mapped. |
| Breaks | Clone path assumes GitHub URL/App. Profile still pushes web deploy. Vibe-coded repo has no test command for later QA cases. |
| Gaps | "No deploy yet" profile. Teaching that seed work ≠ first production URL. |

## Transcript — installer + wizard

Linux. uv Astral consent Yes. This machine. Connect GitHub.

Project: **Clone a project from GitHub.**

```
Is the repo public or private?
Public repos clone from a URL; private ones come from your GitHub account.
  Public      paste its git URL
  Private     pick from your GitHub repos
```

**User:** Public.

Paste URL `https://github.com/riley/vibe-todo.git`. Clone folder default
`~/code/vibe-todo`.

```
How do you want to copy riley/vibe-todo?
  Clone it        push straight back to riley/vibe-todo   (if push_access)
  Duplicate it    push to a new remote repo we'll create
  Fork it         … (read-only variant only, when keep_fork)
```

**User:** Clone it (they own it).

Slug `vibe-todo`, name `vibe-todo`, prefix `VIBE`, bind **Use connected repo**.
Skip hosting. Apply.

## Transcript — `/yoke onboard`

Survey: one `app.py` or `index.html`, no tests, no CI. Strategy: "finish the
product". Profile proposes `webapp-scaffold` — **conflict with existing
files** must map, not overwrite (`profile-and-scaffold.md`).

Hosting deferred. The profile offers only merge-only or no default; it cannot
confirm a persistent environment. Riley chooses **no default** while the
product has no host. Step 5 verifies the empty readback and creates no site,
environment, or flow. Merge-only remains available if they want every item to
carry the local-merge contract.

Seed from CURRENT-PLAN creates implementation issues without a deploy flow.

## Test setup

**Reality:** vibe-coded — **no tests**, no CI. The explicit no-tests
archetype (with A01/A08/A12).

**Bind today:** nothing honest. `webapp-scaffold` would conflict and must
map, not overwrite — so Pack tests do not land.

**Onboard:** survey records "no tests" as a fact and never asks what the
QA gate should mean.

**Ask that should happen:** offer a **minimal** suite (one pytest/vitest
file, not a full Pack overwrite); if declined, **attest no-tests** so
reviewing-implementation seeds `implementation_review`. Refuse registering
`pytest` or `command-ci`. Recommendation in [test-setup.md](test-setup.md).

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| Deploy | Profile | No persistent default until a host exists | Route A / omit flow |
| CI | Optional `ci_workflow_file` | QA command-ci unreachable named reason | Local tests when they exist |
| Merge target | GitHub App bind | Skip GitHub → local only | They did bind — PRs possible |

Ledger: G-test-setup-unasked, G-no-tests-posture.
