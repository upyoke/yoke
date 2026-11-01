# Terminal setup (optional)

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Installation reference](index.md) > Terminal setup (optional)
<!-- /yoke:breadcrumbs -->

Use this path if you prefer to install and configure Yoke yourself in a terminal.
For the recommended agent-led path, follow [Get started](index.md).

```bash
curl -fsSL https://upyoke.com/install | sh
```

In an interactive terminal, the installer opens setup. If it does not, run
`yoke setup --tui`. Follow the questions, review the proposed changes and Apply.
See [Install](install.md#onboard-wizard) for the wizard's steps and prerequisites.
After setup, open your coding agent in the project folder and follow the
[next steps](agent-setup.md#after-setup).

## Setup details and recovery

Read saved setup in the project's checkout:

```text
yoke onboard checklist get --project P --json
```

The read resolves that project's run in the connected universe and checks this
machine's prerequisites. Saved choices and evidence survive a new session or
machine; current settings determine the observed state. `configured`, `deferred`,
`not-needed`, `unknown` and `blocked` remain distinct. Optional unexamined
capabilities stay unknown. `run.next_action` names the next required recipe and
its deeper home; `run.setup_readiness` describes current prerequisites.
Human checklist replies lead with the same Next recipe that install, refresh,
register and checklist init show. Orientation includes concise setup facts once
per session, suppresses settled setup after first-work activation, and uses
`Setup: run yoke onboard checklist get` if space is tight. Failed reads name the
reason and recovery; permission-denied setup is omitted. An older server without
`next_action` supplies no guessed Next line.

Onboard saves the confirmed profile in the existing run. Resume reuses it;
changed settings require confirming the changed proposal. The checklist Markdown
is a view. A serving release without checklist schema 2 refuses before new
scoped writes and names the control-plane operator recovery.

Run `yoke setup` for machine setup. Bare `yoke onboard` points there and lists
the project commands, including `yoke onboard project`. Selection rows fit the
terminal's available width, including 80 columns and narrower; a long label
or description is shortened, and the selected description appears below.

Press **Esc**, **Ctrl-[**, or a **Back** row to return to exactly the previous
interactive screen. Back stays on the first screen and waits while Apply is
writing. Checks without a cancellation route also wait until they finish.
Going forward again reuses what this setup already did: the repository it
cloned, the connection it approved or started, a restored backup, and an
opened git installer are never offered again as someone else's.

`yoke uninstall` also handles unfinished setup: absent GitHub authorization
or an absent active connection skips disconnect with a reason, so an otherwise
clean machine can finish removal.

Choosing **Don't set up a project now · just the machine** still connects
your account. The finish screen lists your accessible projects with their
work-item prefixes, plus commands to file and browse work from any folder
and the hosted dashboard link for the connection (or `yoke ui up` for a
team server's workbench). Filing a Dash first requires
reading the project's Before creation execution instructions; the screen shows that command
and the required `--execution-instructions-considered` flag. If your account
has no projects, it says so and omits the filing and browsing commands.
To prepare a project's code on this machine later, run `yoke setup`.

Setup adds a progress map and three random headers (ASCII, Emoji and Mixed)
without a design screen. Existing project art stays intact. After setup, run
`yoke board art variant create --help` to preview and add another header, or
edit `.yoke/board-art` to change the map or saved art; run `yoke board rebuild`
to see the result.

Setup wires the project to Yoke and installs its operating guidance. It does
not install an application scaffold. The installed `yoke` skill
(`$yoke onboard` in Codex; `/yoke onboard` in Claude Code or Cursor)
surveys existing work, plans dashes and configures only their needs, including
any chosen application Pack, then hands off to `/yoke steer`. The webapp scaffold contributes an application-docs
reference to canonical `AGENTS.md` and a marked `.gitignore` block; project
guidance, the Yoke managed block and custom ignore rules remain intact.
Preview with `yoke packs get webapp-scaffold /path/to/project --project P`,
then apply that reviewed plan with `--apply`. An installed Pack uses
`yoke packs update` for repeats and newer versions. See the installed
`docs/packs/webapp-scaffold/README.md` for boundaries and conflict recovery.

When cloning or adopting an independently cloned folder, choose where Yoke
publishes: **Read-only source** keeps fetching available and disables Yoke
publication through the checkout's `publication_read_only` project setting in
the machine config. Git remote URLs and native Git behavior stay unchanged; **Use source for pushes** names
the source as the destination and states whether write access was confirmed or
remains unverified; **Fork** and **Duplicate** select an owned destination through
the available GitHub capabilities. A configured project's existing destination
stays selected. Review names the destination and branch before Apply.
Read-only setup stays `publication-pending`; lane preparation and local merges
remain available, including when the checkout has an `origin` remote. Yoke pushes
refuse with `publication_destination_read_only`. To publish, choose/configure an
owned writable destination using the refusal's recovery, then retry publication.
Source fetching remains usable. Existing
legacy disabled push URLs migrate once into the Yoke setting and are removed;
other fetch and push URLs remain intact.

Review names the setup commit's remote and branch before Apply. With stored
GitHub authorization, Apply commits Yoke setup and attempts to push it; an
empty remote takes that commit as its first push, and branch
protection can require a review proposal instead. Without that authorization,
Review names an optional push with your own git credentials and the exact
command to push later. If no helper or SSH key works, Apply completes with the
setup committed locally and not pushed; it never asks for credentials. A checkout without a remote stays local-only. Skipping
GitHub shows no GitHub App binding in Review; it disables GitHub automation,
and does not disable Git pushes to a selected writable destination. Cancel at Review
to leave Apply's writes undone.

A local-only project can finish its first item. With a merge-only flow,
merge close-out records the result and verification, runs the remaining
lifecycle gates and reaches `done` without a GitHub repository or release run.
See [flow completion](../deployments/model/flows.md).

The run report records what publication did on its own step: complete when
the commit reached the remote, skipped with its reason, or incomplete with the
recovery command when the commit stayed local. Setup's board art is committed
after that commit and goes where it went: pushed to the same branch, or added
to the review pull request's branch. A refused art push turns the step
incomplete with its recovery; when setup's commit stayed local, its recovery
also names the art commit. The report's `final_status` is
`done` only when setup was published (or had nothing to publish);
otherwise it reads `publication-pending` or `publication-skipped`.

During Apply, each reviewed operation shows its status: ○ pending, ◐ running,
✔ complete, ⊘ skipped or ✗ failed; an incomplete operation, such as a setup
commit left unpushed, also shows ✗. Plain terminals use `o`, `~`, `+`, `-` and
`x`. Overall and group counts summarize completion; the list follows the running
operation and supports PageUp/PageDown. Relay steps name the actual plist or
user-service file for the selected connection, including its instance suffix.

On a wizard screen containing a link or one-time code, press **Ctrl-Y** to
copy the exact value. A screen with both offers them in sequence; the footer
names what the next press will take. **Ctrl-O** opens the screen's link in your
browser on a local desktop.

Setup first checks foreground terminal ownership on POSIX systems (macOS and
Linux). A background launch refuses with `setup_terminal_not_foreground` before
preparation: use `fg` or run `yoke setup` from the foreground shell without `&`.
If ownership cannot be checked, `setup_terminal_ownership_unavailable` asks for
a foreground terminal, `yoke setup --agent` ([Agent setup](agent-setup.md)) or
`--non-interactive` with the required flags. Windows
uses Textual's native console lifecycle; it has no POSIX foreground job group.
Intentional noninteractive setup does not use these terminal checks.

The wizard runs its own helper processes — login-shell PATH probes, browser
and Node checks, package installs — with no terminal: they read nothing from
it and cannot become its foreground job. Interactive sudo cannot ask for a
password while the wizard is open; that step refuses with
`setup_wizard_sudo_refused`. Run `yoke setup` again: its preparation step asks
for the password before the wizard opens.

If another job takes the terminal during the wizard, setup restores terminal
input and mouse modes and exits with `setup_terminal_ownership_lost`. The
message names what setup observed: the job-control signal (`SIGTTIN` or
`SIGTTOU`), the terminal's foreground process group with its command when that
process still runs, and the error number when the terminal check failed.
Setup prints that notice as soon as it restores the screen; work already
running, such as Apply, finishes before setup exits, so keep the terminal open
until it does. Return to the foreground shell and run `yoke setup` again.
Completed setup
changes remain; the diagnostic does not imply rollback. If restoration fails,
the diagnostic names the failure and asks you to run `stty sane` before
retrying. Suspension by `SIGTSTP` and foreground resumption by `SIGCONT`
preserve your wizard state, as does the copy view below.

Before opening the wizard, onboarding prepares its scratch and cache directories.
On Linux it also runs the existing Python venv and browser runtime setup,
including Linux library checks, regardless of whether a display is available.
These deterministic steps need no choice and are absent from Review's consent
plan. A preparation failure reports its reason and still opens the wizard;
Apply verifies and repairs the same setup. GitHub, harness permission settings,
tokens, machine registration, and the relay remain after your choices. The relay
unit depends on the connection you selected.

The Account step opens the approval link with your installed default browser.
On a Linux desktop without one, it uses Yoke's Chromium runtime, installing it
through the same setup and cache browser QA uses. The wizard shows a progress
screen while preparing the browser; the approval link and one-time code remain
visible, with the copy keys available. Later browser QA reuses that download.
If the bundled-browser download fails, setup checks installed Chromium/Chrome
browsers with a sandboxed test-page launch. Only a successful executable is
saved in machine config at `settings.browser_executable_path`. Setup, browser
QA and browser authorization use that same selection; browser status checks
that the selected executable can still open a sandboxed test page. No browser is copied
into Playwright's cache. Later setup prefers an available bundled browser and
clears the system selection after verifying its dependencies. If an HTML block
page or corrupt ZIP replaces the download and no installed browser works, allow
`cdn.playwright.dev`, `playwright.download.prss.microsoft.com`, and
`playwright.azureedge.net`, then retry `yoke qa browser setup`.
On a machine without a graphical display, opening the link attempts nothing and
says “No browser available here. Open this link on any device”. A failed
installation or open shows the same recovery with the failure reason; it only
says “The browser was opened for you” after a successful open.

Over SSH, or on Linux without a local display, the footer says **^y show … to
copy**. Ctrl-Y temporarily suspends the wizard and shows the exact value in
normal terminal scrollback. If selection is supported, select the value and
use your terminal's Copy command (Cmd-C in stock macOS Terminal.app).
Otherwise, type the code on the other device. Press Enter to return to the same
screen with your entered values and focus preserved. Ctrl-O shows the link
the same way on a remote session.

The same selectable view appears if local clipboard commands cannot copy.
Terminals supporting OSC 52 may also copy automatically; selection depends
on the terminal and remote desktop client. Nothing is printed above the
wizard until you request it with a key.

Checklist reads fill missing legacy rows in memory with the same defaults used
when saving a run. They preserve saved choices and the run branch, and write no
rows; the next normal update saves missing rows. These defaults never prove
current setup readiness. Recorded delivery still marks a run as historical
completion. If saved evidence cannot be read, Overview returns the typed error
only in its onboarding module and keeps the other modules available. Follow the
reported recovery; initializing the checklist can change its branch.
