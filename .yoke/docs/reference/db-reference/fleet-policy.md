# Fleet policy and native launch admission

`yoke_contracts.fleet_policy` owns timing, message limits, retries, broadcast
confirmation and surface fallback as product constants. Launch registration
has 10 minutes from relay pickup. Organization settings retain
`membership.auto_join_domain_verified` under Membership. New configuration
requires a work item naming the person who needs to change that value.

Relay polls lease assigned launches alongside serial control/wake work.
Each serialized native spawn checks current reclaimable memory and swap,
with a three-second stagger. macOS uses `/usr/bin/vm_stat` and
`/usr/sbin/sysctl -n vm.swapusage` independently of the relay's filtered PATH;
Linux reads `/proc/meminfo`. Admission needs 1 GiB available memory and,
when swap is enabled, 512 MiB free swap. Disabled swap permits launching
with sufficient memory. Placement also respects configured machine capacity.

Launch and wake records, including Cursor, name `native_memory_headroom_low`,
`native_swap_headroom_low` or `native_capacity_unreadable` when no native starts.
For low headroom, stop unused processes and retry; for unreadable capacity,
restore the OS probe before retrying. Thresholds and refusals come from
`yoke_contracts.machine_config.native_capacity`, using the shared memory-lane
constant in `machine_capacity`.
