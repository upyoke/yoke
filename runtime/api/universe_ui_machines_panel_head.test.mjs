import assert from "node:assert/strict";
import test from "node:test";

import {
  renderMachinesPanel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machines_panel.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

function renderOneCard(relay, options = {}) {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  renderMachinesPanel({ document: documentNode }, host, [relay], options);
  return host;
}

const REGISTERED_RELAY = {
  machine_id: "machine-registered",
  hostname: "relay-hostname",
  state: "active",
  liveness: "connected",
  surface_versions: {},
  surface_policies: [],
  capacity: {},
  plan_limits: {},
};

function registeredMachine(facts = {}) {
  return new Map([[REGISTERED_RELAY.machine_id, {
    machine_id: REGISTERED_RELAY.machine_id,
    name: "Studio",
    owner: "Avery",
    ...facts,
  }]]);
}

test("a durable machine record names its machine and owner in the card head", () => {
  const host = renderOneCard(REGISTERED_RELAY, {
    machineById: registeredMachine(),
    showManagement: true,
  });

  const head = byClass(host, "machine-head")[0];
  assert.equal(byClass(head, "machine-host")[0].textContent, "Studio");
  assert.equal(byClass(head, "machine-owner")[0].textContent, "Avery");
  assert.equal(byClass(host, "machine-card-footer")[0].children.length, 1);
  assert.equal(
    byClass(host, "machine-detail-link")[0].href,
    "#/machines/machine-registered",
  );
});

test("both names keep their full value for a reader whose card truncates them", () => {
  const host = renderOneCard(REGISTERED_RELAY, {
    machineById: registeredMachine({
      name: "Studio workstation in the back room",
      owner: "Alexandra Featherstonehaugh-Wallington",
    }),
  });

  assert.equal(
    byClass(host, "machine-host")[0].getAttribute("data-tooltip"),
    "Studio workstation in the back room",
  );
  assert.equal(
    byClass(host, "machine-owner")[0].getAttribute("data-tooltip"),
    "Alexandra Featherstonehaugh-Wallington",
  );
});

test("management controls ride only the caller that asks for them", () => {
  const managed = renderOneCard(REGISTERED_RELAY, {
    machineById: registeredMachine(),
    showManagement: true,
    onRetire: () => {},
  });
  assert.equal(byClass(managed, "machine-card-footer").length, 1);
  assert.equal(byClass(managed, "machine-detail-link").length, 1);
  assert.equal(byClass(managed, "machine-retire").length, 1);

  // The Sessions roster embeds the same card as a status tile: no footer at
  // all, not a footer with its controls hidden.
  const embedded = renderOneCard(REGISTERED_RELAY, {
    machineById: registeredMachine(),
    onRetire: () => {},
  });
  assert.equal(byClass(embedded, "machine-card-footer").length, 0);
  assert.equal(byClass(embedded, "machine-detail-link").length, 0);
  assert.equal(byClass(embedded, "machine-retire").length, 0);
  assert.equal(byClass(embedded, "machine-owner")[0].textContent, "Avery");
});
