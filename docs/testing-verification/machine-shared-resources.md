# The operator's machine is not a fixture

Which shared workstation resources a test may reach, and how the two
structural guards work. Companion to
[`docs/testing-verification.md`](../testing-verification.md).

A test runs on a real workstation, and a few of its resources are shared with
everything else on that machine. Four are guarded structurally, because
per-test discipline had already failed for each.

**The home folder.** The repo-wide pytest plugin
`runtime/real_home_isolation.py` sets `HOME` to an empty per-test folder and
clears `CODEX_HOME` and `XDG_CONFIG_HOME`, so `Path.home()`, `expanduser`, a
harness config path imported by name into another module, and every
subprocess resolve inside the test's `tmp_path`. A test that needs a file a
real home would hold writes it into that folder itself; never point a test
back at the real home. A path captured before the test started still names
the real home, so a Python audit hook watches the writes the test's own
process makes and fails the test with `real_home_written`, naming each path.
The checkout, its environment and the interpreter are exempt. Fix the
reported path by resolving it at call time or pointing the fixture inside
`tmp_path`. Subprocesses are covered by the inherited `HOME`, not the hook.
A test that clears `os.environ` (`mock.patch.dict(..., clear=True)`) keeps
`HOME` and `YOKE_SCRATCH_ROOT` in the cleared mapping; without `HOME`,
`Path.home()` falls back to the account's real home. A test asserting that a
home path is refused uses a home outside the OS temp roots (for example
`/__yoke_test_home__`), because the per-test home is itself a free path.

**The running environment.** The source runner starts pytest with
`UV_PROJECT_ENVIRONMENT` naming the checkout's `.venv`. A test that inherits
it and syncs a fixture project installs that fixture's lock into the running
environment and removes every package the suite needs. Under GitHub Actions
the job's command files (`GITHUB_STEP_SUMMARY`, `GITHUB_OUTPUT`, `GITHUB_ENV`,
`GITHUB_PATH`) arrive the same way. `runtime/running_environment_isolation.py`
clears all of them for every test; a test that exercises one sets its own. Product
code that launches uv for another project (lane provisioning, the
`yoke watch` re-exec) runs it under
`yoke_contracts.uv_project.project_own_environment`, which drops
`UV_PROJECT_ENVIRONMENT` and `VIRTUAL_ENV`.

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

The former shared relay (`com.upyoke.relay`) is never installable,
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
