# Install

```bash
curl -fsSL https://upyoke.com/install | sh
yoke onboard
yoke status
```

Prerequisites: a shell, `curl`, and `uv` (the installer can install `uv` with
consent). You are not asked to bring your own Python. Native Windows is
unsupported; WSL follows the Linux path.

## Onboard wizard

`yoke onboard` is a full-screen wizard:

1. **Install / PATH** — confirm the CLI
2. **Account** — where Yoke lives (this machine / team server / upyoke.com)
3. **GitHub** — optional App connect for product GitHub commands
4. **Project** — create, clone, import, or bind a checkout. A clone is
   fetched here, not at Apply, so you see what the repository holds — and
   decide what happens to any Yoke files it already carries — first
5. **Review** — preview persistent writes, then apply

Anything the wizard already finds — a checkout carrying Yoke files, a
repository that already has a project, a checkout already mapped on this
machine — is announced before you answer anything, and connecting to what
exists is the default. The mouse scrolls and clicks normally; on any screen
showing a URL or a one-time code the footer names a copy key (`^y`) and an
open-in-browser key (`^o`) instead of a native drag-select.

Flags: `--yes` for non-interactive apply; `--local` or `--connect URL` to skip
the destination picker.

## After onboard

Reload PATH if the installer added it (this terminal only), then open Claude
Code, Codex, or Cursor in your project folder and run `/yoke onboard`.

```bash
yoke status          # machine, env, credentials, checkouts
yoke ui up           # local workbench (local mode), detached from this terminal
# or open the Cloud dashboard after sign-in
```

Upgrade later with `yoke update` — it reruns the official installer with
onboarding disabled, honors this machine's already-configured distribution
origin and channel, and reports the verified old and new version (or that
you're already current). The installer itself repairs the git credential
helper a reinstall wipes from site-packages, as the last step of every
successful run — so re-running the curl installer directly still resolves
the same channel version for every Yoke product package and still repairs
the helper, just without the version-change report. Neither path touches a
Yoke source checkout — that updates with git.

The first command you run after an upgrade brings the rest of the install up
to the new engine. A machine-local universe has its schema converged before
the command is served — the same step a hosted container runs on boot.
Additive foreign keys match the live `environments.id` type so a universe
still on text keys reaches the ordered history that converts them. The convergence also declares a bounded `idle_in_transaction_session_timeout` for the session; recording it as the role's database default is best-effort, so a role that cannot alter its own defaults — or a second boot racing on the same catalog row — degrades with an `application_role_default_not_persisted` diagnostic on stderr instead of refusing every read. A project
checkout whose operating layer predates the new engine is named once, with
the `yoke project install <checkout>` that refreshes it. Run that when it
appears; otherwise the checkout keeps teaching the previous release.

## Project-only install

If the project already exists in the universe and you only need the repo
operating layer:

```bash
yoke project install ~/path/to/checkout
```

That materializes skills, agents, hooks, and `.yoke/docs` from the engine's
public docs corpus.

The run finishes the job rather than leaving you a commit to push. It fetches
the branch's remote first and fast-forwards when the checkout is simply
behind, so the layer is generated against current upstream; it commits the
paths it owns; and it pushes that commit. If the remote advanced while the
run was writing, it moves onto the new revision and **regenerates** the layer
there — never a merge, which would keep whichever obsolete generated content
the older side happened to carry.

Where the branch does not accept a direct push, the same commit is pushed to
a `yoke-install/<sha>` branch and proposed as a pull request. Where the push
cannot land at all, the report says `publication_pending` and names the
commit plus the command that finishes it — and the command exits `3` rather
than reporting a clean install the remote never saw.

Two refusals are deliberate. A default branch carrying commits of your own
that the remote lacks is reported instead of pushed, because publishing the
layer is not permission to publish your work-in-progress — and a commit
merely *titled* like an install counts as yours unless its changes stay
inside what the install writes. Files it shares with you rather than owns are
on your side of that line: it merges its hook entries into your
`.claude/settings.json`, appends one line to your `.gitignore`, and writes
into the file-line policy config, so it cannot tell its content there from
yours. A commit it did not just make that touches one of those is reported —
never pushed, and never rewritten while reconciling with the remote. And a
checkout with no remote is a local-only project: publication is skipped, not
failed, as it is for `--no-commit`. Pass `--no-publish` to commit without
pushing.

An unreachable remote does **not** stop the install, which is the one place
it differs from starting other work. Creating a worktree refuses an
unverifiable remote, because new work would have no current revision to
start from; installing writes a local layer, so an offline machine still
gets the thing it asked for. The run records why it could not read the
remote and publication then reports `publication_pending` — you are never
told the remote has a layer it never received.

## Related

- [Modes](modes.md)
- [CLI and config](cli-and-config.md)
- [Projects](projects.md)
