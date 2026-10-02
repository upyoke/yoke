import assert from "node:assert/strict";
import test from "node:test";
import { machineAccessCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machine_access.js";
import { FakeDocument, allNodes, byClass, settle, visibleText } from "./universe_ui_dom_test_support.mjs";

const ok = (result = {}) => ({ status: 200, envelope: { success: true, result } });
const denied = { status: 503, envelope: { success: false, error: { message: "Temporarily unavailable" } } };
function fixture({ mode = "owner_only", actorIds = [], directoryFails = false, failWrite = 0 } = {}) {
  const document = new FakeDocument();
  const requests = [];
  let attempts = 0;
  let reads = 0;
  let reloads = 0;
  const card = machineAccessCard({
    document, isMounted: () => true,
    projects: () => [{ id: 4, name: "Design", slug: "design" }],
    client: { async call(request) {
      requests.push(request);
      if (request.function === "actors.roster") {
        if (directoryFails && ++reads === 1) return denied;
        return ok({ rows: [{ id: 7, name: "Avery" }, { id: 8, name: "Jordan" }] });
      }
      if (++attempts === failWrite) return denied;
      return ok();
    } },
  }, { machine: { machine_id: "machine-a", access: { use: { mode, actor_ids: actorIds } } } }, () => { reloads += 1; });
  return { card, requests, reloads: () => reloads };
}
const find = (root, tag, text) => allNodes(root).find((node) => node.tagName === tag && (!text || node.textContent === text));
function setMode(card, mode) {
  const select = byClass(card, "machine-access-select")[0];
  select.value = mode;
  select.dispatchEvent(new Event("change"));
}

test("machine access shows only relevant labeled fields and resolves names to actor IDs", async () => {
  const { card, requests, reloads } = fixture();
  assert.equal(byClass(card, "machine-access-actors")[0].hidden, true);
  setMode(card, "actors");
  await settle();
  assert.match(visibleText(card), /Avery/);
  assert.match(visibleText(card), /Jordan/);
  const actor = allNodes(card).find((node) => node.tagName === "INPUT" && node.value === "8");
  actor.checked = true;
  actor.dispatchEvent(new Event("change"));
  find(card, "BUTTON", "Save access").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(requests.filter((request) => request.function === "machine.settings.set").map((request) => request.payload), [
    { machine_id: "machine-a", path: "use.actor_ids", value: [8] },
    { machine_id: "machine-a", path: "use.mode", value: "actors" },
  ]);
  assert.equal(reloads(), 1);
});

test("machine access validates the complete project-role choice before writing", async () => {
  const { card, requests } = fixture();
  setMode(card, "project_role");
  const save = find(card, "BUTTON", "Save access");
  save.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(requests.length, 0);
  assert.match(card.textContent, /Choose an available project/);
  const project = allNodes(card).find((node) => node.tagName === "SELECT" && node.className === "machine-access-input");
  project.value = "4";
  find(card, "INPUT").value = "admin";
  save.dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(requests.map((request) => [request.payload.path, request.payload.value]), [
    ["use.project_id", 4], ["use.role", "admin"], ["use.mode", "project_role"],
  ]);
});

test("directory failures retry without resetting mode or current actor selections", async () => {
  const { card, requests } = fixture({ mode: "actors", actorIds: [7], directoryFails: true });
  await settle();
  const save = find(card, "BUTTON", "Save access");
  assert.equal(save.disabled, true);
  find(card, "BUTTON", "Try again").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(save.disabled, false);
  assert.equal(allNodes(card).find((node) => node.tagName === "INPUT" && node.value === "7").checked, true);
  assert.equal(requests.length, 2);
});

test("partial save failure retains selections and exposes the partial result", async () => {
  const { card, reloads } = fixture({ mode: "actors", actorIds: [7], failWrite: 2 });
  await settle();
  const save = find(card, "BUTTON", "Save access");
  save.dispatchEvent(new Event("click"));
  assert.equal(save.disabled, true);
  await settle();
  assert.equal(save.disabled, false);
  assert.match(card.textContent, /Some settings were saved/);
  assert.equal(reloads(), 0);
  assert.equal(allNodes(card).find((node) => node.tagName === "INPUT" && node.value === "7").checked, true);
  save.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(reloads(), 1);
});
