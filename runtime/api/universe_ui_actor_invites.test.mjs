import assert from "node:assert/strict";
import test from "node:test";
import { openInviteForm, renderInviteResult } from "../../packages/yoke-core/src/yoke_core/ui/static/actor_invite_form.js";
import { renderInvitesTable } from "../../packages/yoke-core/src/yoke_core/ui/static/actor_invites_table.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });
const tags = (root, tag) => allNodes(root).filter((node) => node.tagName === tag);
const button = (root, text) => tags(root, "BUTTON").find((node) => node.textContent === text);
const click = async (node) => { assert.ok(node); node.dispatchEvent(new Event("click")); await settle(); };
const escape = (node) => node.dispatchEvent(Object.assign(new Event("keydown"), { key: "Escape" }));
const row = (invite_id, state = "pending", extra = {}) => ({
  invite_id, kind: "code", actor_id: invite_id + 10, name: `Person ${invite_id}`, role: "viewer", state,
  created_at: `2026-10-${String(invite_id).padStart(2, "0")}T12:00:00Z`,
  expires_at: "2026-10-30T12:00:00Z", invited_by_name: "Actual inviter", ...extra,
});
function fixture(call = async () => ok({}), fact = { invite_form: "name", sign_in_method: "invite_code" }) {
  const document = new FakeDocument();
  document.defaultView.location.origin = "https://team.example.test";
  const slot = document.createElement("div");
  const requests = [], created = [], cancelled = [];
  let mounted = true;
  const context = { document, isMounted: () => mounted, client: { call: async (request) => { requests.push(request); return call(request); } } };
  const options = { fact, roles: ["admin", "operator", "viewer"], roleDescriptions: { operator: "Run work", viewer: "Read work" },
    roster: [{ kind: "human", name: "Ana" }], onCreated: (value) => created.push(value), onCancel: (...args) => cancelled.push(args) };
  return { context, slot, options, requests, created, cancelled, unmount: () => { mounted = false; slot.replaceChildren(); } };
}
async function submit(f, value) {
  const input = tags(f.slot, "INPUT")[0];
  input.value = value;
  input.dispatchEvent(new Event("input"));
  tags(f.slot, "FORM")[0].dispatchEvent(new Event("submit"));
  await settle();
}

test("name form defaults to operator, explains roles, validates and warns on duplicate names", async () => {
  const f = fixture();
  openInviteForm(f.context, f.slot, f.options);
  const input = tags(f.slot, "INPUT")[0], select = tags(f.slot, "SELECT")[0];
  assert.equal(f.context.document.activeElement, input);
  assert.equal(input.maxLength, 80);
  assert.equal(select.value, "operator");
  assert.match(f.slot.textContent, /Can: Run work/);
  select.value = "viewer"; select.dispatchEvent(new Event("change"));
  assert.match(f.slot.textContent, /Can: Read work/);
  await submit(f, " ");
  assert.equal(f.requests.length, 0);
  assert.match(f.slot.textContent, /Enter the teammate's name\./);
  assert.equal(input.getAttribute("aria-invalid"), "true");
  assert.equal(input.getAttribute("aria-describedby"), "invite-person-error");
  await submit(f, "a".repeat(81));
  assert.match(f.slot.textContent, /80 characters or fewer/);
  input.value = " aNA "; input.dispatchEvent(new Event("input"));
  assert.ok(button(f.slot, "Create another aNA"));
  assert.match(f.slot.textContent, /separate person/);
  await submit(f, "Ana");
  assert.deepEqual(f.requests[0], { function: "teammate_invites.create", payload: { name: "Ana", role: "viewer" } });
  assert.equal(f.created.length, 1);
});

test("submitting disables controls and ignores duplicate submits; cancel and Escape restore the caller", async () => {
  let release;
  const f = fixture(() => new Promise((resolve) => { release = resolve; }));
  openInviteForm(f.context, f.slot, f.options);
  await submit(f, "Jo");
  assert.ok(tags(f.slot, "BUTTON").every((node) => node.disabled));
  assert.match(f.slot.textContent, /Creating invite…/);
  escape(tags(f.slot, "FORM")[0]);
  await submit(f, "Jo");
  assert.equal(f.requests.length, 1);
  assert.equal(f.cancelled.length, 0);
  release({ status: 403, envelope: { success: false, error: { code: "refused", message: "No access", hint: "Ask an admin" } } });
  await settle();
  assert.match(f.slot.textContent, /No access.*refused.*Ask an admin/);
  assert.ok(tags(f.slot, "BUTTON").every((node) => !node.disabled));
  await click(button(f.slot, "Cancel"));
  assert.equal(f.slot.textContent, "");
  assert.equal(f.cancelled.length, 1);
  openInviteForm(f.context, f.slot, f.options);
  escape(tags(f.slot, "FORM")[0]);
  assert.equal(f.cancelled.length, 2);
});

test("email fact selects its field and dispatch; email result has no secret reveal", async () => {
  const f = fixture(async () => ok({ invite: { email: "ana@example.test" } }), { invite_form: "email", sign_in_method: "yoke_account" });
  openInviteForm(f.context, f.slot, f.options);
  assert.equal(tags(f.slot, "INPUT")[0].type, "email");
  assert.match(f.slot.textContent, /their Yoke account/);
  await submit(f, "bad");
  assert.equal(f.requests.length, 0);
  assert.match(f.slot.textContent, /Enter an email address/);
  await submit(f, "ana@example.test");
  assert.equal(f.requests[0].function, "identity.invite.create");
  for (const result of [f.created[0], { email: "ana@example.test" }]) {
    renderInviteResult(f.context, f.slot, result, { onDone() {} });
    assert.match(f.slot.textContent, /Invite sent to ana@example.test\. They join when they sign in\./);
    assert.equal(byClass(f.slot, "profile-token-reveal").length, 0);
    assert.equal(tags(f.slot, "CODE").length, 0);
  }
});

test("refusals retain the selected form and replay points to Reissue without duplicate creation", async () => {
  for (const code of ["invite_email_required", "invite_name_required", "result_unavailable"]) {
    const f = fixture(async () => ({ status: 409, envelope: { success: false, error: { code, message: "Cannot create" } } }));
    openInviteForm(f.context, f.slot, f.options);
    await submit(f, "Ana");
    assert.equal(tags(f.slot, "INPUT")[0].type, "text");
    assert.equal(f.requests.length, 1);
    assert.deepEqual(f.created, [null]);
    assert.match(f.slot.textContent, code === "result_unavailable" ? /Reissue/ : /Reload to update the form/);
  }
});

test("code result gives all guidance, closes explicitly and clears even the detached code node", async () => {
  const f = fixture();
  let done = 0;
  const result = { invite: row(1, "pending", { name: "Ana" }), code: "fixture-private-invite", expires_at: "2026-10-30T12:00:00Z" };
  renderInviteResult(f.context, f.slot, result, { onDone: () => done++ });
  const secret = byClass(f.slot, "profile-token-value")[0];
  assert.equal(secret.textContent, result.code);
  for (const copy of ["shown once and never again", "Expires", "(in 24 hours). Works once.", "Send it to Ana only",
    "yoke connect https://team.example.test", "choose Enter invite code", "Yoke keeps only a hash"]) assert.ok(f.slot.textContent.includes(copy), copy);
  assert.equal(tags(f.slot, "TIME")[0].getAttribute("datetime"), result.expires_at);
  assert.ok(allNodes(f.slot).every((node) => !String(node.title || "").includes(result.code)));
  assert.equal(f.context.document.activeElement, button(f.slot, "Done"));
  openInviteForm(f.context, f.slot, f.options);
  assert.ok(button(f.slot, "Close code"));
  await click(button(f.slot, "Keep"));
  assert.equal(secret.textContent, result.code);
  openInviteForm(f.context, f.slot, f.options);
  escape(button(f.slot, "Close code").parentNode);
  assert.equal(f.cancelled.length, 2);
  openInviteForm(f.context, f.slot, f.options);
  await click(button(f.slot, "Close code"));
  assert.equal(secret.textContent, "");
  assert.equal(tags(f.slot, "FORM").length, 1);
  renderInviteResult(f.context, f.slot, result, { onDone: () => done++ });
  const second = byClass(f.slot, "profile-token-value")[0];
  await click(button(f.slot, "Done"));
  assert.equal(second.textContent, "");
  assert.equal(done, 1);
});

test("late create response cannot display a secret after navigation", async () => {
  let release;
  const f = fixture(() => new Promise((resolve) => { release = resolve; }));
  openInviteForm(f.context, f.slot, f.options);
  await submit(f, "Ana");
  f.unmount();
  release(ok({ invite: row(1), code: "private" }));
  await settle();
  assert.equal(f.created.length, 0);
  assert.equal(f.slot.textContent, "");
});

test("mixed invite rows use fixed state/time order, catalog roles and authoritative inviter names", () => {
  const f = fixture();
  const rows = [row(3, "revoked"), row(2), row(4, "consumed"), row(1), row(5, "expired"),
    row(6, "pending", { kind: "email", email: "email@example.test", role: null, invited_by_user_id: 2, invited_by_name: "Platform inviter" })];
  renderInvitesTable(f.context, f.slot, rows, { showUsed: true, roleDescriptions: { viewer: "Read only" } });
  const rendered = tags(f.slot, "TBODY")[0].children;
  assert.deepEqual(rendered.map((tr) => tr.children[0].textContent), ["email@example.test", "Person 2actor #12", "Person 1actor #11", "Person 5actor #15", "Person 3actor #13", "Person 4actor #14"]);
  assert.equal(byClass(f.slot, "actors-role")[0].title, "Read only");
  assert.match(rendered[0].textContent, /No role grant.*Platform inviter/);
  assert.deepEqual(byClass(f.slot, "pill").map((node) => node.className), ["pill run", "pill run", "pill run", "pill warn", "pill idle", "pill good"]);
  assert.equal(rendered[5].children[3].textContent, "joined");
  assert.equal(rendered[4].children[4].textContent, "—");
  assert.equal(tags(f.slot, "BUTTON").length, 0);
  assert.equal(tags(f.slot, "CAPTION")[0].textContent, "Invites");
  assert.equal(rendered[0].children[5].getAttribute("data-label"), "Invited by");
});

test("older rows expose missing fields without guessed roles, time or cross-domain identity", () => {
  const f = fixture();
  const rows = [row(1, "pending", { role: undefined, created_at: undefined, invited_by_name: undefined, role_id: 1, invited_by_user_id: 2 }), row(2)];
  renderInvitesTable(f.context, f.slot, rows, { showUsed: false });
  for (const copy of ["Role unavailable", "Creation order is unavailable", "Inviter unavailable", "upgrade"]) assert.ok(f.slot.textContent.includes(copy));
  assert.equal(tags(f.slot, "TBODY")[0].children[0].children[0].textContent, "Person 1actor #11");
  renderInvitesTable(f.context, f.slot, [row(1, "consumed")], { showUsed: false });
  assert.match(f.slot.textContent, /No active invites\. Show used/);
  renderInvitesTable(f.context, f.slot, [], { showUsed: false });
  assert.equal(f.slot.textContent, "No invites yet.");
});

test("creation ordering preserves stored fractional precision within one millisecond", () => {
  const f = fixture();
  renderInvitesTable(f.context, f.slot, [row(1, "pending", { created_at: "2026-10-17T12:00:00.123001Z" }),
    row(2, "pending", { created_at: "2026-10-17T12:00:00.123002Z" })], {});
  assert.equal(tags(f.slot, "TBODY")[0].children[0].children[0].textContent, "Person 2actor #12");
});

test("kind/state actions confirm inline, cancel with Escape, and preserve refusals", async () => {
  const f = fixture();
  const calls = [];
  const options = { canManage: true, showUsed: true, onRevoke: async (value) => { calls.push(value.invite_id); return { status: 409, envelope: { error: { message: "Already changed", hint: "Reload" } } }; }, onReissue: async () => ok({}) };
  renderInvitesTable(f.context, f.slot, [row(1), row(2, "expired"), row(3, "revoked"), row(4, "consumed"), row(5, "pending", { kind: "email", email: "a@example.test" })], options);
  const rendered = tags(f.slot, "TBODY")[0].children;
  const email = rendered.find((tr) => tr.textContent.includes("a@example.test"));
  assert.equal(email.children[6].title, "Revoke, then invite again to resend.");
  assert.equal(button(email, "Reissue"), undefined);
  assert.equal(tags(f.slot, "BUTTON").filter((node) => node.textContent === "Reissue").length, 3);
  const revoke = button(f.slot, "Revoke…");
  await click(revoke);
  const confirm = button(f.slot, "Revoke invite");
  assert.equal(f.context.document.activeElement, confirm);
  escape(confirm.parentNode);
  assert.equal(f.context.document.activeElement, revoke);
  await click(revoke);
  await click(button(f.slot, "Revoke invite"));
  assert.equal(calls.length, 1);
  assert.match(f.slot.textContent, /Already changed Reload/);
  assert.equal(button(f.slot, "Revoke invite").disabled, false);
  await click(button(f.slot, "Cancel"));
  await click(button(f.slot, "Reissue"));
  assert.match(f.slot.textContent, /old code stops working/);
  assert.equal(f.context.document.activeElement, button(f.slot, "Reissue invite"));
});
