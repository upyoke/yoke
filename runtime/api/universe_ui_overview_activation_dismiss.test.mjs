// The Overview activation stack's dismissal flow, the host-facts payload
// forwarding seam, and the day-zero ghost-panel rule. Module states and
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

test("dismiss: ✕ on activated modules, restore line, show, restore", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: ALL_ACTIVATED, dismissAvailable: true,
  });
  const { root, mounted } = await mountOverview(activationClient(answer));

  const dismissButtons = byClass(root, "activation-dismiss");
  assert.equal(dismissButtons.length, 4);
  assert.equal(
    dismissButtons[1].attributes.get("title"),
    "Dismiss — signals keep tracking; restore any time",
  );

  dismissButtons[1].dispatchEvent(new Event("click"));
  await settle();
  let cards = byClass(root, "activation-module");
  assert.deepEqual(cards.map((card) => card.attributes.get("data-module")), [
    "finish_installation_wizard", "run_onboard", "first_deploy",
  ]);
  const restoreLine = byClass(root, "activation-restore-line")[0];
  assert.equal(ownTextContent(restoreLine), "1 dismissed module(s) · ");
  const show = byClass(restoreLine, "activation-show")[0];
  assert.equal(show.textContent, "show");

  show.dispatchEvent(new Event("click"));
  await settle();
  cards = byClass(root, "activation-module");
  assert.equal(cards.length, 4);
  const revealed = cards[1];
  assert.ok(revealed.classList.contains("dismissed"));
  assert.equal(byClass(root, "activation-restore-line").length, 0);

  const restore = byClass(revealed, "activation-restore")[0];
  restore.dispatchEvent(new Event("click"));
  await settle();
  const restored = byClass(root, "activation-module")[1];
  assert.equal(restored.classList.contains("dismissed"), false);
  assert.equal(byClass(restored, "activation-dismiss").length, 1);
  mounted.unmount();
});

test("all dismissed: the stack collapses to the restore line", async (t) => {
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
  assert.equal(
    ownTextContent(byClass(root, "activation-restore-line")[0]),
    "4 dismissed module(s) · ",
  );
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

test("a day-zero section collapses to its ghost; activation revives it", async (t) => {
  stubFetch(t);
  const empty = {
    "strategy.doc.list": { docs: [] },
    "frontier.list": { ready_rows: [], blocked_rows: [] },
    "deployment_runs.list": { rows: [] },
  };
  const { root, mounted } = await mountOverview(
    activationClient(activationAnswer(), empty),
  );

  const ghosts = byClass(root, "overview-ghost");
  assert.equal(ghosts.length, 3);
  assert.deepEqual(
    byClass(root, "overview-ghost-hint").map((node) => node.textContent),
    [
      "Strategy · activates as the docs fill via /yoke onboard",
      "Frontier · activates when the first items are seeded",
      "Delivery · activates on the first deployment run",
    ],
  );
  mounted.unmount();

  // The same empty reads with the backing modules activated render the
  // ordinary live empty panels, not ghosts.
  const activated = await mountOverview(activationClient(
    activationAnswer({ states: ALL_ACTIVATED }), empty,
  ));
  assert.equal(byClass(activated.root, "overview-ghost").length, 0);
  const text = allNodes(activated.root)
    .map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes("no strategy docs yet"));
  assert.ok(text.includes("No runs in this scope."));
  activated.mounted.unmount();
});

test("a non-empty read keeps its live panel on day zero", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountOverview(
    activationClient(activationAnswer()),
  );

  // Default fixtures serve rows for strategy/frontier/delivery, so nothing
  // ghosts even though no backing module is activated.
  assert.equal(byClass(root, "overview-ghost").length, 0);
  assert.deepEqual(
    byClass(root, "overview-section-icon").map((node) => node.textContent),
    ["❖", "⚡", "◈", "⬈"],
  );
  assert.deepEqual(
    byClass(root, "overview-section-title").map((node) => node.textContent),
    ["Strategy", "Waiting and ready", "Active", "Shipping"],
  );
  mounted.unmount();
});
