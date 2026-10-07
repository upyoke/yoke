import assert from "node:assert/strict";
import test from "node:test";
import { renderQaActivity } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_activity.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });
const publicRef = (id, project = "HRB") => `${project}-${id}`;
const click = (node) => node.dispatchEvent(new Event("click"));
const caseLinks = (root) => byClass(root, "qa-activity-case").map((cell) => cell.children[0]);
const button = (root, text) => allNodes(root).find((node) => node.tagName === "BUTTON" && node.textContent === text);

function cases(count = 500) {
  const time = Date.parse("2026-10-02T12:00:00Z");
  return Array.from({ length: count }, (_, index) => ({
    requirement_id: index + 1000, public_ref: publicRef(index + 1),
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
      throw new Error(`unexpected function ${request.function}`);
    } },
  };
  return { root, document, context, controller, requests,
    itemRequests: () => requests.filter((request) => request.function === "items.detail.get") };
}

test("history immediately names canonical items and preserves focus while paging", async () => {
  const f = fixture();
  await renderQaActivity(f.context, f.root, "all");
  await settle();
  assert.equal(byClass(f.root, "qa-activity-row").length, 25);
  assert.equal(byClass(f.root, "qa-stat").length, 5);
  assert.match(byClass(f.root, "qa-history-count")[0].textContent, /1–25 of 500/);
  assert.equal(button(f.root, "Next").disabled, false);
  assert.equal(f.itemRequests().length, 0);
  assert.equal(f.requests.find((request) => request.function === "qa.activity.list").payload.limit, 500);
  const link = caseLinks(f.root)[0];
  const href = link.href;
  link.focus();
  await settle();
  assert.equal(link.textContent, `Command check · ${publicRef(1)}`);
  assert.equal(caseLinks(f.root)[0], link);
  assert.equal(f.document.activeElement, link);
  assert.equal(link.href, href);
});

test("paging names carried items from their canonical member ref", async () => {
  const rows = cases(50);
  rows[25] = { ...rows[25], public_ref: null, deployment_member_public_ref: rows[0].public_ref };
  const f = fixture(rows);
  await renderQaActivity(f.context, f.root, ["1"]);
  await settle();
  click(button(f.root, "Next"));
  await settle();
  assert.match(byClass(f.root, "qa-history-count")[0].textContent, /26–50 of 50/);
  assert.equal(caseLinks(f.root)[0].textContent, `Command check · ${publicRef(1)}`);
  click(button(f.root, "Previous"));
  await settle();
  assert.equal(caseLinks(f.root)[0].textContent, `Command check · ${publicRef(1)}`);
  assert.equal(f.itemRequests().length, 0);
  assert.match(byClass(f.root, "qa-history-count")[0].textContent, /1–25 of 50/);
});

test("an empty filter stays empty and clearing it restores canonical labels", async () => {
  const f = fixture();
  await renderQaActivity(f.context, f.root, "all");
  await settle();
  const search = allNodes(f.root).find((node) => node.getAttribute("aria-label") === "Search history");
  search.value = "no matching case";
  search.dispatchEvent(new Event("input"));
  await settle();
  assert.equal(caseLinks(f.root).length, 0);
  assert.match(byClass(f.root, "qa-history-count")[0].textContent, /No cases match/);
  click(button(f.root, "Clear filters"));
  await settle();
  assert.equal(caseLinks(f.root)[0].textContent, `Command check · ${publicRef(1)}`);
  assert.equal(f.itemRequests().length, 0);
});

for (const hasSignal of [true, false]) {
  test(`detached history cannot overwrite navigation (route signal ${hasSignal})`, async () => {
    const f = fixture();
    if (!hasSignal) delete f.context.signal;
    await renderQaActivity(f.context, f.root, "all");
    await settle();
    const oldNext = button(f.root, "Next");
    if (hasSignal) f.controller.abort();
    f.root.textContent = "Different page";
    click(oldNext);
    await settle();
    assert.equal(f.root.textContent, "Different page");
    assert.equal(f.itemRequests().length, 0);
  });
}

test("same numeric sequence in different projects keeps distinct labels", async () => {
  const rows = cases(2);
  rows[1].public_ref = publicRef(1, "ALT");
  const f = fixture(rows);
  await renderQaActivity(f.context, f.root, "all");
  await settle();
  assert.deepEqual(caseLinks(f.root).map((link) => link.textContent), [
    `Command check · ${publicRef(1)}`, `Command check · ${publicRef(1, "ALT")}`,
  ]);
  assert.equal(f.itemRequests().length, 0);
});
