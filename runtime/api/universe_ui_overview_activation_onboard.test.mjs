// The /yoke onboard module's drawn copy. Every sentence comes from the
// engine's checklist facts, because the module once printed one fixed
// execution-ready line for its activated state — which a run blocked at
// its first hosting step still showed, over a universe with no scaffold
// installed and no environments registered.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, response, visibleText } from "./universe_ui_dom_test_support.mjs";
import {
  activationAnswer,
  activationClient,
  mountOverview,
  onboardFacts,
} from "./universe_ui_activation_test_support.mjs";

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

async function mountOnboard(t, { state = "in_progress", onboard = null }) {
  stubFetch(t);
  const answer = activationAnswer({
    states: {
      finish_installation_wizard: "activated",
      connect_harness: "activated",
      run_onboard: state,
    },
    extras: { run_onboard: { onboard } },
  });
  const { root, mounted } = await mountOverview(activationClient(answer));
  const card = byClass(root, "activation-module").find(
    (node) => node.attributes.get("data-module") === "run_onboard",
  );
  return { card, mounted };
}

test("a blocked run names its blocker and how far it got", async (t) => {
  const { card, mounted } = await mountOnboard(t, {
    onboard: onboardFacts({
      run_status: "blocked",
      steps_done: 12,
      steps_total: 30,
      next: { step: "17b", title: "Hosting setup" },
      blocker: {
        step: "17b",
        title: "Hosting setup",
        detail: "aws-admin capability row absent",
      },
    }),
  });

  assert.equal(
    byClass(card, "activation-copy")[0].textContent,
    "Blocked at 17b Hosting setup — aws-admin capability row absent.",
  );
  assert.equal(
    byClass(card, "activation-progress")[0].textContent,
    "12 of 30 steps done.",
  );
  // The happy-path sentence never appears over an unfinished run.
  assert.ok(!visibleText(card).includes("Execution-ready"));
  mounted.unmount();
});

test("a blocked row with no detail still names the step it stopped on", async (t) => {
  const { card, mounted } = await mountOnboard(t, {
    onboard: onboardFacts({
      run_status: "blocked",
      steps_done: 3,
      steps_total: 30,
      blocker: { step: "17a", title: "Scaffold Pack install", detail: "" },
    }),
  });

  assert.equal(
    byClass(card, "activation-copy")[0].textContent,
    "Blocked at 17a Scaffold Pack install.",
  );
  mounted.unmount();
});

test("an open run reads its next step, not its whole route", async (t) => {
  const { card, mounted } = await mountOnboard(t, {
    onboard: onboardFacts({
      run_status: "open",
      steps_done: 28,
      steps_total: 30,
      next: { step: "17h", title: "Work seeding" },
    }),
  });

  assert.equal(
    byClass(card, "activation-copy")[0].textContent,
    "Next: 17h Work seeding.",
  );
  assert.equal(
    byClass(card, "activation-progress")[0].textContent,
    "28 of 30 steps done.",
  );
  mounted.unmount();
});

test("a finished run claims only the outcomes it produced", async (t) => {
  const { card, mounted } = await mountOnboard(t, {
    state: "activated",
    onboard: onboardFacts({
      run_status: "complete",
      steps_done: 30,
      steps_total: 30,
      strategy_docs: true,
      scaffold_installed: true,
      environments: ["stage", "prod"],
    }),
  });

  assert.equal(
    byClass(card, "activation-copy")[0].textContent,
    "Execution-ready — strategy filled, webapp-scaffold installed, " +
    "stage + prod provisioned.",
  );
  assert.equal(byClass(card, "activation-progress").length, 0);
  mounted.unmount();
});

test("a mapped existing app never claims a scaffold install", async (t) => {
  const { card, mounted } = await mountOnboard(t, {
    state: "activated",
    onboard: onboardFacts({
      run_status: "complete",
      steps_done: 30,
      steps_total: 30,
      strategy_docs: true,
      environments: ["stage"],
    }),
  });

  const copy = byClass(card, "activation-copy")[0].textContent;
  assert.equal(copy, "Execution-ready — strategy filled, stage provisioned.");
  assert.ok(!copy.includes("scaffold"));
  mounted.unmount();
});

test("a finished run with nothing to show says only that", async (t) => {
  const { card, mounted } = await mountOnboard(t, {
    state: "activated",
    onboard: onboardFacts({
      run_status: "complete", steps_done: 30, steps_total: 30,
    }),
  });

  assert.equal(
    byClass(card, "activation-copy")[0].textContent,
    "Onboarding checklist complete.",
  );
  mounted.unmount();
});

test("a universe with no run reads the route into the harness", async (t) => {
  const { card, mounted } = await mountOnboard(t, { onboard: null });

  assert.equal(
    byClass(card, "activation-copy")[0].textContent,
    "In your harness: strategy → execution profile → Packs → envs → " +
    "domain → infra.",
  );
  assert.equal(byClass(card, "activation-progress").length, 0);
  mounted.unmount();
});

test("a later blocked run reports itself under an activated card", async (t) => {
  const { card, mounted } = await mountOnboard(t, {
    state: "activated",
    onboard: onboardFacts({
      run_status: "blocked",
      steps_done: 4,
      steps_total: 30,
      blocker: { step: "17b", title: "Hosting setup", detail: "no credentials" },
    }),
  });

  assert.equal(card.attributes.get("data-state"), "activated");
  assert.equal(
    byClass(card, "activation-copy")[0].textContent,
    "Blocked at 17b Hosting setup — no credentials.",
  );
  mounted.unmount();
});

test("a run a deployment overtook reads done and names the deployment", async (t) => {
  const { card, mounted } = await mountOnboard(t, {
    state: "activated",
    onboard: onboardFacts({
      run_status: "superseded",
      superseded_by: {
        deployment_run_id: "run-20260903-001",
        status: "succeeded",
        at: "2026-09-03T16:22:30Z",
      },
      steps_done: 10,
      steps_total: 22,
    }),
  });

  assert.equal(
    byClass(card, "activation-copy")[0].textContent,
    "Onboarding done — superseded by deployment run-20260903-001 on 2026-09-03.",
  );
  assert.equal(byClass(card, "activation-progress").length, 0);
  assert.ok(!visibleText(card).includes("Blocked"));
  mounted.unmount();
});
