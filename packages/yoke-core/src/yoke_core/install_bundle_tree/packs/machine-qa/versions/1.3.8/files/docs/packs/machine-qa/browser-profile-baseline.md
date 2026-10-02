# Browser-profile baseline

One procedure captures a separate stopped profile, restores it after candidate
installation, and completes the case's own declared browser flow. Preparation
and desktop details live only in the per-OS procedures:

- [Linux, step 5](linux-host-provisioning.md#5-optional-browser-authorization-and-separate-saved-profile)
- [macOS, step 11](macos-host-provisioning.md#11-separate-signed-in-browser-profile)
- [Windows/WSL2, step 6](windows-host-provisioning.md#separate-signed-in-browser-profile-inside-wsl)

The project owns the required sign-ins and `.yoke/browser-flows.json` declaration.
Actual signed-in application UI is the proof at capture and after restoration.
A valid saved sign-in lets both typed recipe gates and exploratory walkers
complete their own approval; only a missing/expired personal sign-in needs a
human sign-in handoff. Read `yoke qa mission browser-flow --help` for the
lease-bound live-transcript contract. No profile data is exported.
