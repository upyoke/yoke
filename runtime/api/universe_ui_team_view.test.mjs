import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { renderTeamView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_team.js";
import {
  FakeDocument, allNodes, byClass, settle,
} from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });

const roster = {
  current_actor_id: 2,
  role_descriptions: { deployment_ci: "Release tags and deploys." },
  machine_only_roles: ["deployment_ci"],
  bootstrap_only_roles: [],
  rows: [
    {
      id: 2, name: "Ben", kind: "human",
      roles: {
        org: [{ org: "Acme", role: "admin" }],
        projects: [{ project: "yoke", role: "owner" }],
      },
      identity: { email: "ben@example.test" },
    },
    {
      id: 7, name: "deploy-ci", kind: "system",
      roles: {
        org: [], projects: [{ project: "yoke", role: "deployment_ci" }],
      },
      identity: null,
    },
  ],
};

function client(answer) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return ok({ name: "Local", slug: "local" });
      }
      if (request.function === "projects.list") return ok({ rows: [] });
      if (request.function === "actors.roster") return answer();
      if (request.function === "teammate_invites.list") return ok({ invite_form: "code", invites: [] });
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountTeam(answer, mode = "local") {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/team";
  const root = documentNode.createElement("div");
  const reads = client(answer);
  const mounted = mountUniverseApp(root, {
    client: reads,
    capabilities: { data: { portability: { mode } } },
  });
  await settle();
  await settle();
  return { root, reads, mounted };
}

// Header labels without the active sort arrow.
function headings(root) {
  return allNodes(root).filter((node) => node.tagName === "TH")
    .map((node) => node.textContent.replace(/ [↑↓]$/, ""));
}

const panelTitles = (root) => byClass(root, "actors-panel")
  .map((panel) => byClass(panel, "panel-header")[0].textContent);

test("Team route groups people and machine accounts with readable grants", async () => {
  const { root, reads, mounted } = await mountTeam(() => ok(roster), "hosted");
  assert.deepEqual(byClass(root, "page-head").map((node) => node.textContent), ["Team"]);
  assert.deepEqual(panelTitles(root), ["People· 1", "Machine accounts· 1", "Invites· 0"]);
  const [people, machines] = byClass(root, "actors-panel");
  assert.deepEqual(headings(people), [
    "Actor", "State", "Org role", "Project access", "Member email", "API keys", "Action",
  ]);
  assert.deepEqual(headings(machines), ["Actor", "State", "Grants", "API keys"]);
  assert.deepEqual(byClass(root, "actors-name").map((node) => node.textContent), [
    "Ben (you)", "deploy-ci",
  ]);
  assert.deepEqual(byClass(people, "actors-access").map((node) => node.textContent), [
    "All projects · from org admin", "yoke · owner",
  ]);
  assert.ok(people.textContent.includes("ben@example.test"));
  assert.deepEqual(byClass(machines, "actors-grant").map((node) => node.textContent), [
    "Project · yokedeployment_cimachine-onlyRelease tags and deploys.",
  ]);
  assert.deepEqual(reads.requests.filter((request) => request.function === "actors.roster")
    .map((request) => request.payload), [{}]);
  const text = root.textContent;
  for (const removed of [
    "Grant access", "engine roles · two scopes", "Accounts come from Members.",
    "Team · 4", "deployment_ci · yoke", "Account",
    "Everyone and everything that can act in this universe",
  ]) assert.ok(!text.includes(removed), removed);
  mounted.unmount();
});

test("local roster omits Member email and names a sole human actor", async () => {
  const onlyHuman = { ...roster, rows: [roster.rows[0]] };
  const { root, mounted } = await mountTeam(() => ok(onlyHuman));
  assert.deepEqual(panelTitles(root), ["People· 1"]);
  assert.deepEqual(headings(byClass(root, "actors-panel")[0]), [
    "Actor", "State", "Org role", "Project access", "API keys", "Action",
  ]);
  const notice = byClass(root, "actors-local-notice")[0];
  assert.equal(notice.hidden, false);
  assert.match(notice.textContent, /Reachable here only/);
  assert.match(notice.textContent, /You are the only actor in this universe\./);
  mounted.unmount();
});

test("the actual app exposes Invite and restores its head focus on Escape", async () => {
  const { root, mounted } = await mountTeam(() => ok(adminRoster), "hosted");
  const invite = button(root, "Invite");
  await click(invite);
  assert.equal(invite.disabled, true);
  nodes(root, "FORM")[0].dispatchEvent(Object.assign(new Event("keydown"), { key: "Escape" }));
  assert.equal(invite.disabled, false);
  assert.equal(root.ownerDocument.activeElement, invite);
  mounted.unmount();
});

const nodes = (root, tag) => allNodes(root).filter((node) => node.tagName === tag);
const button = (root, text) => nodes(root, "BUTTON").find((node) => node.textContent === text);
const click = async (node) => { assert.ok(node); node.dispatchEvent(new Event("click")); await settle(); };
const adminRoster = { ...roster, can_manage_actors: true, person_org_roles: ["admin", "operator", "viewer"],
  rows: [...roster.rows, { id: 8, name: "Disabled", kind: "human", status: "disabled", roles: { org: [] } }] };
const inviteRow = { invite_id: 1, actor_id: 9, name: "Ana", kind: "code", role: "operator", state: "pending",
  created_at: "2026-10-17T10:00:00Z", expires_at: "2026-10-18T10:00:00Z", invited_by_name: "Ben" };
async function direct(call, mode = "self-host") {
  const document = new FakeDocument(), main = document.createElement("main"), head = document.createElement("div");
  const requests = [];
  const context = { document, isMounted: () => true, capabilities: { data: { portability: { mode } } },
    client: { call: async (request) => { requests.push(request); return call(request); } } };
  const pending = renderTeamView(context, main, null, null, { setPageHead: ({ actions = [] }) => head.replaceChildren(...actions) });
  await settle();
  return { document, main, head, requests, pending };
}

test("both registry-skew refusals and OIDC failure hide Invite but retain the usable roster", async () => {
  for (const code of ["function_not_registered", "function_version_skew", "oidc_misconfigured", "read_failed"]) {
    const message = code === "oidc_misconfigured" ? "Sign-in is not ready; ask the server operator to correct company sign-in settings" : "Read refused";
    const f = await direct((request) => request.function === "actors.roster" ? ok(adminRoster)
      : { status: 503, envelope: { success: false, error: { code, message } } });
    assert.equal(button(f.head, "Invite"), undefined);
    assert.match(f.main.textContent, /Ben/);
    assert.ok(nodes(f.main, "SELECT").length);
    const text = byClass(f.main, "actors-invites")[0].textContent;
    if (code.startsWith("function_")) assert.match(text, /Invites need a newer Yoke server\. Ask the server operator to upgrade, then reload\./);
    else { assert.ok(text.includes(message)); assert.match(text, /Invites could not be read/); assert.ok(button(f.main, "Try again")); assert.doesNotMatch(text, /newer Yoke server/); }
  }
});

test("nonadmins get read-only invites or the permission line alone; older roles prevent Invite", async () => {
  for (const denied of [false, true]) {
    const f = await direct((request) => request.function === "actors.roster" ? ok({ ...adminRoster, can_manage_actors: false })
      : denied ? { status: 403, envelope: { success: false } } : ok({ invite_form: "code", invites: [inviteRow] }));
    const panel = byClass(f.main, "actors-invites")[0];
    assert.match(panel.textContent, /Only org admins can invite people\./);
    assert.equal(nodes(panel, "BUTTON").length, 0);
    assert.equal(button(f.head, "Invite"), undefined);
    if (denied) assert.equal(byClass(panel, "panel-body")[0].textContent, "Only org admins can invite people.");
  }
  const f = await direct((request) => request.function === "actors.roster" ? ok({ ...adminRoster, person_org_roles: undefined }) : ok({ invite_form: "code", invites: [inviteRow] }));
  assert.equal(nodes(f.main, "SELECT").length, 0);
  assert.equal(button(f.head, "Invite"), undefined);
  assert.match(f.main.textContent, /Invite roles are unavailable/);
});

test("local mode shows reachability for multiple actors and never reads invites", async () => {
  const f = await direct(() => ok(adminRoster), "local");
  assert.match(byClass(f.main, "actors-local-notice")[0].textContent, /Reachable here only/);
  assert.equal(byClass(f.main, "actors-invites").length, 0);
  assert.equal(button(f.head, "Invite"), undefined);
  assert.deepEqual(f.requests.map((request) => request.function), ["actors.roster"]);
});

test("roster and invite reads start together; a pending invite read does not hide the roster", async () => {
  let release;
  const f = await direct((request) => request.function === "actors.roster" ? ok(adminRoster) : new Promise((resolve) => { release = resolve; }));
  assert.deepEqual(f.requests.map((request) => request.function), ["actors.roster", "teammate_invites.list"]);
  assert.match(f.main.textContent, /Ben/);
  assert.match(f.main.textContent, /Loading invites/);
  release(ok({ invite_form: "code", invites: [] }));
  await f.pending;
  assert.ok(button(f.head, "Invite"));
});

test("code create/reissue/revoke reread both lists, preserve toggles and hold the code until Done", async () => {
  let added = false, state = "pending", serial = 0;
  const used = { ...inviteRow, invite_id: 2, state: "consumed", name: "Joined" };
  const f = await direct((request) => {
    if (request.function === "actors.roster") return ok({ ...adminRoster, rows: [...adminRoster.rows, ...(added ? [{ id: 9, name: "Ana", kind: "human", status: "active", roles: { org: [] } }] : [])] });
    if (request.function === "teammate_invites.list") return ok({ invite_form: "code", invites: [used, ...(added ? [{ ...inviteRow, state }] : [])] });
    if (request.function === "teammate_invites.revoke") { state = "revoked"; return ok({ invite: { ...inviteRow, state } }); }
    added = true; state = "pending";
    return ok({ invite: inviteRow, code: `private-code-${++serial}`, expires_at: inviteRow.expires_at });
  });
  for (const toggle of nodes(f.main, "INPUT")) { toggle.checked = true; toggle.dispatchEvent(new Event("change")); }
  await click(button(f.head, "Invite"));
  assert.equal(button(f.head, "Invite").disabled, true);
  const input = nodes(byClass(f.main, "actors-invite-slot")[0], "INPUT")[0];
  input.value = "Ana";
  nodes(f.main, "FORM")[0].dispatchEvent(new Event("submit"));
  await settle();
  assert.equal(byClass(f.main, "profile-token-value")[0].textContent, "private-code-1");
  assert.ok(nodes(f.main, "INPUT").every((node) => node.checked));
  assert.equal(byClass(f.main, "actors-name").filter((node) => node.textContent === "Ana").length, 1);
  assert.match(byClass(f.main, "actors-invites")[0].textContent, /pending/);
  await click(button(f.main, "Reissue")); await click(button(f.main, "Reissue invite"));
  assert.equal(byClass(f.main, "profile-token-value")[0].textContent, "private-code-2");
  assert.equal(byClass(f.main, "actors-name").filter((node) => node.textContent === "Ana").length, 1);
  await click(button(f.main, "Revoke…")); await click(button(f.main, "Revoke invite"));
  assert.match(byClass(f.main, "actors-invites")[0].textContent, /revoked/);
  assert.equal(byClass(f.main, "profile-token-value")[0].textContent, "private-code-2");
  await click(button(f.main, "Done"));
  assert.equal(byClass(f.main, "profile-token-value").length, 0);
  assert.equal(f.document.activeElement, button(f.head, "Invite"));
  const reads = (id) => f.requests.filter((request) => request.function === id).length;
  assert.equal(reads("actors.roster"), 5); assert.equal(reads("teammate_invites.list"), 5);
});

test("email fact merges identity rows and returns its nested result without a code reveal", async () => {
  let sent = false;
  const f = await direct((request) => {
    if (request.function === "actors.roster") return ok(adminRoster);
    if (request.function === "teammate_invites.list") return ok({ invite_form: "email", sign_in_method: "oidc", invites: [inviteRow] });
    if (request.function === "identity.invite.list") return ok({ invites: sent ? [{ invite_id: 8, email: "a@example.test", role: "viewer", status: "pending", created_at: inviteRow.created_at, invited_by_user_id: 2, invited_by_name: "Hosted inviter" }] : [] });
    assert.equal(request.function, "identity.invite.create"); sent = true;
    return ok({ invite: { email: "a@example.test" } });
  }, "hosted");
  await click(button(f.head, "Invite"));
  assert.match(f.main.textContent, /company sign-in/);
  nodes(byClass(f.main, "actors-invite-slot")[0], "INPUT")[0].value = "a@example.test";
  nodes(f.main, "FORM")[0].dispatchEvent(new Event("submit")); await settle();
  assert.match(f.main.textContent, /Invite sent to a@example.test/);
  assert.match(f.main.textContent, /Hosted inviter/);
  assert.equal(byClass(f.main, "profile-token-reveal").length, 0);
  assert.equal(f.requests.filter((request) => request.function === "identity.invite.list").length, 2);
});

test("actor role and enable actions reload invites and preserve visibility choices", async () => {
  const f = await direct((request) => request.function === "actors.roster" ? ok(adminRoster)
    : request.function === "teammate_invites.list" ? ok({ invite_form: "code", invites: [{ ...inviteRow, state: "consumed" }] }) : ok({}));
  for (const toggle of nodes(f.main, "INPUT")) { toggle.checked = true; toggle.dispatchEvent(new Event("change")); }
  await click(button(f.main, "Enable"));
  const role = nodes(f.main, "SELECT")[0]; role.value = "viewer"; role.dispatchEvent(new Event("change")); await settle();
  for (const id of ["actors.roster", "teammate_invites.list"]) assert.equal(f.requests.filter((request) => request.function === id).length, 3);
  assert.ok(nodes(f.main, "INPUT").every((node) => node.checked));
  assert.ok(f.requests.some((request) => request.function === "actors.state.set"));
  assert.ok(f.requests.some((request) => request.function === "actors.role.set"));
});

test("empty, loading and refused reads retain a meaningful Team screen", async () => {
  const empty = await mountTeam(() => ok({ rows: [], current_actor_id: null }));
  assert.equal(byClass(empty.root, "actors-panel").length, 0);
  assert.ok(empty.root.textContent.includes("No actors are registered"));
  empty.mounted.unmount();

  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/team";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, {
    client: client(() => pending),
  });
  await settle();
  assert.ok(root.textContent.includes("Loading team…"));
  release(ok(roster));
  await settle();
  mounted.unmount();

  const failed = await mountTeam(() => ({
    status: 403,
    envelope: { success: false, error: { message: "actor access denied" } },
  }));
  assert.ok(failed.root.textContent.includes("actor access denied"));
  assert.ok(failed.root.textContent.includes("Refresh the page"));
  failed.mounted.unmount();
});
