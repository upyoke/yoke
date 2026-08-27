# The operator's machine is not a fixture

Which shared workstation resources a test may reach, and how the two
structural guards work. Companion to
[`docs/testing-verification.md`](../testing-verification.md).

A test runs on a real workstation, and a few of its resources are shared with
everything else on that machine. Two are guarded structurally, because
per-test discipline had already failed for both.

**Browsers.** Every test path that could open one is required to inject a
fake opener; the repo-wide conftest fails the test rather than letting the
platform launcher run, and points `BROWSER` at a harmless command so a child
process cannot fall through to the operator's default browser either.

**launchd.** Every launchctl invocation and every launch-agent plist location
resolves through `yoke_core.tools.launchctl_boundary`. An isolated
`YOKE_MACHINE_HOME` keeps LaunchAgents inside that machine-home, so a
pytest sandbox can never write the operator's login domain. Under a test
process the boundary also records launchctl commands into a per-test
sandbox instead of executing them, and redirects any plist that would
still bind to the operator's real `~/Library/LaunchAgents`. A test that
passes its own home is untouched. The sandbox travels as an environment
variable (`YOKE_LAUNCHD_TEST_SANDBOX`, exported by the conftest) because
the leak this replaced arrived through a spawned child, which no
monkeypatch can reach. A test with no sandbox is refused by name.

The machine's canonical relay (`com.upyoke.relay`) is never installable,
loadable, or bootable-out from a test — not even with the integration opt-in.
A test that genuinely must load a real agent is marked
`@pytest.mark.launchd_integration` and requests the `real_launchd_agent`
fixture, which registers each label for unconditional bootout in teardown.

Assert the plist document where you can: `relay_plist_document` and
`relay_launchd_paths` are pure, and every install/status/uninstall entry
point takes a `runner`, so a fake records the exact launchctl argv without
reaching the boundary at all.

Leaks that predate the guard are found by `HC-session-relay-orphans` and
reclaimed with `yoke doctor run --quick --fix`, which unloads and deletes
suffixed `com.upyoke.relay.*.plist` strays and never touches
`com.upyoke.relay`. macOS Background Task Management rows for deleted
agents may linger in System Settings → Login Items until reboot, or
until an operator runs `sudo sfltool resetbtm` — never from a test or
agent. The reasoning is in
[`../archive/decisions/launchd-test-boundary.md`](../archive/decisions/launchd-test-boundary.md).
