# VPS Hosting Pack

Provides a reusable AWS VPS component plus host provisioning, TLS, and firewall
helpers.

## Project-specific work

- Choose the AMI, instance type, volume, key, instance profile, and network.
- Reconcile users, filesystem paths, packages, ports, and service ownership
  with the application's runtime.
- Configure the real DNS and certificate flow before enabling TLS automation.
- Import any existing host and review replacement risk before applying.
- Prove provisioning, firewall convergence, restart, and rollback on the target.
