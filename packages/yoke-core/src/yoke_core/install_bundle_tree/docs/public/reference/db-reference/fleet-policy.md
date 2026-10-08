# Fleet policy and native launch admission

Fleet timing, message limits, retries, broadcast confirmation, and surface
fallback are product constants in `yoke_contracts.fleet_policy`. Launches have
10 minutes to register from relay pickup. Organization settings retain the
membership choice `membership.auto_join_domain_verified`; the Organization
screen presents it under Membership. Add configuration only when a work item
names the person who needs to change the value.

A relay poll leases assigned launches alongside serial control work. Pending
wake delivery does not prevent launch admission. The relay checks current
reclaimable memory and swap headroom before each native spawn, with a three
second stagger between spawn boundaries. This works on macOS (`vm_stat` and
`sysctl vm.swapusage`) and Linux (`/proc/meminfo`). It requires at least 1 GiB
of available memory and, when swap is enabled, 512 MiB of free swap. A machine
with swap disabled can launch when memory headroom is sufficient.

The launch record names `native_memory_headroom_low`,
`native_swap_headroom_low`, or `native_capacity_unreadable` when no native was
started. Free memory or swap headroom by stopping unused processes, then retry
the launch. Restore the OS capacity probe before retrying an unreadable
reading. Existing lane and worker caps still apply to placement.
