// Machines paints identity, relays, and 24h usage without waiting on the
// open-session roster, then fills that roster with its own loading, error,
// and retry. The open read still uses sessions.list {open:true}.

import assert from "node:assert/strict";
import test from "node:test";

import {
  renderMachinesView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_machines.js";
import {
  FakeDocument, byClass, settle, visibleText,
} from "./universe_ui_dom_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

function fail(message) {
  return {
    status: 500,
    envelope: { success: false, error: { message } },
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function machineRow(id, name) {
  return { machine_id: id, name, owner: "Ada", retired_at: null };
}

function relayRow(id, hostname) {
  return {
    relay_id: `machine:${id}`, machine_id: id, hostname,
    relay_version: "launch.1", state: "active", liveness: "connected",
    surface_versions: { "claude-cli": "2.1.238" }, project_ids: [1],
    last_seen_at: "2026-09-17T12:00:00Z", capacity: {},
  };
}

function openSession(id, machineId, facts = {}) {
  return {
    session_id: id,
    machine_id: machineId,
    liveness: "active",
    holdings: { current: [] },
    ...facts,
  };
}

function holding(ref, title, extras = {}) {
  return {
    holding_kind: "work_claim",
    target_kind: "item",
    public_ref: ref,
    item_title: title,
    project_id: 1,
    project_sequence: Number(String(ref).split("-").at(-1)),
    ...extras,
  };
}

function viewClient(handlers) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      const handler = handlers[request.function];
      if (!handler) throw new Error(`unexpected function ${request.function}`);
      return handler(request);
    },
  };
}

async function renderView(handlers) {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const client = viewClient(handlers);
  renderMachinesView({
    document: documentNode,
    client,
    isMounted: () => true,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
  }, main);
  return { main, client };
}

function fastMachines(openHandler) {
  return {
    "machine.list": () => ok({
      machines: [machineRow("m1", "studio")],
      count: 1,
    }),
    "session_control.relay.list": () => ok({
      relays: [relayRow("m1", "studio")],
      count: 1,
    }),
    "sessions.list": (request) => {
      if (request.payload.usage_last_24h) return ok({ rows: [] });
      return openHandler(request);
    },
  };
}

test("machine cards paint while the open roster is still in flight", async () => {
  const held = deferred();
  const { main } = await renderView(fastMachines(() => held.promise));
  await settle();
  assert.equal(byClass(main, "machine-card").length, 1);
  assert.match(visibleText(main, " "), /studio/);
  assert.equal(byClass(main, "machine-work-loading").length, 1);
  assert.match(visibleText(main, " "), /Loading open sessions/);
  assert.equal(byClass(main, "machine-work-row").length, 0);
  held.resolve(ok({
    rows: [openSession("s1", "m1", {
      holdings: { current: [holding("YOK-9", "Held work")] },
    })],
  }));
  await settle();
  assert.equal(byClass(main, "machine-work-loading").length, 0);
  assert.match(visibleText(main, " "), /1 active · 0 other open · 0 steering/);
  assert.match(visibleText(main, " "), /YOK-9/);
  assert.match(visibleText(main, " "), /Held work/);
});

test("a failing open roster leaves machines up and retries only that read", async () => {
  let openCalls = 0;
  const { main, client } = await renderView(fastMachines(() => {
    openCalls += 1;
    if (openCalls === 1) return fail("open roster timed out");
    return ok({
      rows: [openSession("s1", "m1", { liveness: "stale" })],
    });
  }));
  await settle();
  assert.equal(byClass(main, "machine-card").length, 1);
  assert.match(visibleText(main, " "), /open roster timed out/);
  const retry = byClass(main, "machines-retry")[0];
  assert.equal(retry.textContent, "Try again");
  retry.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(openCalls, 2);
  assert.equal(
    client.requests.filter((request) => (
      request.function === "sessions.list" && request.payload.open
    )).length,
    2,
  );
  assert.equal(
    client.requests.filter((request) => request.function === "machine.list").length,
    1,
  );
  assert.match(visibleText(main, " "), /0 active · 1 other open · 0 steering/);
});

test("a large open roster keeps every session in the machine totals", async () => {
  const rows = [];
  for (let index = 0; index < 40; index += 1) {
    rows.push(openSession(`a-${index}`, "alpha", {
      liveness: index < 25 ? "active" : "stale",
      holdings: index < 5
        ? { current: [holding(`YOK-${100 + index}`, `Alpha ${index}`)] }
        : { current: [] },
    }));
    rows.push(openSession(`b-${index}`, "beta", {
      liveness: "active",
      holdings: {
        current: index === 0
          ? [{
            holding_kind: "work_claim",
            target_kind: "steering",
            project_id: 1,
            strategy_docs: ["CURRENT-PLAN"],
          }]
          : [],
      },
    }));
  }
  const { main } = await renderView({
    "machine.list": () => ok({
      machines: [machineRow("alpha", "alpha-box"), machineRow("beta", "beta-box")],
      count: 2,
    }),
    "session_control.relay.list": () => ok({
      relays: [relayRow("alpha", "alpha-box"), relayRow("beta", "beta-box")],
      count: 2,
    }),
    "sessions.list": (request) => {
      if (request.payload.usage_last_24h) return ok({ rows: [] });
      assert.deepEqual(request.payload, { open: true });
      return ok({ rows });
    },
  });
  await settle();
  const headings = byClass(main, "machine-work")
    .map((node) => node.children[0].textContent);
  assert.deepEqual(headings, [
    "25 active · 15 other open · 0 steering",
    "40 active · 0 other open · 1 steering",
  ]);
  assert.equal(byClass(main, "machine-work-row").length, 5);
  assert.equal(byClass(main, "machine-work-rest")[0].children.length, 3);
});
