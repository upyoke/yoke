# Copy links and codes during onboarding

Review names the setup commit's remote and branch before Apply. With stored
GitHub authorization, Apply commits Yoke setup and attempts to push it; branch
protection can require a review proposal instead. Without that authorization,
a GitHub remote leaves the setup committed locally and Review shows the exact
command to push later. A checkout without a remote stays local-only. Skipping
GitHub shows no GitHub App binding in Review; it disables GitHub automation,
and does not change the existing setup-publication behavior. Cancel at Review
to leave Apply's writes undone.

On a wizard screen containing a link or one-time code, press **Ctrl-Y** to
copy the exact value. A screen with both offers them in sequence; the footer
names what the next press will take. **Ctrl-O** opens the screen's link in your
browser on a local desktop.

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
