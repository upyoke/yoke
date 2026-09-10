// The Profile page and the actor menu that leads to it: one profile.get
// read feeds five cards; revoke asks once inline; the onboarding reset
// clears the hidden count; the sidebar never lists Profile.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { displayTimeZoneValue } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_time.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

const MACHINE_ID = "11111111-1111-4111-8111-111111111111";

function profileAnswer(overrides = {}) {
  return {
    actor: { id: 2, kind: "human", name: "Ben" },
    identity: { email: "ben@example.test", signed_in_with: "Google" },
    roles: {
      org: [{ org: "Acme", role: "admin" }],
      projects: [{ project: "yoke", name: "Yoke", role: "admin" }],
    },
    tokens: [
      {
        token_id: 7, name: "operator-cli", status: "active",
        created_at: "2026-06-30T00:00:00Z", last_used_at: "2026-09-10T10:00:00Z",
        expires_at: null, machine_id: null, machine_name: null,
      },
      {
        token_id: 8, name: "laptop", status: "active",
        created_at: "2026-08-01T00:00:00Z", last_used_at: null,
        expires_at: null, machine_id: MACHINE_ID, machine_name: "laptop",
      },
    ],
    preferences: { time_zone: "Europe/Berlin" },
    onboarding: { hidden_count: 2 },
    ...overrides,
  };
}

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

function profileClient(profile = profileAnswer()) {
  const requests = [];
  let current = profile;
  return {
    requests,
    async call(request) {
      requests.push(request);
      switch (request.function) {
        case "organizations.get":
          return ok({ name: "Local", slug: "local" });
        case "projects.list":
          return ok({ rows: [] });
        case "profile.get":
          return ok(current);
        case "profile.token.revoke":
          current = {
            ...current,
            tokens: current.tokens.filter(
              (token) => token.token_id !== request.payload.token_id,
            ),
          };
          return ok({ token_id: request.payload.token_id, status: "revoked" });
        case "profile.token.create":
          return ok({ token_id: 9, name: request.payload.name, raw_token: "yk_raw_once" });
        case "profile.preference.set":
          return ok(request.payload);
        case "profile.onboarding.reset":
          current = { ...current, onboarding: { hidden_count: 0 } };
          return ok({ cleared: 2 });
        default:
          throw new Error(`unexpected function ${request.function}`);
      }
    },
  };
}

async function mountProfile(client, hash = "#/profile") {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  await settle();
  return { root, mounted, documentNode };
}

function panelTitles(root) {
  return byClass(root, "panel-header").map((h) => h.children[0].textContent);
}

function texts(root, className) {
  return byClass(root, className).map((node) => node.textContent);
}

test("profile draws five cards from one read", async () => {
  const client = profileClient();
  const { root, mounted } = await mountProfile(client);
  assert.deepEqual(panelTitles(root), [
    "Who you are", "What you can do", "API tokens", "Preferences",
    "Reset onboarding modules",
  ]);
  assert.equal(
    client.requests.filter((r) => r.function === "profile.get").length >= 1,
    true,
  );
  const facts = byClass(root, "profile-facts")[0];
  const labels = allNodes(facts).filter((n) => n.tagName === "DT")
    .map((n) => n.textContent);
  assert.deepEqual(labels, ["Name", "Email", "Signed in with", "Actor id"]);
  const rows = byClass(root, "profile-row");
  const rowTitles = rows.map((row) => byClass(row, "")[0] || row)
    .map((row) => allNodes(row).find((n) => n.tagName === "B").textContent);
  assert.deepEqual(rowTitles, ["Acme", "Yoke", "operator-cli", "laptop"]);
  const machineLink = allNodes(root).find(
    (n) => n.tagName === "A" && n.textContent === "Machine →",
  );
  assert.equal(machineLink.href, `#/machines/${MACHINE_ID}`);
  assert.equal(displayTimeZoneValue(), "Europe/Berlin");
  mounted.unmount();
});

test("profile hides email when the actor has no linked identity", async () => {
  const client = profileClient(profileAnswer({ identity: null }));
  const { root, mounted } = await mountProfile(client);
  const facts = byClass(root, "profile-facts")[0];
  const labels = allNodes(facts).filter((n) => n.tagName === "DT")
    .map((n) => n.textContent);
  assert.deepEqual(labels, ["Name", "Actor id"]);
  mounted.unmount();
});

test("revoke asks once inline, then reloads the tokens", async () => {
  const client = profileClient();
  const { root, mounted } = await mountProfile(client);
  const arm = allNodes(root).find(
    (n) => n.tagName === "BUTTON" && n.textContent === "Revoke…",
  );
  arm.dispatchEvent(new Event("click"));
  assert.equal(
    client.requests.filter((r) => r.function === "profile.token.revoke").length,
    0,
  );
  const confirm = allNodes(root).find(
    (n) => n.tagName === "BUTTON" && n.textContent === "Revoke",
  );
  confirm.dispatchEvent(new Event("click"));
  await settle();
  await settle();
  const revoke = client.requests.find((r) => r.function === "profile.token.revoke");
  assert.deepEqual(revoke.payload, { token_id: 7 });
  assert.equal(
    allNodes(root).some((n) => n.tagName === "B" && n.textContent === "operator-cli"),
    false,
  );
  mounted.unmount();
});

test("reset clears the hidden count and disables itself", async () => {
  const client = profileClient();
  const { root, mounted } = await mountProfile(client);
  const reset = allNodes(root).find(
    (n) => n.tagName === "BUTTON" && n.textContent === "Reset",
  );
  assert.equal(reset.disabled, false);
  const sentence = reset.parentNode.children[0].textContent;
  assert.match(sentence, /\(2 hidden now\)/);
  reset.dispatchEvent(new Event("click"));
  await settle();
  await settle();
  assert.equal(
    client.requests.filter((r) => r.function === "profile.onboarding.reset").length,
    1,
  );
  const after = allNodes(root).find(
    (n) => n.tagName === "BUTTON" && n.textContent === "Reset",
  );
  assert.equal(after.disabled, true);
  assert.doesNotMatch(after.parentNode.children[0].textContent, /hidden now/);
  mounted.unmount();
});

test("the actor menu names the person and links to Profile; the sidebar does not", async () => {
  const client = profileClient();
  const { root, mounted } = await mountProfile(client, "#/overview");
  const chip = byClass(root, "actor-chip")[0];
  assert.equal(chip.tagName, "BUTTON");
  assert.equal(byClass(root, "actor-name")[0].textContent, "Ben");
  const menu = byClass(root, "actor-menu")[0];
  assert.equal(menu.hidden, true);
  chip.dispatchEvent(new Event("click"));
  assert.equal(menu.hidden, false);
  assert.equal(
    byClass(root, "actor-menu-heading")[0].textContent,
    "Ben · ben@example.test",
  );
  const link = byClass(root, "actor-menu-link")[0];
  assert.equal(link.textContent, "Profile");
  assert.equal(link.href, "#/profile");
  const sidebarLabels = byClass(root, "nav-link")
    .map((n) => byClass(n, "txt")[0].textContent);
  assert.equal(sidebarLabels.includes("Profile"), false);
  mounted.unmount();
});
