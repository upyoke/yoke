# The credentialed git environment

Every git command Yoke runs that reaches a remote carries the machine's stored
GitHub credential. There is one place that decides this —
`yoke_cli.config.credentialed_git` — and every engine remote operation goes
through it: merge pushes and fetches, the branch publish that ends a merge,
the QA lane push that CI checks out, the doctor's branch and stale-remote
reads, the deploy pipeline's tag and SHA resolution, the advance lane publish,
and the session-start main-checkout fast-forward.

## Why it exists

Onboarding already cloned your project with the stored credential. Everything
after onboarding used to run on whatever credentials the surrounding shell
happened to carry. On a machine that onboarded through the wizard, a repo-local
credential helper covered that up. A fresh user — no SSH key, no `gh` login —
hit it directly: the first push stalled until its timeout and reported nothing
anyone could act on. The doctor's fetch had a 15-second ceiling, which read as
a hang rather than as the authentication failure it was.

The fix is one conversion rather than a credential added per call site, because
a call site that is easy to miss is exactly the one a fresh user finds.

## What it decides, per command

**Is this command going to contact a remote?** `clone`, `fetch`, `ls-remote`,
`pull`, `push`, and `remote update`/`remote prune` do. Everything else is a
local read and gets a prompt-free environment and nothing more. The subcommand
is found behind git's global options, because engine call sites routinely lead
with `-C <path>` and a push behind `-C` must not read as local.

**Which URL will it contact?** A named remote is resolved against the checkout,
a URL operand is taken as written, and an omitted operand means `origin`.

**Is that URL the machine's configured GitHub origin?**

- *No* — another host, a file remote, no remote at all: the command runs
  non-interactively with no credential. A missing GitHub credential is not
  what is wrong with a GitLab remote.
- *Yes* — the command runs in the hermetic environment the clone path uses:
  the stored token as a URL-scoped `http.extraheader`, injected through
  `GIT_CONFIG_*` so it reaches neither argv, `.git/config`, nor the stored
  remote; ambient credential helpers, system and global config, and `~/.netrc`
  reset out of the way.

## SSH origins

A checkout cloned over SSH has no HTTPS remote to attach a header to, so the
configured origin's SSH forms are rewritten onto its HTTPS form:

```
url.https://github.com/.insteadOf = git@github.com:
url.https://github.com/.insteadOf = ssh://git@github.com/
```

Git contacts HTTPS, the URL-scoped header applies, and the stored token serves
the checkout — no key required. This is what makes `https` and `ssh` origins
behave identically from the engine's point of view.

## Which credential

The token comes from the same credential store the installed git credential
helper reads, keyed by the request's protocol and host — not from the
API-side token reader.

That distinction is load-bearing. Refreshing a GitHub App user authorization
rotates it and revokes the previous access token, so a git command that
minted its own token through the refreshing path could have it revoked
mid-flight by any other Yoke process on the machine that refreshed in
between. The symptom is a push that fails with a credential prompt on a busy
machine and succeeds on a quiet one.

Which Yoke connection the machine profile is proven against is pinned the
same way a merge child pins it. An owner-only `<env>-db-admin` connection is
a door into one universe's database, not a plane that can answer for the
saved profile, so the https sibling it administers answers instead. Without
that pinning a merge refuses at the moment it tries to publish — the engine
has already switched to the admin connection by then.

## When no credential resolves

The command is refused, by name, with its recovery:

```
cannot authenticate a git operation against https://github.com/acme/widgets.git:
machine GitHub App authorization is not configured. Yoke reaches GitHub with
this machine's GitHub App user authorization and nothing else stands in for it.
Run `yoke github status` to see what is stored, then `yoke github connect` to
authorize this machine.
```

The refusal comes back as a failed command — git's own fatal exit code, with
the message on stderr — so every existing return-code branch surfaces the
diagnosis instead of an empty failure, and no caller has to learn a second
shape. A timeout is named the same way: the command cannot be waiting on a
prompt, so the message says the remote is unreachable, slow, or refusing this
machine's credential.

## Relationship to the repo-local credential helper

`yoke onboard` still installs a URL-scoped credential helper into checkouts it
onboards (see [github-connections.md](github-connections.md)), and
`yoke github disconnect` still removes it. That helper serves git commands run
by *people* in their own shells. It is no longer what carries Yoke's own
remote operations, so a checkout without it — an SSH origin, a manual clone —
now behaves the same as one with it.

## Adding a remote operation

Call `credentialed_git.run(args, cwd=..., timeout=...)` with git's arguments
(no leading `"git"`). When a call site needs its own execution — a runner that
reaps process groups, an injected command runner — take the environment
instead with `credentialed_git.git_environment(args, cwd=...)` and run the
command yourself. Do not build a git environment by hand: an environment that
is only prompt-proof is exactly the state this replaced.
