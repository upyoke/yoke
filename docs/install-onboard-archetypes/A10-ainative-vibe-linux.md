# A10 — Riley, AI-native, vibe-coded mess, Linux, GitHub no CI, no deploy

**Vector:** AI-native · vibe-coded · hosting none · Linux · GitHub without CI ·
deploy none.

Riley generated an app in Cursor over a weekend, pushed to a public GitHub
repo, never deployed. They install Yoke to "make it real".

## Fit / break / gaps

| | |
|---|---|
| Fits | Linux install. Clone from GitHub **or** existing folder. Connect GitHub. Skip hosting. Scaffold mapped. |
| Breaks | Clone path assumes GitHub URL/App. A missing suite needs an explicit test posture before QA binding. |
| Gaps | "No deploy yet" profile. Teaching that seed work ≠ first production URL. |

## Transcript — installer + wizard

Linux. uv installs automatically when absent. This machine. Connect GitHub.

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

Map existing files without overwriting them. Offer a minimal project-native suite when none exists; if declined, record the operator's no-tests reason. Register only actual runnable argv. No eligible Actions test workflow means no command-ci or queue. A missing suite cannot silently become an empty QA gate.

The confirmed profile, command/CI binding and immutable QA attachment follow
[test-setup.md](test-setup.md); this example is not a live setup receipt.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| Deploy | Profile | No persistent default until a host exists | Route A / omit flow |
| CI | Optional `ci_workflow_file` | QA command-ci unreachable named reason | Local tests when they exist |
| Merge target | GitHub App bind | Skip GitHub → local only | They did bind — PRs possible |

No unresolved test-setup gap is asserted by this example.
