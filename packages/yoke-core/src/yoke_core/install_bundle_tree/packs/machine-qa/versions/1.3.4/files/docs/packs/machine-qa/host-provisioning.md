# Provisioning persistent Test Machines

Every Test Machine is persistent and reached through SSH. Declare its `os`
(`macos`, `linux` or `windows`) in `test-machine:<resource-name>` settings; no lifecycle
field is needed. Choose the instructions for that OS:

- [macOS: Terminal.app, privacy grants and signed-in GUI state](macos-host-provisioning.md).
- [Linux: Ubuntu 24.04, non-root SSH, tmux, harness sign-in and tunnel-only desktop for screenshots](linux-host-provisioning.md).
- [Windows: OpenSSH into WSL2, Linux home restore and tmux](windows-host-provisioning.md).

Each capability owns its settings, verification, receipts and serial QA lease.
The installing project owns host addresses, users, goldens and secrets. Store
`ssh_private_key` through `yoke projects capability secret set --project P
--cap-type test-machine --key ssh_private_key --value-file KEY_FILE` on every
machine that executes QA. All test hosts in that project authorize that shared
key; its private bytes never belong in settings, plans, messages or artifacts.

A registered capacity machine is a separate agent-launch identity. A test host
may also register capacity, but neither registration implies the other's
readiness or grants. Use a separate user/home for capacity; do not run ordinary
work in a test home while a reset or QA lease holds it. Machine detail links a
matching hostname to its Test Machine capability without merging identities.

Provision infrastructure through the project's declared IaC surface before
running these steps. Record any operator-authorized infrastructure exception.
After provision, capture a golden, verify both registered baselines, then reset
to the baseline needed by the next case. Verification is destructive and leaves
the installed `shell-preconfigured` state; it does not leave a fresh host.

OS-aware clients require the next-release serving contract and converged
settings. An older response or settings document without `os` refuses with
`test_machine_os_serving_floor_required`. Upgrade the serving build and run the
governed convergence before replacing settings or running operations.
