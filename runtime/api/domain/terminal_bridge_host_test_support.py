"""A scripted macOS host that answers everything the Terminal bridge asks.

Shared by the bridge's verification pass and its diagnosis, because both drive
the same host through the same probes and a second double would let the two
drift apart in exactly the place operators read.
"""

from __future__ import annotations

from runtime.api.domain.scripted_mac_host_test_support import ScriptedMacHost


#: The identity the bridge stamps into its ready banner and typed text when a
#: test pins uuid4.
BRIDGE_IDENTITY = "b" * 12


class FakeMac(ScriptedMacHost):
    """A host that also answers the transcript, keystroke, and capture probes."""

    def __init__(
        self,
        *,
        captures: tuple[str, ...] = ("cG5nLW9uZQ==", "cG5nLXR3bw=="),
        console_user: str = "yoke-test",
        locked: bool = False,
        input_ok: bool = True,
        placement=None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.captures = list(captures)
        self.console_user = console_user
        self.locked = locked
        self.input_ok = input_ok
        self._placement = placement
        self._transcript_reads = 0

    def place(self, requested, attempt):
        if self._placement is None:
            return requested
        return self._placement(requested, attempt)

    def reply(self, command: str) -> str | None:
        if "return contents of selected tab" in command:
            self._transcript_reads += 1
            if self._transcript_reads == 1 or not self.input_ok:
                return "terminal-app-ready\n"
            return f"received-{BRIDGE_IDENTITY}\n"
        if 'tell application "System Events"' in command:
            return "true" if self.input_ok else "false"
        if command.startswith("/bin/test -s "):
            return self.captures.pop(0) if self.captures else ""
        if command == "/usr/bin/stat -f%Su /dev/console":
            return self.console_user
        if command.startswith("/usr/sbin/ioreg"):
            return (
                '    | |   "CGSSessionScreenIsLocked" = Yes'
                if self.locked
                else '    | |   "kCGSSessionOnConsoleKey" = Yes'
            )
        return None


__all__ = ["BRIDGE_IDENTITY", "FakeMac"]
