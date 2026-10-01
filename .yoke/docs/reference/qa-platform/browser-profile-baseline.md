# Browser-authenticated host missions

A clean test-machine home golden contains no Yoke state. A Linux browser
profile can be sealed separately using `yoke test-machine golden-capture
--project P --machine NAME --component browser-profile --json` after desktop
logout and browser-daemon shutdown, before any reset. Read the command's
`--help` and the installed Machine QA Pack's
`docs/packs/machine-qa/browser-profile-baseline.md` for the complete recipe.

The capture uses existing host lease and receipt authority. It records the
private sibling snapshot as `browser_profile_baseline_path`, leaving
`golden_baseline_path` unchanged. Ordinary resets never restore the profile.
For an exploratory mission needing browser authentication, install the
candidate Yoke and stop its browser daemon, then run
`yoke qa browser setup --project P --profile-baseline /absolute/sealed/snapshot --json`
through the mission's lease-routed host-command surface. Read its `--help`:
explicit provisioning restores before daemon startup; default setup and
`--dry-run` never restore a profile. Use the canonical project and recorded path.

Terminal or machine-state host-control cases instead declare the closed setup
operation `machine.browser-profile-restore`, with exactly `project` (the
canonical slug) and `baseline_path` (the recorded absolute snapshot path).
Install the candidate Yoke before that fixture and stop its browser daemon.

Both routes verify owner, home, project and archive digest, refuse unsafe
entries or an existing profile, and run through the installed interpreter.
The snapshot stays on the host; neither its contents nor credentials belong
in QA artifacts or control-plane records. After restoration, use the actual
candidate daemon to open the application and prove its signed-in UI. A cookie
count or a sealed-capture receipt does not prove browser authentication.
