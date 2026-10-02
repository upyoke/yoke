import assert from "node:assert/strict";
import test from "node:test";
import { renderQaActivity } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_activity.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });
const publicRef = (id, project = "HRB") => `${project}-${id}`;
const detail = (id, project) => ok({ item: { public_ref: publicRef(id, project) } });
const click = (node) => node.dispatchEvent(new Event("click"));
const caseLinks = (root) => byClass(root, "qa-activity-case").map((cell) => cell.children[0]);
const button = (root, text) => allNodes(root).find((node) => node.tagName === "BUTTON" && node.textContent === text);

function cases(count = 500) {
  const time = Date.parse("2026-10-02T12:00:00Z");
  return Array.from({ length: count }, (_, index) => ({
    requirement_id: index + 1000, item_id: index + 1,
    plan_id: null, project: "harbour", case_key: `check-${index + 1}`,
    method_id: "command", method_name: "Command", outcome: "passed",
    evidence_count: 0, artifacts: [],
    happened_at: new Date(time - index * 60_000).toISOString(),
  }));
}

function fixture(rows = cases()) {
  const document = new FakeDocument();
  const root = document.createElement("main");
  const requests = [];
  const pending = new Map();
  const controller = new AbortController();
  const context = {
    document, signal: controller.signal, isMounted: () => true,
    projects: () => [{ id: 1, slug: "harbour", name: "Harbour" }],
    client: { call(request) {
      requests.push(request);
      if (request.function === "qa.activity.list") return Promise.resolve(ok({
        rows, summary: { total: rows.length, counts: { passed: rows.length } },
      }));
      if (request.function === "inbox.list") return Promise.resolve(ok({ needs_decision: [] }));
      assert.equal(request.function, "items.detail.get");
      const itemId = request.target.item_id;
      return new Promise((resolve, reject) => { pending.set(itemId, { resolve, reject }); });
    } },
  };
  return { root, document, context, controller, requests, pending,
    itemRequests: () => requests.filter((request) => request.function === "items.detail.get") };
}

test("history paints before optional names and requests only the visible page", async () => {
  const f = fixture();
  let completed = false;
  const rendering = renderQaActivity(f.context, f.root, "all").then(() => { completed = true; });
  await settle();
  assert.equal(completed, true, "render must finish while item reads are still pending");
  await rendering;
  assert.equal(byClass(f.root, "qa-activity-row").length, 25);
  assert.equal(byClass(f.root, "qa-stat").length, 5);
  assert.match(byClass(f.root, "qa-history-count")[0].textContent, /1–25 of 500/);
  assert.equal(button(f.root, "Next").disabled, false);
  assert.equal(f.itemRequests().length, 25);
  assert.deepEqual(f.itemRequests().map((request) => request.target.item_id),
    Array.from({ length: 25 }, (_, index) => index + 1));
  assert.equal(f.requests.find((request) => request.function === "qa.activity.list").payload.limit, 500);

  const link = caseLinks(f.root)[0];
  const table = byClass(f.root, "qa-activity-table")[0];
  const evidence = byClass(f.root, "qa-activity-evidence")[0];
  const href = link.href;
  link.focus();
  assert.equal(link.textContent, "Command check · item 1");
  f.pending.get(1).resolve(detail(1));
  await settle();
  assert.equal(link.textContent, `Command check · ${publicRef(1)}`);
  assert.equal(caseLinks(f.root)[0], link);
  assert.equal(f.document.activeElement, link);
  assert.equal(link.href, href);
  assert.equal(byClass(f.root, "qa-activity-table")[0], table);
  assert.equal(byClass(f.root, "qa-activity-evidence")[0], evidence);
  assert.equal(f.itemRequests().length, 25);
});

test("paging deduplicates pending and completed names including carried items", async () => {
  const rows = cases(50);
  rows[25] = { ...rows[25], item_id: null, deployment_member_item_id: rows[0].item_id };
  const f = fixture(rows);
  await renderQaActivity(f.context, f.root, ["1"]);
  await settle();
  const previousLink = caseLinks(f.root)[0];
  click(button(f.root, "Next"));
  await settle();
  const currentLink = caseLinks(f.root)[0];
  assert.match(byClass(f.root, "qa-history-count")[0].textContent, /26–50 of 50/);
  assert.equal(f.itemRequests().length, 49);
  assert.equal(f.itemRequests().filter((request) => request.target.item_id === 1).length, 1);
  f.pending.get(1).resolve(detail(1));
  await settle();
  assert.equal(previousLink.textContent, "Command check · item 1");
  assert.equal(currentLink.textContent, `Command check · ${publicRef(1)}`);
  assert.equal(caseLinks(f.root)[0], currentLink);
  click(button(f.root, "Previous"));
  await settle();
  assert.equal(caseLinks(f.root)[0].textContent, `Command check · ${publicRef(1)}`);
  assert.equal(f.itemRequests().length, 49);
  assert.match(byClass(f.root, "qa-history-count")[0].textContent, /1–25 of 50/);
});

test("late names cannot revive an empty filter and are reused after clearing it", async () => {
  const f = fixture();
  await renderQaActivity(f.context, f.root, "all");
  await settle();
  const oldLink = caseLinks(f.root)[0];
  const search = allNodes(f.root).find((node) => node.getAttribute("aria-label") === "Search history");
  search.value = "no matching case";
  search.dispatchEvent(new Event("input"));
  assert.equal(caseLinks(f.root).length, 0);
  f.pending.get(1).resolve(detail(1));
  await settle();
  assert.equal(caseLinks(f.root).length, 0);
  assert.match(byClass(f.root, "qa-history-count")[0].textContent, /No cases match/);
  assert.equal(oldLink.textContent, "Command check · item 1");
  click(button(f.root, "Clear filters"));
  await settle();
  assert.equal(caseLinks(f.root)[0].textContent, `Command check · ${publicRef(1)}`);
  assert.equal(f.itemRequests().length, 25);
});

test("navigation ignores delayed labels even when the shared app stays mounted", async () => {
  const f = fixture();
  await renderQaActivity(f.context, f.root, "all");
  await settle();
  const oldLink = caseLinks(f.root)[0];
  const oldNext = button(f.root, "Next");
  f.controller.abort();
  f.context.signal = new AbortController().signal;
  f.root.textContent = "Different page";
  click(oldNext);
  f.pending.get(1).resolve(detail(1));
  await settle();
  assert.equal(f.root.textContent, "Different page");
  assert.equal(oldLink.textContent, "Command check · item 1");
  assert.equal(f.itemRequests().length, 25);
});

test("detached history also ignores late labels without a route signal", async () => {
  const f = fixture();
  delete f.context.signal;
  await renderQaActivity(f.context, f.root, "all");
  await settle();
  const oldLink = caseLinks(f.root)[0];
  const oldNext = button(f.root, "Next");
  f.root.textContent = "Different page";
  click(oldNext);
  f.pending.get(1).resolve(detail(1));
  await settle();
  assert.equal(f.root.textContent, "Different page");
  assert.equal(oldLink.textContent, "Command check · item 1");
  assert.equal(f.itemRequests().length, 25);
});

test("failed and hanging labels leave rows usable while other names update", async () => {
  const f = fixture(cases(3));
  await renderQaActivity(f.context, f.root, "all");
  await settle();
  f.pending.get(1).reject(new Error("network unavailable"));
  f.pending.get(2).resolve(detail(2));
  await settle();
  assert.deepEqual(caseLinks(f.root).map((link) => link.textContent), [
    "Command check · item 1", `Command check · ${publicRef(2)}`, "Command check · item 3",
  ]);
  assert.equal(byClass(f.root, "qa-activity-row").length, 3);
  click(button(f.root, "Clear filters"));
  await settle();
  assert.equal(f.itemRequests().length, 3);
});

test("reference caches belong to one mounted history and skip already named rows", async () => {
  const rows = cases(2);
  rows[1].item_ref = publicRef(2);
  const first = fixture(rows);
  await renderQaActivity(first.context, first.root, "all");
  await settle();
  assert.equal(first.itemRequests().length, 1);
  first.pending.get(1).resolve(detail(1));
  await settle();
  const second = fixture(rows);
  await renderQaActivity(second.context, second.root, "all");
  await settle();
  assert.equal(caseLinks(second.root)[0].textContent, "Command check · item 1");
  assert.equal(second.itemRequests().length, 1);
  second.pending.get(1).resolve(detail(1, "ALT"));
  await settle();
  assert.equal(caseLinks(second.root)[0].textContent, `Command check · ${publicRef(1, "ALT")}`);
  assert.equal(caseLinks(first.root)[0].textContent, `Command check · ${publicRef(1)}`);
});
