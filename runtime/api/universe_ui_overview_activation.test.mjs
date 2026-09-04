// The Overview activation-module stack: module states across the signal
// matrix, the drawn copy for each state, the wizard checklist, and the
// harness module's lead copy. Per-machine rows live in
// universe_ui_overview_activation_machines.test.mjs; dismissal and payload
// forwarding in universe_ui_overview_activation_dismiss.test.mjs.

import assert from "node:assert/strict";
import test from "node:test";

import {
  allNodes,
  byClass,
  response,
  visibleText,
} from "./universe_ui_dom_test_support.mjs";
import {
  activationAnswer,
  activationClient,
  harnessTargets,
  machineRow,
  mountOverview,
  wizardSubmodules,
} from "./universe_ui_activation_test_support.mjs";

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

function moduleCards(root) {
  return byClass(root, "activation-module");
}

function textOf(node) {
  return visibleText(node);
}

test("day zero: module one is next up, the rest wait in order", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: { finish_installation_wizard: "in_progress" },
    extras: {
      finish_installation_wizard: {
        submodules: wizardSubmodules({}, "no host machine fact supplied"),
      },
    },
  });
  const { root, mounted } = await mountOverview(activationClient(answer));

  const cards = moduleCards(root);
  assert.deepEqual(cards.map((card) => card.attributes.get("data-module")), [
    "finish_installation_wizard", "connect_harness", "run_onboard",
    "first_deploy",
  ]);
  assert.deepEqual(cards.map((card) => card.attributes.get("data-state")), [
    "in_progress", "not_started", "not_started", "not_started",
  ]);
  assert.deepEqual(
    cards.map((card) => byClass(card, "activation-medallion")[0].textContent),
    ["1", "2", "3", "4"],
  );
  assert.deepEqual(
    cards.map((card) => byClass(card, "pill")[0].textContent),
    ["next up", "waits", "waits", "waits"],
  );
  assert.deepEqual(
    cards.map((card) => byClass(card, "activation-title")[0].textContent),
    [
      "Finish the installation wizard", "Connect a harness",
      "Run /yoke onboard", "First deploy",
    ],
  );
  const onboardTitle = byClass(cards[2], "activation-title")[0];
  assert.equal(
    onboardTitle.attributes.get("title"),
    "Run this in your harness — the web never invokes a skill",
  );
  // Which signal derives a state explains the model to its designers; it is
  // never printed on a member's dashboard, and neither is the engine
  // vocabulary that carries it.
  const stackText = textOf(byClass(root, "activation-stack")[0]);
  for (const internal of [
    "signal ·", "HarnessSessionStarted", "run_id", "no host machine fact",
  ]) {
    assert.ok(!stackText.includes(internal), `leaked internal copy: ${internal}`);
  }
  // No dismiss controls exist without an actor.
  assert.equal(byClass(root, "activation-dismiss").length, 0);
  mounted.unmount();
});

test("the wizard checklist renders ✓/○ rows with tail allowances", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: { finish_installation_wizard: "in_progress" },
    extras: {
      finish_installation_wizard: {
        submodules: wizardSubmodules({ machine: true, hosting: true }),
      },
    },
  });
  const { root, mounted } = await mountOverview(activationClient(answer));

  const rows = byClass(root, "activation-check");
  assert.deepEqual(rows.map((row) => row.attributes.get("data-sub")), [
    "machine_universe", "github", "first_project", "hosting",
  ]);
  assert.deepEqual(
    rows.map((row) => byClass(row, "activation-check-mark")[0].textContent),
    ["✓", "○", "○", "✓"],
  );
  assert.deepEqual(
    rows.map((row) => byClass(row, "activation-check-label")[0].textContent),
    [
      "Local universe created", "GitHub connected", "First project created",
      "Hosting connected",
    ],
  );
  // The pending recommended tail row is the only one allowed to wait;
  // the pending REQUIRED row carries no such allowance.
  assert.deepEqual(
    rows.map((row) => byClass(row, "activation-check-optional").length),
    [0, 1, 0, 0],
  );
  assert.equal(
    byClass(rows[1], "activation-check-optional")[0].textContent,
    "· finish any time",
  );
  // A row states what is done, never which engine surface proves it.
  assert.equal(textOf(rows[0]), "✓Local universe created");
  assert.equal(textOf(rows[1]), "○GitHub connected· finish any time");
  // Machine connected mid-wizard reads return-to-terminal, never web-first.
  const wizard = moduleCards(root)[0];
  assert.ok(textOf(wizard).includes(
    "Your machine is connected to your Yoke identity.",
  ));
  const cta = byClass(wizard, "activation-cta")[0];
  assert.equal(textOf(cta), "Return to your terminal and finish yoke onboard");
  assert.equal(byClass(root, "web-first").length, 0);
  mounted.unmount();
});

test("hosted with the machine pending reads the web-first copy", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: { finish_installation_wizard: "in_progress" },
    extras: {
      finish_installation_wizard: {
        submodules: wizardSubmodules({ project: true }),
      },
    },
  });
  const { root, mounted } = await mountOverview(
    activationClient(answer),
    { data: { portability: { mode: "hosted" } } },
  );

  const webFirst = byClass(root, "web-first")[0];
  assert.ok(webFirst, "hosted machine-pending module renders web-first copy");
  const strong = allNodes(webFirst).find((node) => node.tagName === "STRONG");
  assert.equal(strong.textContent, "Install Yoke on your machine");
  const code = allNodes(webFirst).find((node) => node.tagName === "CODE");
  assert.equal(code.textContent, "curl -fsSL https://upyoke.com/install | sh");
  assert.ok(textOf(webFirst).includes(
    " — the wizard connects this machine, then GitHub · Project · " +
    "Hosting fold in here.",
  ));
  // The hosted machine row wears its hosted label.
  assert.equal(
    byClass(root, "activation-check-label")[0].textContent,
    "Machine connected",
  );
  mounted.unmount();
});

test("the harness module answers per machine, never for the universe", async (t) => {
  stubFetch(t);
  const connectedAt = new Date(Date.now() - 5 * 60 * 1000).toISOString();
  const answer = activationAnswer({
    states: {
      finish_installation_wizard: "activated", connect_harness: "activated",
      run_onboard: "in_progress",
    },
    extras: {
      connect_harness: {
        machines: [machineRow({
          state: "activated",
          activated_at: connectedAt,
          surfaces: ["claude-cli"],
          last_seen_at: connectedAt,
          connected: { executor: "claude-code", at: connectedAt },
          targets: harnessTargets({
            "claude-code": true, "claude-cli": true, "claude-vscode": true,
          }),
        })],
        projects: [{ slug: "yoke", workspace: "/Users/dev/yoke" }],
      },
    },
  });
  const { root, mounted } = await mountOverview(activationClient(answer));

  const cards = moduleCards(root);
  assert.deepEqual(cards.map((card) => card.attributes.get("data-state")), [
    "activated", "activated", "in_progress", "not_started",
  ]);
  assert.deepEqual(
    cards.slice(0, 2).map(
      (card) => byClass(card, "activation-medallion")[0].textContent,
    ),
    ["✓", "✓"],
  );
  const harness = cards[1];
  const machines = byClass(harness, "activation-machine");
  assert.equal(machines.length, 1);
  assert.equal(machines[0].attributes.get("data-state"), "activated");
  assert.equal(byClass(machines[0], "activation-machine-name")[0].textContent, "alpha-box");
  assert.match(textOf(machines[0]), /claude-code connected 5m ago\./);
  const chips = byClass(machines[0], "activation-target");
  assert.deepEqual(chips.map((chip) => chip.textContent), [
    "Claude Code ✓", "Codex", "Cursor",
    "Claude CLI ✓", "Codex CLI", "Cursor CLI",
    "Claude in VS Code ✓", "Cursor IDE",
  ]);
  assert.deepEqual(
    chips.map((chip) => chip.attributes.get("data-hit")),
    ["true", "false", "false", "true", "false", "false", "true", "false"],
  );
  // Why the unlit targets are not blockers explains the activation model;
  // the chips carry that themselves without a note beneath them.
  assert.equal(byClass(harness, "activation-note").length, 0);
  // An activated module lists no project directories to open.
  assert.equal(byClass(harness, "activation-project").length, 0);
  // The unlocked third module carries its next-action copy.
  assert.ok(textOf(cards[2]).includes(
    "In your harness: strategy → execution profile → Packs → envs → " +
    "domain → infra.",
  ));
  mounted.unmount();
});

test("an unapproved harness reads red with its remediation", async (t) => {
  stubFetch(t);
  const surface = "Codex's hook-trust prompt";
  const answer = activationAnswer({
    states: {
      finish_installation_wizard: "activated", connect_harness: "activated",
      run_onboard: "in_progress",
    },
    extras: {
      connect_harness: {
        machines: [machineRow({
          state: "activated",
          connected: { executor: "codex", at: new Date().toISOString() },
          targets: harnessTargets(
            { codex: true, "codex-cli": true },
            { codex: "red", "codex-cli": "red" },
            { codex: surface, "codex-cli": surface },
          ),
        })],
        projects: [],
      },
    },
  });
  const { root, mounted } = await mountOverview(activationClient(answer));

  const harness = moduleCards(root)[1];
  const chips = byClass(harness, "activation-target");
  // Registered, so it is a hit — but unapproved hooks are broken, not idle.
  assert.equal(chips[1].textContent, "Codex");
  assert.equal(chips[1].attributes.get("data-hit"), "true");
  assert.equal(chips[1].attributes.get("data-hook-health"), "red");
  const remediation = byClass(harness, "activation-remediation");
  // One line per approval surface, not one per red chip.
  assert.equal(remediation.length, 1);
  assert.equal(
    remediation[0].textContent,
    "Waiting on you — trust this project's hooks in " + `${surface}.`,
  );
  mounted.unmount();
});

test("fully deployed: every module reads activated with its copy", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: {
      finish_installation_wizard: "activated", connect_harness: "activated",
      run_onboard: "activated", first_deploy: "activated",
    },
  });
  const { root, mounted } = await mountOverview(activationClient(answer));

  const cards = moduleCards(root);
  assert.deepEqual(
    cards.map((card) => byClass(card, "pill")[0].textContent),
    ["activated", "activated", "activated", "activated"],
  );
  assert.ok(textOf(cards[3]).includes("Live — onboarding is done."));
  // The onboarding card draws its own copy from the run's checklist facts;
  // universe_ui_overview_activation_onboard.test.mjs owns those derivations.
  mounted.unmount();
});

test("an unresolved activation read renders pending, never states", async (t) => {
  stubFetch(t);
  const client = activationClient(activationAnswer());
  const failing = {
    requests: client.requests,
    async call(request) {
      if (request.function === "overview.activation.get") {
        return {
          status: 200,
          envelope: { success: false, error: { message: "boom" } },
        };
      }
      return client.call(request);
    },
  };
  const { root, mounted } = await mountOverview(failing);

  assert.equal(moduleCards(root).length, 0);
  assert.equal(
    byClass(root, "activation-unresolved")[0].textContent,
    "activation signals unresolved",
  );
  mounted.unmount();
});
