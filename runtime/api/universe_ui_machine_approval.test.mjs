import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { renderApprovalCard, renderMachineApproval } from "../../packages/yoke-core/src/yoke_core/ui/static/machine_approval.js";
import { localReachabilityNotice } from "../../packages/yoke-core/src/yoke_core/ui/static/local_reachability_notice.js";
import { REGISTRY_SKEW_CODES, isRegistrySkewError } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_view_support.js";
import { parseUniverseRoute } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";

function page({ decision = null, failure = null, readError = null, count = 0,
  machine = "My laptop", code = "k7f2", expired = false, state = "pending", mode = "hosted",
  viewer = { actor_id: 9, name: "Morgan" }, requested_by = { actor_id: 9, name: "Morgan" },
  embedded = false, onDecided, waitForDecision, afterRefusal } = {}) {
  const document = new FakeDocument();
  const main = document.createElement("div");
  const requests = [], navigation = [], titles = [];
  let refuse = failure;
  const expires = new Date(Date.now() + (expired ? -120000 : 540000)).toISOString();
  const context = {
    capabilities: { data: { portability: { mode } } },
    document, isMounted: () => true, navigate: (path) => navigation.push(path),
    client: { async call(request) {
      requests.push(request);
      const ok = (result) => ({ status: 200, envelope: { success: true, result } });
      if (request.function === "organizations.get") return ok({ name: "Example org" });
      if (request.function === "machine.list") return ok({ count, machines: [] });
      if (request.function === "machine_authorization.get") {
        if (readError) return { status: 403, envelope: { success: false, error: readError } };
        return ok({ authorization: { code, machine, machine_id: "4f2c9a1e-80d6-4b2c-a447-123456789abc", platform: "macOS", expires_at: expires, decision, state, viewer, requested_by } });
      }
      if (refuse) {
        const error = refuse;
        refuse = null;
        if (afterRefusal) ({ state, decision, readError } = { state, decision, readError, ...afterRefusal });
        return { status: 503, envelope: { success: false, error } };
      }
      if (waitForDecision) await waitForDecision;
      return ok({ authorization: { decision: request.payload.action } });
    } },
  };
  if (embedded) renderApprovalCard(context, main, code, { embedded, onDecided });
  else renderMachineApproval(context, main, null, code, { setPageHead: ({ title }) => titles.push(title) });
  return { main, requests, context, navigation, titles, expires };
}
const button = (main, label) => allNodes(main).find((node) => node.tagName === "BUTTON" && node.textContent === label);
const tag = (main, name) => allNodes(main).filter((node) => node.tagName === name);

test("approval displays real facts and completes first-run progress", async () => {
    assert.equal(parseUniverseRoute("/machine-approval/k7f2").detail, "k7f2");
    const { main, requests, titles, expires } = page();
    await settle();
    assert.equal(titles.at(-1), "Approve this machine");
    assert.match(main.textContent, /My laptopmacOS · machine 4f2c9a1e-80d6-4b2c-a447-123456789abc/);
    assert.match(main.textContent, /matches the one in your terminal/);
    assert.match(main.textContent, /OrganizationExample org/);
    assert.match(main.textContent, /Match codeK7F2must match your terminalRequested byMorgan · actor #9/);
    assert.match(main.textContent, /Approving asMorgan · actor #9This machine will act as you/);
    assert.equal(main.ownerDocument.activeElement, button(main, "Approve machine"));
    assert.match(main.textContent, /in 9 minutes/);
    assert.equal(tag(main, "TIME")[0].getAttribute("datetime"), expires);
    assert.notEqual(tag(main, "TIME")[0].textContent, expires);
    assert.equal(byClass(main, "machine-approval-steps")[0].children[3].getAttribute("aria-current"), "step");
    button(main, "Approve machine").dispatchEvent(new Event("click"));
    await settle();
    assert.deepEqual(requests.find((r) => r.function === "machine_authorization.get").payload, { code: "K7F2" });
    assert.deepEqual(requests.find((r) => r.function === "machine_authorization.resolve").payload, { code: "K7F2", action: "approve" });
    assert.equal(titles.at(-1), "Machine connected");
    assert.match(main.textContent, /✓ My laptop is connected to Example org/);
    assert.equal(byClass(main, "machine-approval-next")[0].textContent, "Return to your terminal");
    assert.equal(byClass(main, "machine-approval-steps")[0].children.every((step) => step.className === "done"), true);
    assert.doesNotMatch(main.textContent, /Expires|must match|yoke connect|CLI/);
    assert.equal(button(main, "Deny"), undefined);
  });

test("later machine requests omit setup progress", async () => {
  const { main } = page({ count: 2 });
  await settle();
  assert.equal(byClass(main, "machine-approval-steps").length, 0);
  assert.ok(button(main, "Approve machine"));
});

test("missing machine names omit the whole row", async () => {
  const { main } = page({ machine: null });
  await settle();
  assert.equal(tag(main, "DT").some((node) => node.textContent === "Machine"), false);
  assert.doesNotMatch(main.textContent, /Connecting machine|machine 4f2c9a1e/);
});

test("denial authorizes nothing and removes decision controls", async () => {
  const { main, titles } = page();
  await settle();
  button(main, "Deny").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(titles.at(-1), "Connect your machine");
  assert.match(main.textContent, /Request deniedNothing was authorized/);
  assert.equal(button(main, "Approve machine"), undefined);
});

test("a transport refusal preserves retry and never reports success", async () => {
  const { main, requests } = page({ failure: { code: "authorization_store_unavailable", message: "authorization_store_unavailable: restore storage" } });
  await settle();
  const approve = button(main, "Approve machine");
  approve.dispatchEvent(new Event("click"));
  await settle();
  assert.match(main.textContent, /authorization_store_unavailable.*Retry your decision/);
  assert.doesNotMatch(main.textContent, /is connected/);
  assert.equal(approve.disabled, false);
  approve.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(requests.filter((r) => r.function === "machine_authorization.resolve").length, 2);
  assert.match(main.textContent, /is connected/);
});

test("expired facts name the local time without promising automatic renewal", async () => {
  const { main, titles, expires } = page({ expired: true });
  await settle();
  assert.equal(titles.at(-1), "Connect your machine");
  assert.match(main.textContent, /This code expired at .*Nothing was authorized/);
  assert.match(main.textContent, /Run `yoke connect` again for a new code/);
  assert.equal(button(main, "Approve machine"), undefined);
  assert.doesNotMatch(main.textContent, new RegExp(expires));
});

test("an unavailable code has named recovery without a code entry form", async () => {
  const { main } = page({ readError: { code: "authorization_unavailable" } });
  await settle();
  assert.match(main.textContent, /That code isn't availableIt may have expired or been answered/);
  assert.equal(tag(main, "INPUT").length + tag(main, "FORM").length, 0);
});

test("no URL code renders the connection heading without reads or entry controls", async () => {
  const { main, requests, titles } = page({ code: null });
  await settle();
  assert.equal(titles.at(-1), "Connect your machine");
  assert.equal(requests.length, 0);
  assert.equal(tag(main, "INPUT").length + tag(main, "FORM").length, 0);
  assert.equal(button(main, "Continue"), undefined);
});

test("shared embedded card focuses its labelled heading and reports decisions", async () => {
  let decisions = 0;
  const { main, requests } = page({ embedded: true, onDecided: () => { decisions++; } });
  await settle();
  const heading = tag(main, "H2")[0];
  assert.equal(main.ownerDocument.activeElement, heading);
  assert.equal(byClass(main, "machine-approval-card")[0].getAttribute("aria-labelledby"), heading.id);
  assert.equal(byClass(main, "machine-approval-steps").length, 0);
  button(main, "Deny").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(decisions, 1);
  assert.deepEqual(requests.at(-1).payload, { code: "K7F2", action: "deny" });
});

test("recording disables both actions and exposes a live status", async () => {
  let finish;
  const { main } = page({ waitForDecision: new Promise((resolve) => { finish = resolve; }) });
  await settle();
  button(main, "Approve machine").dispatchEvent(new Event("click"));
  assert.equal(tag(main, "BUTTON").every((node) => node.disabled), true);
  assert.equal(byClass(main, "machine-approval-status")[0].getAttribute("role"), "status");
  assert.match(main.textContent, /Recording your decision/);
  finish(); await settle();
  assert.equal(byClass(main, "machine-approval-outcome")[0].getAttribute("role"), "status");
});

test("older successful replies name the signed-in account without invented identity", async () => {
  const { main } = page({ viewer: null, requested_by: null });
  await settle();
  assert.match(main.textContent, /Approving asyour signed-in accountThis machine will act as you/);
  assert.match(main.textContent, /Ask the server operator to upgrade/);
  assert.doesNotMatch(main.textContent, /Requested by|actor #/);
  assert.ok(button(main, "Approve machine"));
});

for (const [code, expected] of [
  ["actor_disabled", /You can't approve machines here.*Sign in as an active member of Example org/],
  ["organization_membership_required", /You can't approve machines here/],
  ["authorization_human_required", /You can't approve machines here/],
  ["authorization_consumed", /This request was already answeredCheck Machines/],
  ["authorization_expired", /This code expiredNothing was authorized/],
  ["not_found", /That code isn't available/],
  ["storage_unavailable", /Restore storage.*Reload to retry/],
]) test(`read refusal ${code} keeps its distinct recovery`, async () => {
  const { main } = page({ readError: { code, message: "Restore storage" } });
  await settle();
  assert.match(main.textContent, expected);
  assert.equal(byClass(main, "machine-approval-outcome")[0].getAttribute("role"), "alert");
  assert.equal(button(main, "Approve machine"), undefined);
});

for (const code of ["actor_disabled", "organization_membership_required", "authorization_human_required"])
test(`decision refusal ${code} removes invalid actions`, async () => {
  const { main } = page({ failure: { code, message: "Sign in again" } });
  await settle(); button(main, "Approve machine").dispatchEvent(new Event("click")); await settle();
  assert.match(main.textContent, /You can't approve machines here/);
  assert.equal(button(main, "Approve machine"), undefined);
});

for (const [code, state, decision, expected] of [
  ["authorization_expired", "expired", null, /This code expired at/],
  ["authorization_consumed", "consumed", "approve", /This request was already answered/],
  ["authorization_already_decided", "denied", "deny", /Request denied/],
]) test(`decision race ${code} rereads the authoritative outcome`, async () => {
  const { main, requests } = page({ failure: { code }, afterRefusal: { state, decision } });
  await settle(); button(main, "Approve machine").dispatchEvent(new Event("click")); await settle();
  assert.equal(requests.filter((r) => r.function === "machine_authorization.get").length, 2);
  assert.match(main.textContent, expected);
  assert.equal(button(main, "Approve machine"), undefined);
});

test("a consumed approval cannot present an unconsumed success", async () => {
  const { main } = page({ state: "consumed", decision: "approve" });
  await settle();
  assert.match(main.textContent, /This request was already answered/);
  assert.doesNotMatch(main.textContent, /Return to your terminal/);
});

test("local routes with and without codes make no remote reads", async () => {
  for (const code of [null, "K7F2"]) {
    const { main, requests, titles } = page({ code, mode: "local" });
    await settle();
    assert.equal(requests.length, 0);
    assert.equal(titles.at(-1), "Connect your machine");
    assert.match(main.textContent, /Reachable here only/);
    assert.equal(button(main, "Approve machine"), undefined);
  }
});

test("local reachability sentence matches the CLI and token notice is distinct", () => {
  const source = readFileSync(new URL("../../packages/yoke-cli/src/yoke_cli/config/local_reachability.py", import.meta.url), "utf8");
  const expected = [...source.match(/LOCAL_REACHABILITY_NOTICE = \(([\s\S]*?)\n\)/)[1].matchAll(/"([^"]*)"/g)].map((part) => part[1]).join("");
  const doc = new FakeDocument();
  const full = localReachabilityNotice(doc, { variant: "full" });
  assert.equal(tag(full, "P")[0].textContent.replace("yoke self-host init", "`yoke self-host init`"), expected);
  assert.equal(tag(full, "A")[0].textContent, "Self-host guide →");
  const token = localReachabilityNotice(doc, { variant: "token" });
  assert.equal(tag(token, "P")[0].textContent, "This token works on this computer only. A token does not make this local universe reachable from another computer. To share it, set up a team server with yoke self-host init.");
});

test("registry skew codes match the Python owner and refuse unrelated errors", () => {
  const source = readFileSync(new URL("../../packages/yoke-core/src/yoke_core/domain/control_plane_function_degradation.py", import.meta.url), "utf8");
  const expected = [...source.match(/REGISTRY_SKEW_CODES = frozenset\(\{([^}]*)\}\)/)[1].matchAll(/"([^"]+)"/g)].map((part) => part[1]);
  assert.deepEqual([...REGISTRY_SKEW_CODES].sort(), expected.sort());
  for (const code of expected) assert.equal(isRegistrySkewError({ code }), true);
  for (const code of ["authorization_unavailable", "not_found", undefined]) assert.equal(isRegistrySkewError({ code }), false);
  assert.equal(isRegistrySkewError(undefined), false);
});

test("decided codes show the outcome without another approval", async () => {
  const { main } = page({ decision: "approve" });
  await settle();
  assert.equal(button(main, "Approve machine"), undefined);
  assert.match(main.textContent, /Return to your terminal/);
});

test("a detached route ignores late reads even while the application stays mounted", async () => {
  const { main, titles } = page();
  main.isConnected = false;
  await settle();
  assert.equal(titles.at(-1), "Connect your machine");
  assert.doesNotMatch(main.textContent, /My laptop|Approve machine/);
});
