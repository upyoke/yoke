# The credentialed git environment (internal)

Git commands against GitHub prefer the machine's stored authorization. When
none is stored, they may try the user's own git credentials non-interactively.
There is one place that decides this —
`yoke_cli.config.credentialed_git` — and every engine remote operation goes
through it: merge pushes and fetches, the branch publish that ends a merge,
the QA lane push that CI checks out, the doctor's branch and stale-remote
reads, the deploy pipeline's tag and SHA resolution, the advance lane publish,
and the session-start main-checkout fast-forward.

## Why it exists

A shared credentialed environment gives every remote Git operation the same authorization and bounded, non-interactive failure behavior.



## What it decides, per command

**Is this command going to contact a remote?** `clone`, `fetch`, `ls-remote`,
`pull`, `push`, and `remote update`/`remote prune` do. Everything else is a
local read and gets a prompt-free environment and nothing more. The subcommand
is found behind git's global options, because engine call sites routinely lead
with `-C <path>` and a push behind `-C` must not read as local.

**Which URL will it contact?** A named remote is resolved against the checkout,
a URL operand is taken as written, and an omitted operand means `origin`.

**Is that URL the machine's configured GitHub origin?** The answer is
recorded, not re-derived: the decision travels with the environment, so a
failed command's attribution line reports what the run actually did rather
than what a later re-derivation would guess.

- *No* — another host, a file remote, no remote at all: the command runs
  non-interactively with no credential. A missing GitHub credential is not
  what is wrong with a GitLab remote.
- *Yes, with stored authorization* — the command runs in the hermetic environment
  the clone path uses:
  the stored token as a URL-scoped `http.extraheader`, injected through
  `GIT_CONFIG_*` so it reaches neither argv, `.git/config`, nor the stored
  remote; ambient credential helpers, system and global config, and `~/.netrc`
  reset out of the way. Broken or revoked stored authorization refuses and never
  consults ambient credentials.
- *Yes, without stored authorization* — Git keeps the user's configuration and
  may use an existing helper or SSH key. Prompts remain disabled, including
  `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=Never`, and SSH `BatchMode=yes`.
  `run` bounds the child and its helpers by the existing network deadline.

## SSH origins

A checkout cloned over SSH has no HTTPS remote to attach a header to, so the
configured origin's SSH forms are rewritten onto its HTTPS form when using
stored authorization. The optional own-credential path preserves SSH:


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

## One token, shared

The store keeps the access token beside the refresh token that minted it and
hands the stored one back until it is within
`GITHUB_APP_USER_ACCESS_TOKEN_REFRESH_MARGIN_SECONDS` of expiring. That margin
is what lets a command starting just inside the window still finish with a
token the remote accepts.

Without it, every remote git command performed a live refresh grant. Two
commands running at once each minted a token and revoked the other's, so the
same push failed, succeeded, and failed again within minutes with no
credential change in between — and a single gate run rotated twice, because a
lane publish fetches and then pushes. Caching turns the common read into a
lookup, so concurrent commands carry the same token and the refresh exchange
happens about once per token lifetime.

Storing the access token costs no reach. The document already holds the
refresh token, which mints access tokens for months, under the same owner-only
permissions that an access token expiring in hours now lives under.

The cache lives under one nested `cached_access` key rather than beside the
refresh fields. A build shipped before the cache existed refuses a document
carrying `access_token`, `expires_at`, `scope`, or `token_type` at the top
level, and the recovery it names is a reconnect — the one action that revokes
the token every other live process holds. Since a machine runs many Yoke
processes that upgrade at different times, nesting is what keeps an older build
reading the document: it sees a key it does not know, ignores it, and refreshes
exactly as before. That is one storage shape and one reader, not a
compatibility layer.

`yoke github status` reports that stored token as its own binding — when it
expires, and whether the next command will renew it. It reads the document
locally and rotates nothing, so a status check cannot break a push in flight.
The binding is informational and never gates `ready`: a machine with no token
cached yet simply mints one on its next command.

Which Yoke connection the machine profile is proven against is pinned the
same way a merge child pins it. An owner-only `<env>-db-admin` connection is
a door into one universe's database, not a plane that can answer for the
saved profile, so the https sibling it administers answers instead. Without
that pinning a merge refuses at the moment it tries to publish — the engine
has already switched to the admin connection by then.

## When no credential resolves

When no authorization is stored, a failed optional Git attempt says that no
Yoke GitHub authorization is stored, that your own git credentials did not work,
and names `yoke github status` and `yoke github connect` as recovery. It returns
a failed command, including when the deadline expires; it never opens a prompt.
Onboarding retains its setup commit and named pending-publication outcome.
Disconnected standalone completion retains a successful local merge and the
named “not pushed because GitHub is not connected” outcome. Neither flow needs
ambient credentials to complete. Successful publication names which credential
path was used; a successful own-credential push does not enable App checks or
GitHub sync.

With stored authorization, a read that loses the machine operation lock or
cannot reach GitHub is replayed within the shared authorization retry budget
(`yoke_contracts.github_auth_transience`). Only a failure that survives the
budget refuses, naming the recovery that matches what failed.

A retry-shaped failure gets the opposite advice, deliberately: the stored
authorization still stands, so the recovery is to retry. **No failure path
here recommends reconnecting to clear contention.** `yoke github connect
--replace` rotates the authorization, which revokes the access token every
other running command is carrying — on a busy machine that turns one blocked
command into a machine-wide outage.

The refusal comes back as a failed command — git's own fatal exit code, with
the message on stderr — so every existing return-code branch surfaces the
diagnosis instead of an empty failure, and no caller has to learn a second
shape. A timeout is named the same way: the command cannot be waiting on a
prompt, so the message says the remote is unreachable, slow, or refusing this
machine's credential.

## Relationship to the repo-local credential helper

`yoke setup` still installs a URL-scoped credential helper into checkouts it
onboards (see [github-connections.md](github-connections.md)), and
`yoke github disconnect` still removes it. That helper serves git commands run
by *people* in their own shells. Stored Yoke authorization ignores ambient
helpers. Without stored authorization, the optional path may use the user's
existing helper, without installing a new credential or substituting it for
GitHub API authorization.

## Adding a remote operation

Call `credentialed_git.run(args, cwd=..., timeout=...)` with git's arguments
(no leading `"git"`). When a call site needs its own execution — a runner that
reaps process groups, an injected command runner — take the environment
instead with `credentialed_git.git_environment(args, cwd=...)` and run the
command yourself, retaining that runner's network deadline and process cleanup.
Do not build a git environment by hand: credential selection and prompt
suppression belong to this shared runner.
