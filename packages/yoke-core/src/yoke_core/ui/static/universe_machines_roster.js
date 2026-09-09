// Which machines exist is the registry's answer, on every page that asks.
//
// A relay is telemetry about a machine, not evidence that one is registered:
// a relay row outlives the registration it was created under, so a roster
// built from relays alone shows identities the registry has already stopped
// recognising, and shows nothing at all for a registered machine that is
// merely offline. Both pages therefore start from the registry and let the
// relay enrich it, which is also why they agree.

// A registered machine with no live relay still belongs on the roster; it is
// offline, which is a reading, not an absence.
export function offlineRelay(machine) {
  return {
    machine_id: machine.machine_id,
    hostname: machine.name,
    liveness: "silent",
    state: "offline",
    surface_versions: {},
    surface_confirmed_absent: [],
    plan_limits: {},
    capacity: {},
    surface_policies: [],
  };
}

export function relaysByMachineId(relays) {
  return new Map((relays || []).map((row) => [String(row.machine_id), row]));
}

// Retired machines keep their history and their detail page; they leave the
// roster, because the roster answers what can run now.
export function activeMachines(machines) {
  return (machines || []).filter((machine) => !machine.retired_at);
}

// One reading per registered, non-retired machine, in registry order.
export function registeredMachineRelays(machines, relays) {
  const byId = relaysByMachineId(relays);
  return activeMachines(machines).map(
    (machine) => byId.get(String(machine.machine_id)) || offlineRelay(machine),
  );
}

export function machinesById(machines) {
  return new Map(
    activeMachines(machines).map((machine) => [String(machine.machine_id), machine]),
  );
}
