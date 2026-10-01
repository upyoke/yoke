# Copy links and codes during onboarding

On a wizard screen containing a link or one-time code, press **Ctrl-Y** to
copy the exact value. A screen with both offers them in sequence; the footer
names what the next press will take. **Ctrl-O** opens the screen's link in your
browser on a local desktop.

The Account step opens the approval link with your installed default browser.
On a Linux desktop without one, it uses Yoke's Chromium runtime, installing it
through the same setup and cache browser QA uses. The wizard shows a progress
screen while preparing the browser; the approval link and one-time code remain
visible, with the copy keys available. Later browser QA reuses that download.
On a machine without a graphical display, onboarding downloads nothing and
says “No browser available here. Open this link on any device”. A failed
installation or open shows the same recovery with the failure reason; it only
says “The browser was opened for you” after a successful open.

Over SSH, or on Linux without a local display, the footer says **^y show … to
copy**. Ctrl-Y temporarily suspends the wizard and shows the exact value in
normal terminal scrollback, followed by “Select and copy, then press Enter to
return”. Select the value and use your terminal's Copy command (Cmd-C in
stock macOS Terminal.app), then press Enter. The wizard returns to the same
screen with your entered values and focus preserved. Ctrl-O shows the link
the same way on a remote session.

The same selectable view appears if local clipboard commands cannot copy.
Terminals supporting OSC 52 may also copy automatically; manual selection
works without changing terminal settings. Nothing is printed above the
wizard until you request it with a key.
