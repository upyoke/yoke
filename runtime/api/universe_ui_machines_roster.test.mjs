import assert from "node:assert/strict";
import test from "node:test";

import {
  activeMachines,
  offlineRelay,
  registeredMachineRelays,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machines_roster.js";

const MACHINES = [
  { machine_id: "online-1", name: "studio", owner: "Ada", retired_at: null },
  { machine_id: "offline-1", name: "back-room", owner: "Ada", retired_at: null },
  { machine_id: "retired-1", name: "old-box", owner: "Ada", retired_at: "2026-08-20T10:00:00Z" },
];

const RELAYS = [
  { machine_id: "online-1", hostname: "studio", liveness: "connected", state: "active" },
  // A relay whose machine registration is gone: the identity the registry no
  // longer recognises, which is exactly what a relay-only roster would show.
  { machine_id: "unregistered-1", hostname: "old-mini", liveness: "silent", state: "idle" },
];

test("the roster is the registry's answer, enriched by whatever relay exists", () => {
  const rows = registeredMachineRelays(MACHINES, RELAYS);

  assert.deepEqual(rows.map((row) => row.machine_id), ["online-1", "offline-1"]);
  // A registered machine with a live relay keeps that relay's reading.
  assert.equal(rows[0].liveness, "connected");
  // A registered machine with no relay is offline, which is a reading, not an
  // absence — it stays on the roster rather than disappearing from it.
  assert.equal(rows[1].liveness, "silent");
  assert.equal(rows[1].state, "offline");
  assert.equal(rows[1].hostname, "back-room");
});

test("a retired machine and an unregistered relay identity are both left out", () => {
  const ids = registeredMachineRelays(MACHINES, RELAYS).map((row) => row.machine_id);

  assert.equal(ids.includes("retired-1"), false);
  assert.equal(ids.includes("unregistered-1"), false);
  assert.deepEqual(activeMachines(MACHINES).map((row) => row.machine_id), [
    "online-1", "offline-1",
  ]);
});

test("an empty registry yields an empty roster whatever the relays report", () => {
  assert.deepEqual(registeredMachineRelays([], RELAYS), []);
  assert.deepEqual(registeredMachineRelays(undefined, undefined), []);
});

test("the offline stand-in carries the shape a card reads", () => {
  const row = offlineRelay({ machine_id: "m", name: "named" });

  assert.equal(row.hostname, "named");
  assert.deepEqual(row.surface_versions, {});
  assert.deepEqual(row.capacity, {});
  assert.deepEqual(row.surface_policies, []);
});
