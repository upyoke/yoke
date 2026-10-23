import assert from "node:assert/strict";
import test from "node:test";

import { renderTeamView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_team.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });
const nameFact = { invite_form: "name", sign_in_method: "invite_code" };
const nodes = (root, tag) => allNodes(root).filter((node) => node.tagName === tag);
const button = (root, text) => nodes(root, "BUTTON").find((node) => node.textContent === text);
const headerText = (panel) => byClass(panel, "panel-header")[0].textContent;

function person(id, name, overrides = {}) {
  return {
    id, name, kind: "human", status: "active", tokens: [],
    roles: { org: [{ org: "Acme", role: "operator" }], projects: [] },
    identity: { email: `${name.toLowerCase()}@example.test` },
    ...overrides,
  };
}

const roster = (overrides = {}) => ({
  current_actor_id: 2, can_manage_actors: true, person_org_roles: ["admin", "operator", "viewer"],
  role_descriptions: { operator: "Normal operator work." }, machine_only_roles: [], bootstrap_only_roles: [],
  rows: [person(2, "Ben"), person(3, "Ana", { status: "disabled" })],
  ...overrides,
});

async function render({ rosterResult = roster(), mode = "self-host", team } = {}) {
  const document = new FakeDocument(), main = document.createElement("main"), head = document.createElement("div");
  const data = { portability: { mode }, ...(team === undefined ? {} : { team }) };
  const context = {
    document, isMounted: () => true, capabilities: { data },
    client: { call: async (request) => (request.function === "actors.roster"
      ? ok(rosterResult) : ok({ ...nameFact, invites: [] })) },
  };
  await renderTeamView(context, main, null, null, { setPageHead: ({ actions = [] }) => head.replaceChildren(...actions) });
  await settle();
  return { main, head };
}

test("API keys show a count and the newest use behind a classed disclosure", async () => {
  const tokens = [
    { token_id: 4, name: "laptop", last_used_at: "2026-10-20T09:15:42Z", machine_id: "m-1", machine_name: "Office" },
    { token_id: 5, name: "ci", last_used_at: "2026-10-22T18:03:10Z", machine_id: "m-2", machine_name: "Studio" },
    { token_id: 6, name: "spare", last_used_at: null },
  ];
  const { main } = await render({ rosterResult: roster({ rows: [
    person(2, "Ben", { tokens }), person(4, "Cy", { tokens: [tokens[2]] }), person(5, "Di"),
  ] }) });
  const [ben, cy, di] = byClass(main, "actors-keys");
  const disclosure = nodes(ben, "DETAILS")[0];
  const summary = nodes(disclosure, "SUMMARY")[0];
  assert.equal(summary.className, "actors-keys-summary");
  assert.equal(summary.textContent, "3 keysLast used 2026-10-22 18:03 UTC · Studio");
  assert.deepEqual(byClass(disclosure, "actors-key").map((node) => node.textContent), [
    "laptop (#4) · last used 2026-10-20T09:15:42Z · machine Office",
    "ci (#5) · last used 2026-10-22T18:03:10Z · machine Studio",
    "spare (#6) · last used never",
  ]);
  assert.equal(nodes(cy, "SUMMARY")[0].textContent, "1 keyNever used");
  assert.equal(di.textContent, "No active keys");
  assert.equal(nodes(di, "DETAILS").length, 0);
});

test("Invites lead People, and Show disabled sits in the People header", async () => {
  const { main } = await render();
  const panels = byClass(main, "actors-panel");
  assert.match(headerText(panels[0]), /^Invites/);
  assert.match(headerText(panels[1]), /^People· 1Show disabled \(1\)$/);
  assert.equal(byClass(main, "actors-controls").length, 0);
  const toggle = nodes(panels[1], "INPUT")[0];
  toggle.checked = true;
  toggle.dispatchEvent(new Event("change"));
  assert.match(headerText(byClass(main, "actors-panel")[1]), /^People· 2Show disabled \(1\)$/);
});

test("local Team names the next step inside a padded notice and has no Invites", async () => {
  const { main } = await render({ mode: "local", rosterResult: roster({ rows: [person(2, "Ben")] }) });
  const notice = byClass(main, "actors-local-notice")[0];
  const body = byClass(notice, "panel-body")[0];
  assert.equal(nodes(body, "H3")[0].textContent, "Set up a team server to add people");
  assert.match(body.textContent, /yoke self-host init/);
  assert.match(body.textContent, /You are the only actor in this universe\./);
  assert.equal(byClass(main, "actors-invites").length, 0);
});

test("a host seats-left fact reaches the Invites header and the invite form", async () => {
  const { main, head } = await render({ mode: "hosted", team: { seatsLeft: 3 } });
  assert.equal(headerText(byClass(main, "actors-invites")[0]), "Invites· 0· 3 seats left");
  button(head, "Invite").dispatchEvent(new Event("click"));
  assert.match(main.textContent, /This invite uses 1 of 3 seats left\./);
  const one = await render({ mode: "hosted", team: { seatsLeft: 1 } });
  assert.equal(headerText(byClass(one.main, "actors-invites")[0]), "Invites· 0· 1 seat left");
});

test("zero seats left shows the full-seat recovery in the header and the invite form", async () => {
  const { main, head } = await render({ mode: "hosted", team: { seatsLeft: 0 } });
  assert.equal(headerText(byClass(main, "actors-invites")[0]), "Invites· 0· 0 seats left");
  button(head, "Invite").dispatchEvent(new Event("click"));
  assert.match(main.textContent, /No seats left\. Change plan in Billing, or revoke a pending invite\./);
  assert.doesNotMatch(main.textContent, /This invite uses/);
});

test("an absent or malformed seats fact draws no seats line", async () => {
  for (const team of [undefined, null, {}, { seatsLeft: null }, { seatsLeft: -1 }, { seatsLeft: 2.5 }, { seatsLeft: "4" }]) {
    const { main, head } = await render({ mode: "hosted", team });
    assert.equal(headerText(byClass(main, "actors-invites")[0]), "Invites· 0", JSON.stringify(team));
    button(head, "Invite").dispatchEvent(new Event("click"));
    assert.doesNotMatch(main.textContent, /seat/, JSON.stringify(team));
  }
});

test("a non-admin reads roles as text with no seats, Disable or Invite", async () => {
  const { main, head } = await render({ mode: "hosted", team: { seatsLeft: 3 }, rosterResult: roster({ can_manage_actors: false }) });
  const invites = byClass(main, "actors-invites")[0];
  assert.equal(headerText(invites), "Invites· 0");
  assert.match(invites.textContent, /Only org admins can invite people\./);
  assert.equal(button(head, "Invite"), undefined);
  assert.equal(button(main, "Disable"), undefined);
  assert.equal(nodes(main, "SELECT").length, 0);
  assert.doesNotMatch(main.textContent, /seat/);
});
