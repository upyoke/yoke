import assert from "node:assert/strict";
import test from "node:test";
import { appendApprovingAs, renderPendingMachines, resolveMirroredMachineApproval } from "../../packages/yoke-core/src/yoke_core/ui/static/machine_admission_pending.js";
import { renderMachineApproval } from "../../packages/yoke-core/src/yoke_core/ui/static/machine_approval.js";
import { inboxPresentation } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_inbox.js";
import { createDecisionResolver } from "../../packages/yoke-core/src/yoke_core/ui/static/inbox_rows.js";
import { machineRequestRow, renderInbox } from "./universe_ui_inbox_test_support.mjs";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });
const fail = (code) => ({ status: 503, envelope: { success: false, error: { code } } });
const button = (root, label) => allNodes(root).find((n) => n.tagName === "BUTTON" && n.textContent === label);
const tags = (root, name) => allNodes(root).filter((n) => n.tagName === name);
const request = (code = "K7F2", extras = {}) => ({ code, machine: "New laptop", platform: "macOS",
  machine_id: "4f2c9a1e-80d6-4b2c-a447-123456789abc", requested_by: { name: "Morgan", actor_id: 9 },
  expires_at: new Date(Date.now() + 540000).toISOString(), state: "pending", ...extras });

function fixture(t, { rows = [request()], mode = "hosted", options = {}, route, pending } = {}) {
  const document = new FakeDocument(), main = document.createElement("main");
  const controller = new AbortController(), calls = [], timers = new Map();
  let id = 0;
  const clock = document.defaultView;
  clock.setTimeout = (fn, ms) => { timers.set(++id, { fn, ms }); return id; };
  clock.clearTimeout = (key) => timers.delete(key);
  const state = { rows, pending };
  const context = { document, signal: controller.signal, isMounted: () => true, basePath: "/workbench",
    capabilities: { data: { portability: { mode } } },
    client: { async call(call) {
      calls.push(call);
      switch (call.function) {
        case "machine_authorization.pending": return state.pending ? state.pending() : ok({ requests: state.rows });
        case "organizations.get": return ok({ name: "Example org" });
        case "machine.list": return ok({ machines: [], count: 1 });
        case "machine_authorization.get": return ok({ authorization: { ...request(call.payload.code), decision: null, viewer: { name: "Morgan", actor_id: 9 } } });
        case "machine_authorization.resolve":
          state.rows = state.rows.filter((row) => row.code !== call.payload.code);
          return ok({ authorization: { decision: call.payload.action } });
        default: throw new Error(`unexpected function ${call.function}`);
      }
    } },
  };
  const handle = route !== undefined ? renderMachineApproval(context, main, null, route) : renderPendingMachines(context, main, options);
  t.after(() => controller.abort());
  return { document, main, calls, timers, state, controller, handle, clock };
}
const pendingCalls = (f) => f.calls.filter((call) => call.function === "machine_authorization.pending").length;

test("loading stays hidden, and an empty Machines panel stays hidden", async (t) => {
  let finish;
  const f = fixture(t, { pending: () => new Promise((resolve) => { finish = resolve; }) });
  assert.equal(byClass(f.main, "machine-pending")[0].hidden, true);
  assert.doesNotMatch(f.main.textContent, /Loading|loading/);
  finish(ok({ requests: [] })); await settle();
  assert.equal(byClass(f.main, "machine-pending")[0].hidden, true);
  assert.equal(f.timers.size, 0);
});

test("table exposes machine facts, identities, caption, local expiry and unbound requests", async (t) => {
  const f = fixture(t, { mode: "self-host", rows: [request(), request("G8P3", { requested_by: null })] });
  await settle();
  const table = tags(f.main, "TABLE")[0];
  assert.equal(table.className, "items table-stacks-narrow");
  assert.deepEqual(tags(table, "TH").map((n) => n.textContent), ["Code", "Machine", "Requested by", "Expires", "Review"]);
  assert.equal(tags(table, "CAPTION")[0].className, "shell-visually-hidden");
  assert.equal(tags(table, "CAPTION")[0].textContent, "Machines waiting for approval");
  assert.match(table.textContent, /New laptopmacOS · machine 4f2c9a1e-80d6-4b2c-a447-123456789abc/);
  assert.match(table.textContent, /Morgan · actor #9/);
  assert.match(table.textContent, /Not signed in yet/);
  assert.equal(tags(table, "TIME")[0].getAttribute("datetime"), f.state.rows[0].expires_at);
  assert.match(table.textContent, /in 9 minutes/);
  assert.equal(tags(table, "TD").every((cell) => cell.getAttribute("data-label")), true);
  assert.equal(button(table, "Review").getAttribute("aria-controls"), byClass(f.main, "machine-pending-card")[0].id);
});

test("already expired requests show a pill without Review", async (t) => {
  const f = fixture(t, { rows: [request("K7F2", { expires_at: new Date(Date.now() - 1000).toISOString() })] });
  await settle();
  assert.equal(button(f.main, "Review"), undefined);
  assert.equal(byClass(f.main, "pill")[0].textContent, "expired");
  assert.equal(f.timers.size, 0);
});

for (const action of ["approve", "deny"]) test(`Review reuses the inline card and ${action} removes its row but retains the outcome`, async (t) => {
  const f = fixture(t);
  f.clock.history.replaceState({ retained: true }, "", "/workbench/items");
  f.clock.history.pushState({ retained: true }, "", "/workbench/machines");
  await settle(); button(f.main, "Review").dispatchEvent(new Event("click")); await settle();
  assert.equal(f.clock.location.pathname, "/workbench/machine-approval/K7F2");
  assert.deepEqual(f.clock.history.state, { retained: true });
  const review = button(f.main, "Review"), card = byClass(f.main, "machine-pending-card")[0];
  assert.equal(review.getAttribute("aria-controls"), card.id);
  assert.equal(review.getAttribute("aria-expanded"), "true");
  assert.equal(tags(f.main, "TBODY")[0].children[0].getAttribute("aria-selected"), "true");
  assert.equal(f.document.activeElement.tagName, "H2");
  assert.deepEqual(f.calls.find((call) => call.function === "machine_authorization.get").payload, { code: "K7F2" });
  button(f.main, action === "approve" ? "Approve machine" : "Deny").dispatchEvent(new Event("click")); await settle();
  assert.deepEqual(f.calls.find((call) => call.function === "machine_authorization.resolve").payload, { code: "K7F2", action });
  assert.equal(pendingCalls(f), 2);
  assert.equal(tags(f.main, "TABLE").length, 0);
  assert.match(f.main.textContent, action === "approve" ? /is connected to Example org/ : /Request denied/);
  assert.equal(byClass(f.main, "machine-pending")[0].hidden, false);
  f.clock.history.back(); assert.equal(f.clock.location.pathname, "/workbench/items");
});

test("no-code approval route lists requests and selects without entry controls or duplicate headings", async (t) => {
  const f = fixture(t, { route: null }); await settle();
  assert.deepEqual(f.calls.map((c) => c.function), ["machine_authorization.pending"]);
  assert.equal(tags(f.main, "INPUT").length + tags(f.main, "FORM").length, 0);
  button(f.main, "Review").dispatchEvent(new Event("click")); await settle();
  assert.equal(tags(f.main, "H1").length, 1);
  assert.equal(tags(f.main, "H1")[0].textContent, "Approve this machine");
});

test("selected route puts only other requests below its card", async (t) => {
  const f = fixture(t, { route: "k7f2", rows: [request(), request("G8P3")] }); await settle();
  assert.equal(tags(f.main, "H1").length, 1);
  const panel = byClass(f.main, "machine-pending")[0];
  assert.match(panel.textContent, /Other machines waiting \(1\).*G8P3/);
  assert.doesNotMatch(panel.textContent, /K7F2/);
  assert.equal(f.main.children.at(-1).contains(panel), true);
  button(panel, "Review").dispatchEvent(new Event("click")); await settle();
  assert.equal(f.calls.filter((c) => c.function === "machine_authorization.get").at(-1).payload.code, "G8P3");
  assert.match(panel.textContent, /K7F2/);
  assert.doesNotMatch(panel.textContent, /G8P3/);
});

test("empty approval route teaches the connection command", async (t) => {
  const f = fixture(t, { route: null, rows: [] }); await settle();
  assert.equal(byClass(f.main, "machine-pending")[0].hidden, false);
  assert.match(f.main.textContent, /No machines are waiting\. Run yoke connect <server> on the new machine, then open the link it prints\./);
  assert.equal(tags(f.main, "CODE")[0].textContent, "yoke connect <server>");
});

for (const code of ["function_not_registered", "function_version_skew", "storage_unavailable"]) {
  test(`pending refusal ${code} chooses its exact recovery`, async (t) => {
    const f = fixture(t, { pending: () => fail(code), route: "K7F2" }); await settle();
    const panel = byClass(f.main, "machine-pending")[0];
    const skew = code !== "storage_unavailable";
    assert.match(panel.textContent, skew ? /This server can't list waiting machines yet\. Open the link your terminal printed to approve it\./ : /Waiting machines could not be read\./);
    assert.equal(Boolean(button(panel, "Try again")), !skew);
    assert.ok(button(f.main, "Approve machine"));
  });
}

test("network failure retries only pending and leaves a polite status", async (t) => {
  const f = fixture(t, { pending: () => { throw new Error("network"); } }); await settle();
  assert.equal(byClass(f.main, "machine-pending-status")[0].getAttribute("role"), "status");
  assert.match(f.main.textContent, /Waiting machines could not be read/);
  f.state.pending = null; button(f.main, "Try again").dispatchEvent(new Event("click")); await settle();
  assert.equal(pendingCalls(f), 2);
  assert.equal(f.calls.length, 2);
  assert.ok(button(f.main, "Review"));
});

for (const mode of ["local", "unknown"]) test(`${mode} mode replaces pending with reachability and performs no reads`, async (t) => {
  const f = fixture(t, { mode }); await settle();
  assert.equal(f.calls.length, 0);
  assert.match(f.main.textContent, /Reachable here only/);
  assert.match(f.main.textContent, /yoke self-host init/);
  assert.equal(tags(f.main, "TABLE").length, 0);
});

test("visibility refreshes, an open card polls every thirty seconds, and abort releases both timers", async (t) => {
  const f = fixture(t); await settle();
  assert.equal([...f.timers.values()].some(({ ms }) => ms === 30000), false);
  f.document.visibilityState = "hidden"; f.document.dispatchEvent(new Event("visibilitychange")); await settle();
  assert.equal(pendingCalls(f), 1);
  f.document.visibilityState = "visible"; f.document.dispatchEvent(new Event("visibilitychange")); await settle();
  assert.equal(pendingCalls(f), 2);
  button(f.main, "Review").dispatchEvent(new Event("click")); await settle();
  const refresh = [...f.timers.values()].find(({ ms }) => ms === 30000);
  assert.ok(refresh); refresh.fn(); await settle(); assert.equal(pendingCalls(f), 3);
  f.controller.abort();
  f.document.dispatchEvent(new Event("visibilitychange")); refresh.fn(); await settle();
  assert.equal(pendingCalls(f), 3);
  assert.equal([...f.timers.values()].some(({ ms }) => ms === 30000), false);
});

test("expiry repaint removes Review without a read", async (t) => {
  t.mock.timers.enable({ apis: ["Date"], now: Date.now() });
  const f = fixture(t, { rows: [request("K7F2", { expires_at: new Date(Date.now() + 1000).toISOString() })] });
  await settle(); const expiry = [...f.timers.values()].find(({ ms }) => ms === 1000);
  t.mock.timers.tick(1001); expiry.fn();
  assert.equal(button(f.main, "Review"), undefined);
  assert.equal(byClass(f.main, "pill")[0].textContent, "expired");
  assert.equal(pendingCalls(f), 1);
});

test("late and superseded reads cannot overwrite the current list", async (t) => {
  const finishes = [];
  const f = fixture(t, { pending: () => new Promise((resolve) => finishes.push(resolve)) });
  f.handle.reload(); finishes[1](ok({ requests: [request("G8P3")] })); await settle();
  finishes[0](ok({ requests: [request()] })); await settle();
  assert.match(f.main.textContent, /G8P3/); assert.doesNotMatch(f.main.textContent, /K7F2/);
  f.handle.reload(); f.main.replaceChildren(); finishes[2](ok({ requests: [request()] })); await settle();
  assert.equal(f.main.textContent, "");
});

for (const action of ["approve", "deny"]) test(`Inbox ${action} preserves the mirror payload and shows the approving identity`, async () => {
  const row = machineRequestRow(), { main, client } = renderInbox("all", [row]);
  await settle();
  const card = byClass(main, "review-card")[0], actions = byClass(card, "review-actions")[0];
  assert.match(card.textContent, /Approving as Morgan · actor #9\. This machine will act as you\./);
  assert.ok(actions.parentNode.children.findIndex((n) => n.textContent.startsWith("Approving as"))
    < actions.parentNode.children.indexOf(actions));
  assert.equal(inboxPresentation.subjectHref(row), "/machines");
  assert.match(inboxPresentation.decisionOrigin(row), /cannot act until a member approves it as themselves/);
  assert.match(inboxPresentation.decisionSubtitle(row).leading, /match code WXYZ-1234/);
  button(card, action === "approve" ? "Approve" : "Deny").dispatchEvent(new Event("click")); await settle();
  assert.deepEqual(client.requests.filter((c) => c.function === "decision_requests.resolve"), [
    { function: "decision_requests.resolve", payload: { request_id: row.id, action } },
  ]);
  assert.equal(client.requests.filter((c) => c.function === "machine_authorization.pending").length, 1);
  assert.equal(byClass(main, "review-action").length, 0);
  assert.match(main.textContent, action === "approve" ? /Approved/ : /Denied/);
});

test("mirror action preserves request_id fallback and optional notes exactly", async () => {
  const calls = [], context = { client: { call: async (call) => { calls.push(call); return ok({}); } } };
  for (const note of [null, "", "checked the code"]) {
    await resolveMirroredMachineApproval(context, { request_id: 17 }, "deny", note);
    assert.deepEqual(calls.at(-1), { function: "decision_requests.resolve",
      payload: { request_id: 17, action: "deny", ...(note ? { note } : {}) } });
  }
});

for (const rejects of [false, true]) test(`mirror ${rejects ? "network" : "refusal"} failure keeps actions retryable`, async () => {
  const document = new FakeDocument(), wrap = document.createElement("article"), action = document.createElement("button");
  wrap.appendChild(action);
  let finish, reloads = 0;
  const context = { document, client: { call: () => new Promise((resolve, reject) => { finish = rejects ? reject : resolve; }) } };
  const result = createDecisionResolver(context, () => { reloads++; })(machineRequestRow(), "deny", wrap);
  assert.equal(action.disabled, true);
  finish(rejects ? new Error("retry decision") : { status: 503, envelope: { success: false, error: { message: "retry decision" } } });
  await result;
  assert.equal(action.disabled, false); assert.equal(reloads, 0);
  assert.match(byClass(wrap, "inbox-row-error")[0].textContent, /retry decision/);
});

test("approving identity reads once per mount and ignores late replies after abort", async () => {
  const document = new FakeDocument(), controller = new AbortController(), calls = [];
  let finish;
  const context = { document, signal: controller.signal, isMounted: () => true,
    client: { call: (call) => { calls.push(call); return new Promise((resolve) => { finish = resolve; }); } } };
  const hosts = [document.createElement("div"), document.createElement("div")];
  const reads = hosts.map((host) => appendApprovingAs(context, host)); await settle();
  assert.deepEqual(calls, [{ function: "machine_authorization.pending", payload: {} }]);
  controller.abort(); finish(ok({ viewer: { name: "Morgan", actor_id: 9 } })); await Promise.all(reads);
  for (const host of hosts) assert.match(host.textContent, /Approving as your signed-in account/);
  const remount = appendApprovingAs({ ...context, signal: new AbortController().signal }, hosts[0]); await settle();
  finish(ok({ viewer: { name: "Sam", actor_id: 10 } })); await remount;
  assert.equal(calls.length, 2); assert.match(hosts[0].textContent, /Approving as Sam · actor #10/);
});

for (const reply of [ok({}), fail("function_not_registered"), new Error("network")]) {
  test(`missing viewer degrades safely: ${reply instanceof Error ? "network" : reply.status}`, async () => {
    const document = new FakeDocument(), host = document.createElement("div");
    await appendApprovingAs({ document, isMounted: () => true, client: { call: async () => {
      if (reply instanceof Error) throw reply; return reply;
    } } }, host);
    assert.equal(host.textContent, "Approving as your signed-in account. This machine will act as you.");
  });
}

test("other Inbox kinds do not request or display the approving identity", async () => {
  const { main, client } = renderInbox(); await settle();
  assert.doesNotMatch(main.textContent, /Approving as/);
  assert.equal(client.requests.some((c) => c.function === "machine_authorization.pending"), false);
});
