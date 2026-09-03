// The harness module drawn per registered machine, and the wizard row that
// names those machines. A second box in the same organization must see
// itself listed as next up rather than reading the first box's harness
// history as its own.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, response, visibleText } from "./universe_ui_dom_test_support.mjs";
import {
  activationAnswer,
  activationClient,
  harnessTargets,
  machineRow,
  mountOverview,
  wizardSubmodules,
} from "./universe_ui_activation_test_support.mjs";

const ALPHA = "11111111-1111-4111-8111-111111111111";
const BETA = "22222222-2222-4222-8222-222222222222";

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

async function mountMachines(t, { harnessState, machines, wizardMachines }) {
  stubFetch(t);
  const answer = activationAnswer({
    states: {
      finish_installation_wizard: "activated",
      connect_harness: harnessState,
    },
    extras: {
      finish_installation_wizard: {
        submodules: wizardSubmodules({ machine: true, project: true }).map(
          (submodule) => (
            submodule.key === "machine_universe"
              ? { ...submodule, machines: wizardMachines || [] } : submodule
          ),
        ),
      },
      connect_harness: {
        machines,
        projects: [{ slug: "yoke", workspace: "/Users/dev/yoke" }],
      },
    },
  });
  const { root, mounted } = await mountOverview(activationClient(answer));
  const cards = byClass(root, "activation-module");
  return { root, wizard: cards[0], harness: cards[1], mounted };
}

test("a relay-only machine reads next up beside a connected one", async (t) => {
  const seen = new Date(Date.now() - 3 * 60 * 1000).toISOString();
  const { wizard, harness, mounted } = await mountMachines(t, {
    harnessState: "in_progress",
    wizardMachines: [
      { machine_id: ALPHA, name: "alpha-box", connected_at: seen },
      { machine_id: BETA, name: "beta-box", connected_at: seen },
    ],
    machines: [
      machineRow({
        machine_id: ALPHA,
        name: "alpha-box",
        state: "activated",
        activated_at: seen,
        surfaces: ["claude-cli", "codex-cli"],
        last_seen_at: seen,
        connected: { executor: "codex", at: seen },
        // The engine lists only targets with evidence; mirror that here.
        targets: harnessTargets(
          { codex: true, "codex-cli": true }, { codex: "green", "codex-cli": "green" },
        ).filter((target) => target.hit),
      }),
      machineRow({
        machine_id: BETA,
        name: "beta-box",
        surfaces: ["claude-cli"],
        last_seen_at: seen,
      }),
    ],
  });

  // The wizard row names every registered machine.
  const machineCheck = byClass(wizard, "activation-check")[0];
  assert.equal(
    byClass(machineCheck, "activation-check-machines")[0].textContent,
    "· 2 machines: alpha-box, beta-box",
  );

  const rows = byClass(harness, "activation-machine");
  assert.deepEqual(rows.map((row) => row.attributes.get("data-machine")), [ALPHA, BETA]);
  assert.deepEqual(
    rows.map((row) => row.attributes.get("data-state")), ["activated", "in_progress"],
  );
  assert.deepEqual(
    rows.map((row) => byClass(row, "activation-machine-mark")[0].textContent),
    ["✓", "○"],
  );
  assert.equal(
    byClass(rows[0], "activation-machine-meta")[0].textContent,
    "· claude-cli, codex-cli · seen 3m ago",
  );
  assert.match(textOf(rows[0]), /codex connected 3m ago\./);
  assert.deepEqual(
    byClass(rows[0], "activation-target").map((chip) => chip.textContent),
    ["Codex ✓", "Codex CLI ✓"],
  );
  // The second box carries none of the first box's chips or connection.
  assert.equal(byClass(rows[1], "activation-target").length, 0);
  assert.ok(textOf(rows[1]).includes(
    "Next up — open a supported harness on this machine.",
  ));
  assert.ok(!textOf(rows[1]).includes("codex connected"));
  // The module is still in progress, so the directories to open follow.
  assert.equal(byClass(harness, "activation-project").length, 1);
  // The lead universe copy yields to the machine rows.
  assert.ok(!textOf(harness).includes("Open a supported harness in a project directory:"));
  mounted.unmount();
});

test("a machine the control plane knows only by id names itself by id", async (t) => {
  const { wizard, harness, mounted } = await mountMachines(t, {
    harnessState: "activated",
    wizardMachines: [{ machine_id: BETA, name: null, connected_at: null }],
    machines: [machineRow({
      machine_id: BETA,
      name: null,
      state: "activated",
      connected: { executor: "cursor", at: "not-a-date" },
    })],
  });

  // The id renders whole: a prefix would collide with other machines.
  assert.equal(
    byClass(wizard, "activation-check-machines")[0].textContent, `· machine ${BETA}`,
  );
  const row = byClass(harness, "activation-machine")[0];
  assert.equal(byClass(row, "activation-machine-name")[0].textContent, `machine ${BETA}`);
  assert.equal(byClass(row, "activation-machine-meta").length, 0);
  assert.ok(textOf(row).includes("cursor connected."));
  mounted.unmount();
});

test("the in-progress harness module lists project directories", async (t) => {
  stubFetch(t);
  const answer = activationAnswer({
    states: {
      finish_installation_wizard: "activated", connect_harness: "in_progress",
    },
    extras: {
      connect_harness: {
        machines: [],
        projects: [
          { slug: "yoke", workspace: "/Users/dev/yoke" },
          { slug: "quiet", workspace: null },
        ],
      },
    },
  });
  const { root, mounted } = await mountOverview(activationClient(answer));

  const harness = byClass(root, "activation-module")[1];
  assert.ok(textOf(harness).includes(
    "Open a supported harness in a project directory:",
  ));
  const rows = byClass(harness, "activation-project");
  assert.equal(rows.length, 2);
  assert.equal(textOf(rows[0]), "yoke · /Users/dev/yoke · cd /Users/dev/yoke");
  // A project with no known directory lists without one.
  assert.equal(textOf(rows[1]), "quiet");
  mounted.unmount();
});

function textOf(node) {
  return visibleText(node);
}
