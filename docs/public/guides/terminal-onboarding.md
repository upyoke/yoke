# Copy links and codes during onboarding

Run `yoke setup` for machine setup. Bare `yoke onboard` points there and lists
the project commands, including `yoke onboard project`. Selection rows fit the
terminal's available width, including 80 columns and narrower; a long label
or description is shortened, and the selected description appears below.

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

Review names the setup commit's remote and branch before Apply. With stored
GitHub authorization, Apply commits Yoke setup and attempts to push it; branch
protection can require a review proposal instead. Without that authorization,
Review names an optional push with your own git credentials and the exact
command to push later. If no helper or SSH key works, Apply completes with the
setup committed locally and not pushed; it never asks for credentials. A checkout without a remote stays local-only. Skipping
GitHub shows no GitHub App binding in Review; it disables GitHub automation,
and does not change the existing setup-publication behavior. Cancel at Review
to leave Apply's writes undone.

On a wizard screen containing a link or one-time code, press **Ctrl-Y** to
copy the exact value. A screen with both offers them in sequence; the footer
names what the next press will take. **Ctrl-O** opens the screen's link in your
browser on a local desktop.

Setup first checks foreground terminal ownership on POSIX systems (macOS and
Linux). A background launch refuses with `setup_terminal_not_foreground` before
preparation: use `fg` or run `yoke setup` from the foreground shell without `&`.
If ownership cannot be checked, `setup_terminal_ownership_unavailable` asks for
a foreground terminal or `--non-interactive` with the required flags. Windows
uses Textual's native console lifecycle; it has no POSIX foreground job group.
Intentional noninteractive setup does not use these terminal checks.

If another job takes the terminal during the wizard, setup restores terminal
input and mouse modes and exits with `setup_terminal_ownership_lost`. Return to
the foreground shell and run `yoke setup` again. Completed setup changes remain;
the diagnostic does not imply rollback. If restoration fails, the diagnostic
names the failure and asks you to run `stty sane` before retrying. Suspension
by `SIGTSTP` and foreground resumption by `SIGCONT` preserve your wizard state,
as does the copy view below.

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
