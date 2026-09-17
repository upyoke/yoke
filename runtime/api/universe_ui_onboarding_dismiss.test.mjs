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
  mountWorkbench,
} from "./universe_ui_onboarding_test_support.mjs";

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
  const { mounted } = await mountWorkbench(client, {
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
    const bareMount = await mountWorkbench(bare, capabilities);
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
  const { root, mounted } = await mountWorkbench(activationClient(answer));

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
  assert.equal(byClass(root, "onboarding-control")[0].hidden, true);
  mounted.unmount();
});

test("the Setup control waits for its read rather than flashing", async (t) => {
  stubFetch(t);
  // The read never resolves, so what is left to do is still undecided while
  // the rest of the workbench draws. The control stays hidden: showing a
  // marker first and taking it away once the read landed is the flash anyone
  // who had dismissed every module saw on every load.
  const answer = activationAnswer({ states: ALL_ACTIVATED });
  const client = activationClient(answer);
  const pendingRead = {
    requests: client.requests,
    call(request) {
      if (request.function === "overview.activation.get") {
        return new Promise(() => {});
      }
      return client.call(request);
    },
  };
  const { root, mounted } = await mountWorkbench(pendingRead);
  await settle();

  assert.equal(byClass(root, "onboarding-control")[0].hidden, true);
  assert.equal(byClass(root, "activation-module").length, 0);
  // The rest of the screen is not held up by it.
  assert.ok(byClass(root, "work-band").length > 1);
  mounted.unmount();
});

test("work still to do shows the control, counted from the read", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: {
      finish_installation_wizard: "activated", connect_harness: "activated",
      run_onboard: "not_started", first_deploy: "not_started",
    },
  });
  const { root, mounted } = await mountWorkbench(activationClient(answer));

  const control = byClass(root, "onboarding-control")[0];
  assert.equal(control.hidden, false);
  assert.equal(byClass(root, "onboarding-trigger")[0].textContent, "Setup · 2/4");
  // The whole stack is one press away, with every module's own actions.
  assert.equal(byClass(root, "activation-module").length, 4);
  // Hovering says which steps are left without opening anything.
  assert.deepEqual(
    byClass(root, "onboarding-summary-step").map(ownTextContent),
    [
      "✓ Finish the installation wizard",
      "✓ Connect a harness",
      "○ Run /yoke onboard",
      "○ First deploy",
    ],
  );
  mounted.unmount();
});

test("everything complete retires the control entirely", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({ states: ALL_ACTIVATED });
  const { root, mounted } = await mountWorkbench(activationClient(answer));

  assert.equal(byClass(root, "onboarding-control")[0].hidden, true);
  // The modules are still rendered inside the dialog, so Profile's reset
  // brings back a stack that still has its actions.
  assert.equal(byClass(root, "activation-module").length, 4);
  mounted.unmount();
});

test("an unresolved read says so rather than claiming completion", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({ states: ALL_ACTIVATED });
  const client = activationClient(answer);
  const failingRead = {
    requests: client.requests,
    call(request) {
      if (request.function === "overview.activation.get") {
        return Promise.resolve({
          status: 500,
          envelope: { success: false, error: { message: "unavailable" } },
        });
      }
      return client.call(request);
    },
  };
  const { root, mounted } = await mountWorkbench(failingRead);
  await settle();

  assert.equal(byClass(root, "activation-unresolved").length, 1);
  mounted.unmount();
});

test("all dismissed: nothing is left to count and the control goes", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: {
      finish_installation_wizard: "activated", connect_harness: "not_started",
      run_onboard: "not_started", first_deploy: "not_started",
    },
    dismissed: [
      "finish_installation_wizard", "connect_harness", "run_onboard",
      "first_deploy",
    ],
    dismissAvailable: true,
  });
  const { root, mounted } = await mountWorkbench(activationClient(answer));

  assert.equal(byClass(root, "activation-module").length, 0);
  assert.equal(byClass(root, "activation-restore-line").length, 0);
  assert.equal(byClass(root, "onboarding-control")[0].hidden, true);
  mounted.unmount();
});

test("dismissing a module takes it out of the reckoning too", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: {
      finish_installation_wizard: "activated", connect_harness: "activated",
      run_onboard: "activated", first_deploy: "not_started",
    },
    dismissAvailable: true,
  });
  const { root, mounted } = await mountWorkbench(activationClient(answer));
  assert.equal(byClass(root, "onboarding-trigger")[0].textContent, "Setup · 3/4");
  // Hiding one of the finished three leaves two of three still complete.
  byClass(root, "activation-dismiss")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.equal(byClass(root, "onboarding-trigger")[0].textContent, "Setup · 2/3");
  mounted.unmount();
});

test("no bound actor: the ✕ never renders even on activated modules", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: ALL_ACTIVATED, dismissAvailable: false,
  });
  const { root, mounted } = await mountWorkbench(activationClient(answer));

  assert.equal(byClass(root, "activation-module").length, 4);
  assert.equal(byClass(root, "activation-dismiss").length, 0);
  mounted.unmount();
});

test("empty live bands remain visible beside day-zero onboarding", async (t) => {
  stubFetch(t);
  const empty = {
    "strategy.surface.list": { docs: [], writes: [] },
    "items.overview.list": { rows: [] },
    "frontier.list": { ready_rows: [], blocked_rows: [] },
    "deployment_runs.list": { rows: [] },
  };
  const { root, mounted } = await mountWorkbench(
    activationClient(activationAnswer(), empty),
  );

  assert.deepEqual(
    byClass(root, "work-band-title").map((node) => node.textContent),
    ["Waiting", "Ready", "Active", "Done (24h)"],
  );
  const text = allNodes(root).map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes("Nothing is stopped."));
  assert.ok(text.includes("Nothing finished in the last 24 hours."));
  mounted.unmount();
});

test("non-empty reads draw cards while onboarding is still day zero", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountWorkbench(
    activationClient(activationAnswer()),
  );

  assert.equal(byClass(root, "onboarding-trigger")[0].textContent, "Setup · 0/4");
  assert.equal(byClass(root, "work-item-card").length, 1);
  mounted.unmount();
});
