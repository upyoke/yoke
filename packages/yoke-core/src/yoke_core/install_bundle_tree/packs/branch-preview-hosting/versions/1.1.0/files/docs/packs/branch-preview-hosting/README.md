# Branch Preview Hosting Pack

Adds the host-side pieces shared by branch preview systems: deterministic
subdomain-to-port routing and time-to-live cleanup for preview directories,
Compose projects, images, and volumes. It does not prescribe how application
code is built or deployed.

## Project-specific work

- Reserve a preview-only namespace, wildcard domain, and non-overlapping port
  range. Production resources must not use the preview namespace.
- Provision wildcard DNS and TLS for the preview domain.
- Install the nginx site and njs module on the chosen host and verify routing.
- Schedule the Python cleanup program with cron, systemd, or the host's
  scheduler.
- Make the project deployer use the same slug and SHA-256 port calculation.
- Decide what preview data can be deleted and test expiration and teardown on
  the actual host before relying on unattended cleanup.
