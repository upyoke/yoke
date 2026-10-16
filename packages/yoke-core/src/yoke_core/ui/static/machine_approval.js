// First-run progress follows organization state in every hosting mode.
import { callFunction, el, portabilityMode } from "./universe_view_support.js";
import { localReachabilityNotice } from "./local_reachability_notice.js";

const STEPS = ["Sign in", "Approve machine", "Create org", "Connect machine"];
const identity = (actor) => `${actor.name} · actor #${actor.actor_id}`;
const localTime = (instant) => new Date(instant).toLocaleTimeString([], {
  hour: "numeric", minute: "2-digit", timeZoneName: "short",
});

function progress(doc, approved) {
  const list = el(doc, "ol", "machine-approval-steps");
  list.setAttribute("aria-label", "Setup progress");
  STEPS.forEach((label, index) => {
    const done = approved || index < 3;
    const step = el(doc, "li", done ? "done" : "active");
    if (!done) step.setAttribute("aria-current", "step");
    const disc = el(doc, "span", "machine-approval-disc", done ? "✓" : index + 1);
    disc.setAttribute("aria-hidden", "true");
    step.appendChild(disc);
    step.appendChild(el(doc, "span", "machine-approval-step-label", label));
    list.appendChild(step);
  });
  return list;
}

function outcome(doc, body, title, recovery, success = false) {
  const line = el(doc, "div", `machine-approval-outcome ${success ? "good" : "warn"}`);
  line.setAttribute("role", success ? "status" : "alert");
  line.appendChild(el(doc, "strong", null, title));
  if (recovery) line.appendChild(el(doc, "p", null, recovery));
  body.appendChild(line);
}

function terminalCallout(doc) {
  const callout = el(doc, "div", "machine-approval-next");
  const svg = doc.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  for (const [tag, attributes] of [
    ["rect", { x: 2.5, y: 4, width: 19, height: 16, rx: 2.5 }],
    ["path", { d: "M7 10l3 2.5L7 15M12.5 15.5H17" }],
  ]) {
    const node = doc.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
    svg.appendChild(node);
  }
  callout.appendChild(svg);
  callout.appendChild(el(doc, "strong", null, "Return to your terminal"));
  return callout;
}

function facts(doc, authorization, org, approved) {
  const table = el(doc, "dl", "machine-approval-facts");
  const row = (label, values) => {
    const group = el(doc, "div", "machine-approval-fact");
    group.appendChild(el(doc, "dt", null, label));
    const value = el(doc, "dd");
    values.forEach((node) => value.appendChild(node));
    group.appendChild(value);
    table.appendChild(group);
  };
  if (authorization.machine) {
    const detail = [authorization.platform, authorization.machine_id && `machine ${authorization.machine_id}`].filter(Boolean).join(" · ");
    row("Machine", [el(doc, "b", null, authorization.machine),
      ...(detail ? [el(doc, "span", "machine-approval-quiet", detail)] : [])]);
  }
  row("Match code", [el(doc, "span", "machine-approval-code", authorization.code.toUpperCase()),
    ...(approved ? [] : [el(doc, "span", "machine-approval-quiet", "must match your terminal")])]);
  if (authorization.requested_by) row("Requested by", [el(doc, "span", null, identity(authorization.requested_by))]);
  row("Organization", [el(doc, "span", null, org.name)]);
  row("Approving as", [el(doc, "span", null, authorization.viewer ? identity(authorization.viewer) : "your signed-in account"),
    el(doc, "span", "machine-approval-quiet", "This machine will act as you."),
    ...(!authorization.viewer ? [el(doc, "span", "machine-approval-quiet", "Ask the server operator to upgrade to show your account details.")] : [])]);
  if (!approved) {
    const time = el(doc, "time", null, localTime(authorization.expires_at));
    time.setAttribute("datetime", authorization.expires_at);
    const minutes = Math.max(1, Math.ceil((Date.parse(authorization.expires_at) - Date.now()) / 60000));
    row("Expires", [time, el(doc, "span", "machine-approval-quiet", `in ${minutes} ${minutes === 1 ? "minute" : "minutes"}`)]);
  }
  return table;
}

export async function renderMachineApproval(context, main, _scope, code, page = {}) {
  if (code && portabilityMode(context.capabilities) !== "local") {
    return renderApprovalCard(context, main, code, { page });
  }
  main.replaceChildren();
  if (page.setPageHead) page.setPageHead({ title: "Connect your machine" });
  else main.appendChild(el(context.document, "h1", "title", "Connect your machine"));
  if (portabilityMode(context.capabilities) === "local") {
    const card = el(context.document, "section", "machine-approval-card");
    card.appendChild(localReachabilityNotice(context.document, { variant: "full" }));
    main.appendChild(card);
  }
}

export async function renderApprovalCard(context, main, code, { embedded = false, onDecided, page = {} } = {}) {
  if (portabilityMode(context.capabilities) === "local") return renderMachineApproval(context, main, null, null, page);
  code = code.trim().toUpperCase();
  const doc = context.document;
  const head = el(doc, "div", "machine-approval-head");
  const card = el(doc, "section", "machine-approval-card");
  card.setAttribute("aria-label", "Machine request");
  if (embedded) card.setAttribute("aria-labelledby", `machine-approval-${code}`);
  main.replaceChildren(head, card);
  const mounted = () => context.isMounted() && main.isConnected !== false && main.contains(card);
  let authorization, org, firstRun = false, timer, focused = false;
  const clock = doc.defaultView || globalThis;
  const title = (text, ready = false) => {
    if (page.setPageHead) page.setPageHead({ title: text });
    else {
      const heading = el(doc, embedded ? "h2" : "h1", "title", text);
      heading.id = `machine-approval-${code}`;
      heading.tabIndex = -1;
      head.appendChild(heading);
      if (embedded && !focused && ready) { heading.focus(); focused = true; }
    }
  };
  function refusal(error, writing = false, body = card) {
    const kind = error.code;
    if (kind === "authorization_owner_mismatch" && authorization?.requested_by) {
      outcome(doc, card, "Another person is answering this request", `Only ${authorization.requested_by.name} can approve it. Ask them, or run \`yoke connect\` again on the new machine.`);
    } else if (["actor_disabled", "organization_membership_required", "authorization_human_required"].includes(kind)) {
      outcome(doc, card, "You can't approve machines here", `${error.message || "Approval is not allowed."} Sign in as an active member of ${org?.name || "this organization"}.`);
    } else if (["authorization_consumed", "authorization_already_decided"].includes(kind)) {
      outcome(doc, card, "This request was already answered", "Check Machines for the connected machine. To connect again, run `yoke connect` on it.");
    } else if (kind === "authorization_expired") {
      outcome(doc, card, authorization ? `This code expired at ${localTime(authorization.expires_at)}` : "This code expired", "Nothing was authorized. Run `yoke connect` again for a new code.");
    } else if (["authorization_unavailable", "not_found"].includes(kind)) {
      outcome(doc, card, "That code isn't available", "It may have expired or been answered. Machines waiting now are listed below.");
    } else {
      outcome(doc, body, error.message || (writing ? "The decision could not be recorded" : "The request could not be read"),
        writing ? "Retry your decision, or return to your terminal to start a fresh connection." : "Reload to retry, or return to your terminal to start a fresh connection.");
    }
  }
  function paint() {
    clock.clearTimeout(timer);
    head.replaceChildren();
    card.replaceChildren();
    const decision = authorization?.decision;
    const approved = decision === "approve" && !["consumed", "expired"].includes(authorization?.state);
    const expired = authorization && (authorization.state === "expired" || !decision && Date.parse(authorization.expires_at) <= Date.now());
    const pending = authorization && !decision && !expired && authorization.state !== "consumed";
    title(approved ? "Machine connected" : pending ? "Approve this machine" : "Connect your machine", true);
    if (firstRun && !embedded) head.appendChild(progress(doc, approved));
    if (!authorization) return;
    if (authorization.state === "consumed") { refusal({ code: "authorization_consumed" }); return; }
    if (expired) { refusal({ code: "authorization_expired" }); return; }
    if (decision === "deny") { outcome(doc, card, "Request denied", "Nothing was authorized."); return; }
    if (approved) {
      outcome(doc, card, `✓ ${authorization.machine || "Your machine"} is connected to ${org.name}`, null, true);
      card.appendChild(terminalCallout(doc));
      card.appendChild(facts(doc, authorization, org, true));
      return;
    }
    card.appendChild(el(doc, "p", "machine-approval-lede", "Approve only if this code matches the one in your terminal."));
    card.appendChild(facts(doc, authorization, org, false));
    const actions = el(doc, "div", "machine-approval-actions");
    const status = el(doc, "div", "machine-approval-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    for (const [action, label] of [["approve", "Approve machine"], ["deny", "Deny"]]) {
      const button = el(doc, "button", action === "deny" ? "secondary" : null, label);
      button.type = "button";
      button.addEventListener("click", async () => {
        clock.clearTimeout(timer);
        Array.from(actions.children).forEach((node) => { node.disabled = true; });
        status.textContent = "Recording your decision…";
        try {
          const reply = await callFunction(context.client, "machine_authorization.resolve", { code, action });
          if (!mounted()) return;
          if (!reply.envelope?.success) {
            const error = reply.envelope?.error || {};
            if (["authorization_expired", "authorization_consumed", "authorization_unavailable", "authorization_already_decided"].includes(error.code)) { await load(); return; }
            if (["authorization_owner_mismatch", "actor_disabled", "organization_membership_required", "authorization_human_required"].includes(error.code)) {
              card.replaceChildren(); refusal(error, true); return;
            }
            throw Object.assign(new Error(error.message || "The decision could not be recorded"), error);
          }
          authorization.decision = reply.envelope.result.authorization.decision;
          authorization.state = authorization.decision === "approve" ? "approved" : "denied";
          paint();
          onDecided?.();
        } catch (error) {
          if (!mounted()) return;
          status.replaceChildren();
          refusal(error, true, status);
          Array.from(actions.children).forEach((node) => { node.disabled = false; });
          schedule();
        }
      });
      actions.appendChild(button);
    }
    card.appendChild(actions);
    card.appendChild(status);
    if (!embedded && !focused) { actions.children[0].focus(); focused = true; }
    schedule();
  }
  function schedule() {
    const delay = Math.max(0, Math.min(60000, Date.parse(authorization.expires_at) - Date.now()));
    timer = clock.setTimeout(() => { if (mounted()) paint(); }, delay);
    timer?.unref?.();
  }
  async function load() {
    try {
      const requests = [["organizations.get", {}], ["machine.list", {}], ["machine_authorization.get", { code }]];
      const replies = await Promise.all(requests.map(([id, payload]) => callFunction(context.client, id, payload)));
      if (!mounted()) return;
      for (const reply of replies.slice(0, 2)) {
        if (!reply.envelope?.success) throw new Error(reply.envelope?.error?.message || "organization_state_unavailable: setup facts could not be read");
      }
      org = replies[0].envelope.result;
      firstRun = replies[1].envelope.result.count === 0;
      const reply = replies[2];
      if (reply && !reply.envelope?.success) {
        const error = reply.envelope?.error || {};
        authorization = undefined;
        paint();
        card.replaceChildren();
        refusal(error);
        return;
      }
      authorization = reply?.envelope.result.authorization;
      paint();
    } catch (error) {
      if (!mounted()) return;
      head.replaceChildren();
      title("Connect your machine", true);
      card.replaceChildren();
      refusal(error);
    }
  }
  title("Connect your machine");
  card.appendChild(el(doc, "p", "machine-approval-lede", "Loading machine request…"));
  return load();
}
