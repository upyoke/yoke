import assert from "node:assert/strict";
import test from "node:test";

import { renderSessionsView, sessionCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import { sessionRosterFilters } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_roster_filters.js";
import { renderRegisteredSessionDetail, sessionScopeLabel } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_detail.js";
import { exactSessionAudience, openSessionMessageCompose } from "../../packages/yoke-core/src/yoke_core/ui/static/session_message_compose_dialog.js";
import { renderSessionMessagesView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_messages.js";
import { sessionControlCall, SessionControlFailure } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_control_data.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";

const orgRow = {
  session_id: "org-owner", project_id: null, org_id: 7, scope_kind: "org",
  project: null, liveness: "active", executor: "codex", claims: [],
};
const projectRow = {
  ...orgRow, session_id: "project-owner", project_id: 1, org_id: null,
  scope_kind: "project", project: "yoke",
};
const ok = (result) => ({ status: 200, envelope: { success: true, result } });
const denied = () => ({
  status: 403, envelope: { success: false, error: { code: "permission_denied" } },
});
const change = (control, value) => {
  control.value = value;
  control.dispatchEvent(new Event("change"));
};
const cardIds = (main) => byClass(main, "session-card")
  .map((node) => node.getAttribute("data-session-id"));
const button = (main, text) => allNodes(main)
  .find((node) => node.tagName === "BUTTON" && node.textContent === text);
function setup(respond) {
  const document = new FakeDocument();
  const main = document.createElement("main");
  const requests = [];
  const context = {
    document, projects: () => [{ id: 1, slug: "yoke" }], isMounted: () => true,
    steeringGroupColors: () => new Map(), refreshSteeringGroupColors: async () => {},
    client: { async call(request) { requests.push(request); return respond(request); } },
  };
  return { context, main, requests };
}

test("a real org-scoped card labels its scope instead of omitting it", () => {
  const card = sessionCard(new FakeDocument(), orgRow, () => {});
  assert.equal(byClass(card, "session-scope")[0]?.textContent, "Outside any project");
});

test("the project facet offers outside-project sessions separately", () => {
  const filters = sessionRosterFilters(new FakeDocument(), () => {});
  filters.setFacets({ projects: [{ id: 1, slug: "yoke" }] });
  const project = byClass(filters.host, "session-filter-control")[2];
  assert.ok(project.children.some((option) => option.textContent === "Outside any project"));
  const outside = project.children.find((option) => option.textContent === "Outside any project").value;
  change(project, outside);
  assert.deepEqual(filters.apply([orgRow, projectRow, { project_id: null }]), [orgRow]);
  assert.deepEqual(filters.historyCriteria(["1"]).projects, ["1"]);
  assert.ok(filters.summary().includes("Project: Outside any project"));
  change(project, "1");
  assert.deepEqual(filters.apply([orgRow, projectRow]), [projectRow]);
});

test("scope labels preserve projects, missing metadata and text escaping", () => {
  assert.equal(sessionScopeLabel(projectRow), "yoke");
  assert.equal(sessionScopeLabel({ project: "older-project" }), "older-project");
  assert.equal(sessionScopeLabel({ project_id: null }), "—");
  const card = sessionCard(new FakeDocument(), { ...projectRow, project: "<b>name</b>" }, () => {});
  const label = byClass(card, "session-scope")[0];
  assert.equal(label.textContent, "<b>name</b>");
  assert.equal(label.innerHTML, "");
});

test("actual detail loads org and project cards without expanding explicit scope", async () => {
  for (const [row, scope] of [[orgRow, "all"], [projectRow, "all"], [orgRow, ["1"]]]) {
    const { context, main, requests } = setup((request) => {
      if (request.function === "events.query.run") return ok({ rows: [] });
      assert.equal(request.function, "sessions.list");
      return ok({ rows: request.payload.project && row.project_id == null ? [] : [row] });
    });
    renderRegisteredSessionDetail(context, main, scope, row.session_id);
    await settle();
    if (scope === "all") {
      assert.deepEqual(cardIds(main), [row.session_id]);
      assert.equal(byClass(main, "session-scope")[0].textContent, sessionScopeLabel(row));
    } else {
      assert.deepEqual(cardIds(main), []);
      assert.equal(requests[0].payload.project, "1");
    }
  }
  const { context, main } = setup(() => denied());
  renderRegisteredSessionDetail(context, main, "all", "unavailable-session");
  await settle();
  assert.deepEqual(cardIds(main), []);
  assert.match(main.textContent, /permission/i);
  assert.ok(!main.textContent.includes(orgRow.session_id));
});

test("outside facet filters active, ended and all while paging honest loaded counts", async () => {
  const endedOrg = { ...orgRow, session_id: "org-ended", liveness: "ended" };
  const endedProject = { ...projectRow, session_id: "project-ended", liveness: "ended" };
  const { context, main, requests } = setup((request) => {
    assert.equal(request.function, "sessions.list");
    if (request.payload.usage_last_24h) return ok({ rows: [] });
    if (request.payload.history) {
      const history = request.payload.history;
      assert.deepEqual(history.projects, []);
      return ok({
        rows: history.cursor ? [endedOrg] : [endedProject],
        matched_count: 99, next_cursor: history.cursor ? null : "next-page",
        facets: { projects: [{ id: 1, slug: "yoke" }] },
      });
    }
    return ok({ rows: [orgRow, projectRow] });
  });
  renderSessionsView(context, main, "all");
  await settle();
  const controls = byClass(main, "session-filter-control");
  const outside = controls[2].children.find((option) => option.textContent === "Outside any project").value;
  change(controls[2], outside);
  assert.deepEqual(cardIds(main), [orgRow.session_id]);
  change(controls[1], "ended");
  await settle();
  assert.deepEqual(cardIds(main), []);
  assert.match(main.textContent, /loaded history.*Load more to continue/);
  assert.equal(byClass(main, "n")[0].textContent, "0");
  assert.equal(button(main, "Load more").hidden, false);
  button(main, "Load more").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(cardIds(main), [endedOrg.session_id]);
  assert.equal(byClass(main, "n")[0].textContent, "1");
  change(controls[1], "");
  assert.deepEqual(new Set(cardIds(main)), new Set([orgRow.session_id, endedOrg.session_id]));
  assert.equal(byClass(main, "n")[0].textContent, "2");
  assert.ok(requests.filter((r) => r.payload.history).every((r) => !r.payload.history.projects.includes(outside)));
});

test("outside history never widens an outer project and normal counts stay server-owned", async () => {
  const ended = { ...projectRow, liveness: "ended" };
  const { context, main, requests } = setup((request) => {
    if (request.payload.usage_last_24h) return ok({ rows: [] });
    if (request.payload.history) return ok({ rows: [ended], matched_count: 72, next_cursor: null });
    return ok({ rows: [projectRow] });
  });
  renderSessionsView(context, main, ["1"]);
  await settle();
  const controls = byClass(main, "session-filter-control");
  change(controls[1], "ended");
  await settle();
  assert.equal(byClass(main, "n")[0].textContent, "1 of 72");
  const outside = controls[2].children.find((option) => option.textContent === "Outside any project").value;
  change(controls[2], outside);
  await settle();
  assert.deepEqual(cardIds(main), []);
  assert.deepEqual(requests.filter((r) => r.payload.history).at(-1).payload.history.projects, ["1"]);
});

for (const recipient of [orgRow, projectRow]) {
  test(`compose keeps exact authorized ${recipient.scope_kind} audience and confirmation`, async () => {
    const { context, main, requests } = setup((request) => {
      assert.deepEqual(request.payload.selector, { session_ids: [recipient.session_id] });
      if (request.function === "session_control.message.preview") {
        return ok({ recipients: [recipient], confirmation_token: "confirmed-audience" });
      }
      assert.equal(request.function, "session_control.message.send");
      assert.equal(request.payload.confirmation_token, "confirmed-audience");
      return ok({ message_id: "sent" });
    });
    openSessionMessageCompose(context, main, { audience: exactSessionAudience([recipient]) });
    await settle();
    assert.match(main.textContent, new RegExp(sessionScopeLabel(recipient)));
    const body = byClass(main, "session-message-body")[0];
    body.value = "A normal message";
    body.dispatchEvent(new Event("input"));
    assert.equal(button(main, "Send message").disabled, false);
    button(main, "Send message").dispatchEvent(new Event("click"));
    await settle();
    assert.equal(requests.length, 2);
  });
}

test("a denied recipient preview offers no hidden recipient or send action", async () => {
  const { context, main, requests } = setup(() => denied());
  openSessionMessageCompose(context, main, { audience: exactSessionAudience([orgRow]) });
  await settle();
  assert.equal(byClass(main, "session-message-preview-list").length, 0);
  assert.equal(button(main, "Send message").disabled, true);
  assert.match(main.textContent, /permission/i);
  assert.deepEqual(requests[0].payload.selector.session_ids, [orgRow.session_id]);
});

test("nullable message recipients and typed controls need no project identity", async () => {
  const message = {
    message_id: "org-message", body: "A normal message", needs_attention: false,
    recipients: [{ ...orgRow, state: "acknowledged" }],
  };
  const { context, main } = setup((request) => {
    if (request.function === "session_control.message.get") return ok({ message });
    assert.equal(request.function, "session_control.message.list");
    assert.equal(Object.hasOwn(request.payload, "projects"), false);
    return ok({ messages: [message], settled_matched_count: 1 });
  });
  renderSessionMessagesView(context, main, "all");
  await settle();
  button(main, "Details").dispatchEvent(new Event("click"));
  await settle();
  const recipient = byClass(main, "session-message-party")
    .find((node) => node.getAttribute("data-tooltip") === "Session org-owner");
  assert.equal(recipient.textContent, "codex");
  assert.equal(byClass(main, "error").length, 0);
  assert.equal((await sessionControlCall(context, "session_control.message.get", {})).message.recipients[0].project_id, null);
  const refused = setup(() => denied());
  await assert.rejects(sessionControlCall(refused.context, "session_control.message.get", {}), SessionControlFailure);
});
