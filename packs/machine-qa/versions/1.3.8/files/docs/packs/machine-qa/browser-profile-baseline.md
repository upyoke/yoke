# Browser-profile baseline

The saved browser profile is part of a test machine's saved baseline. Keep it
separate from the clean home, capture it after every browser writer exits, and
restore it after candidate installation. Desktop and profile setup live in the
complete per-OS procedures:

- [Linux, step 5](linux-host-provisioning.md#5-optional-browser-authorization-and-separate-saved-profile)
- [macOS, step 11](macos-host-provisioning.md#11-separate-signed-in-browser-profile)
- [Windows/WSL2, step 6](windows-host-provisioning.md#separate-signed-in-browser-profile-inside-wsl)

Setup gives the user space to perform whatever sign-ins their project needs,
then saves the profile. Agents do every step that does not need the user;
personal credentials are entered by the user. Profile data stays on the host.
