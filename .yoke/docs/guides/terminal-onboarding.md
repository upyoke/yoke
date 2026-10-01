# Copy links and codes during onboarding

On a wizard screen containing a link or one-time code, press **Ctrl-Y** to
copy the exact value. A screen with both offers them in sequence; the footer
names what the next press will take. **Ctrl-O** opens the screen's link in your
browser on a local desktop.

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
