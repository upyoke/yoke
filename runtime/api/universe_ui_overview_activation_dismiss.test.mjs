// The Overview activation stack's dismissal flow, the host-facts payload
// forwarding seam, and empty-state coexistence. Module states and
// drawn copy live in universe_ui_overview_activation.test.mjs.

import assert from "node:assert/strict";
import test from "node:test";

import {
  allNodes,
  byClass,
  ownTextContent,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  activationAnswer,
  activationClient,
  mountOverview,
} from "./universe_ui_activation_test_support.mjs";

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

const ALL_ACTIVATED = {
  finish_installation_wizard: "activated", connect_harness: "activated",
  run_onboard: "activated", first_deploy: "activated",
};

test("the mount forwards the host machine fact into the read", async (t) => {
  stubFetch(t);
  const client = activationClient(activationAnswer());
  const { mounted } = await mountOverview(client, {
    data: { onboarding: { machineConnected: true } },
  });
  const request = client.requests.find(
    (item) => item.function === "overview.activation.get",
  );
  assert.deepEqual(request.payload, {
    host_facts: { machine_connected: true },
  });
  mounted.unmount();

  // Without the capability — or with a non-boolean shape — nothing is
  // forwarded and the engine derives from its own signals alone.
  for (const capabilities of [
    undefined, { data: { onboarding: { machineConnected: "yes" } } },
  ]) {
    const bare = activationClient(activationAnswer());
    const bareMount = await mountOverview(bare, capabilities);
    const bareRequest = bare.requests.find(
      (item) => item.function === "overview.activation.get",
    );
    assert.deepEqual(bareRequest.payload, {});
    bareMount.mounted.unmount();
  }
});

test("dismiss: ✕ on activated modules hides the module for good", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: ALL_ACTIVATED, dismissAvailable: true,
  });
  const { root, mounted } = await mountOverview(activationClient(answer));

  const dismissButtons = byClass(root, "activation-dismiss");
  assert.equal(dismissButtons.length, 4);
  assert.equal(
    dismissButtons[1].getAttribute("data-tooltip"),
    "Hide — bring it back from Profile",
  );

  dismissButtons[1].dispatchEvent(new Event("click"));
  await settle();
  const cards = byClass(root, "activation-module");
  assert.deepEqual(cards.map((card) => card.attributes.get("data-module")), [
    "finish_installation_wizard", "run_onboard", "first_deploy",
  ]);
  // No count, no show-again, no restore: the only way back is Profile.
  assert.equal(byClass(root, "activation-restore-line").length, 0);
  assert.equal(byClass(root, "activation-show").length, 0);
  assert.equal(byClass(root, "activation-restore").length, 0);
  assert.equal(byClass(root, "overview-section")[0].hidden, false);
  mounted.unmount();
});

test("all dismissed: the Onboarding section disappears from Overview", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: ALL_ACTIVATED,
    dismissed: [
      "finish_installation_wizard", "connect_harness", "run_onboard",
      "first_deploy",
    ],
    dismissAvailable: true,
  });
  const { root, mounted } = await mountOverview(activationClient(answer));

  assert.equal(byClass(root, "activation-module").length, 0);
  assert.equal(byClass(root, "activation-restore-line").length, 0);
  const onboarding = byClass(root, "overview-section").find(
    (node) => (node.attributes.get("data-key") || "").includes("onboarding")
      || allNodes(node).some((n) => n.textContent === "Onboarding"),
  );
  assert.ok(onboarding);
  assert.equal(onboarding.hidden, true);
  mounted.unmount();
});

test("hiding the last visible module hides the section too", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: ALL_ACTIVATED,
    dismissed: ["finish_installation_wizard", "connect_harness", "run_onboard"],
    dismissAvailable: true,
  });
  const { root, mounted } = await mountOverview(activationClient(answer));
  const onboarding = byClass(root, "overview-section").find(
    (node) => allNodes(node).some((n) => n.textContent === "Onboarding"),
  );
  assert.equal(onboarding.hidden, false);
  byClass(root, "activation-dismiss")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.equal(byClass(root, "activation-module").length, 0);
  assert.equal(onboarding.hidden, true);
  mounted.unmount();
});

test("no bound actor: the ✕ never renders even on activated modules", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: ALL_ACTIVATED, dismissAvailable: false,
  });
  const { root, mounted } = await mountOverview(activationClient(answer));

  assert.equal(byClass(root, "activation-module").length, 4);
  assert.equal(byClass(root, "activation-dismiss").length, 0);
  mounted.unmount();
});

test("empty live bands remain visible beside day-zero activation", async (t) => {
  stubFetch(t);
  const empty = {
    "strategy.doc.list": { docs: [] },
    "items.overview.list": { rows: [] },
    "frontier.list": { ready_rows: [], blocked_rows: [] },
    "deployment_runs.list": { rows: [] },
  };
  const { root, mounted } = await mountOverview(
    activationClient(activationAnswer(), empty),
  );

  assert.deepEqual(
    byClass(root, "overview-band-title").map((node) => node.textContent),
    [
      "Standing", "Plans", "Waiting", "Ready", "Active", "Shipping",
      "Done (24h)",
    ],
  );
  const text = allNodes(root)
    .map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes("No strategy documents in this band."));
  assert.ok(text.includes("No deployment run is in flight."));
  mounted.unmount();
});

test("non-empty reads draw cards while activation is still day zero", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountOverview(
    activationClient(activationAnswer()),
  );

  assert.deepEqual(
    byClass(root, "overview-section-title").map((node) => node.textContent),
    ["Onboarding", "Strategy", "Frontier"],
  );
  assert.equal(byClass(root, "overview-doc-card").length, 1);
  assert.equal(byClass(root, "overview-item-card").length, 1);
  assert.equal(byClass(root, "overview-run-card").length, 1);
  mounted.unmount();
});
