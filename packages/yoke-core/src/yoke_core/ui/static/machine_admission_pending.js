import { callFunction, el, isRegistrySkewError, portabilityMode } from "./universe_view_support.js";
import { renderApprovalCard } from "./machine_approval.js";
import { localReachabilityNotice } from "./local_reachability_notice.js";
import { routeHref } from "./universe_navigation.js";

export function resolveMirroredMachineApproval(context, row, action, note) {
  const resolution = { request_id: row.id ?? row.request_id, action };
  if (note) resolution.note = note;
  return callFunction(context.client, "decision_requests.resolve", resolution);
}

const approvingViewers = new WeakMap();

export function appendApprovingAs(context, host) {
  const line = el(context.document, "p", "review-who",
    "Approving as your signed-in account. This machine will act as you.");
  host.appendChild(line);
  const mount = context.signal || context;
  if (!approvingViewers.has(mount)) {
    approvingViewers.set(mount, Promise.resolve()
      .then(() => callFunction(context.client, "machine_authorization.pending", {}))
      .then((reply) => reply.envelope?.success ? reply.envelope.result?.viewer : null)
      .catch(() => null));
  }
  return approvingViewers.get(mount).then((viewer) => {
    if (context.signal?.aborted || !context.isMounted() || !host.contains(line)) return;
    if (viewer) line.textContent = `Approving as ${viewer.name} · actor #${viewer.actor_id}. This machine will act as you.`;
  });
}

export function renderPendingMachines(context, host, { selectedCode, compact = false, onSelect } = {}) {
  const doc = context.document, clock = doc.defaultView || globalThis;
  const signal = context.signal;
  const panel = el(doc, "section", "panel machine-pending");
  const header = el(doc, "div", "panel-header");
  const heading = el(doc, "h2");
  const body = el(doc, "div", "panel-body");
  const list = el(doc, "div");
  const card = el(doc, "div", "machine-pending-card");
  card.id = "machine-pending-card";
  const status = el(doc, "p", "machine-pending-status");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  header.appendChild(heading);
  [list, status, card].forEach((node) => body.appendChild(node));
  [header, body].forEach((node) => panel.appendChild(node));
  panel.hidden = true;
  host.replaceChildren(panel);
  if (portabilityMode(context.capabilities) === "local") {
    panel.hidden = false;
    panel.replaceChildren(localReachabilityNotice(doc, { variant: "full" }));
    return { reload: async () => {} };
  }

  let selected = selectedCode?.trim().toUpperCase(), rows = [], failure = null;
  let sequence = 0, refreshTimer, expiryTimer, stopped = false;
  const active = () => !stopped && !signal?.aborted && context.isMounted()
    && host.isConnected !== false && host.contains(panel);
  const stop = () => {
    stopped = true;
    clock.clearTimeout(refreshTimer);
    clock.clearTimeout(expiryTimer);
    doc.removeEventListener("visibilitychange", visible);
  };
  const schedule = () => {
    clock.clearTimeout(refreshTimer);
    if (selected && active()) {
      refreshTimer = clock.setTimeout(reload, 30000);
      refreshTimer?.unref?.();
    }
  };
  function select(code) {
    if (!active()) return;
    selected = code;
    const href = routeHref(`/machine-approval/${encodeURIComponent(code)}`, context.basePath);
    clock.history.replaceState(clock.history.state, "", href);
    if (onSelect) onSelect(code);
    else {
      renderApprovalCard(context, card, code, { embedded: true, onDecided: reload });
    }
    paint();
    schedule();
  }
  function paint() {
    if (!active()) { stop(); return; }
    clock.clearTimeout(expiryTimer);
    list.replaceChildren();
    status.replaceChildren();
    const shown = compact ? rows.filter((row) => row.code !== selected) : rows;
    panel.hidden = !failure && !shown.length && (compact ? Boolean(selected) : !selected);
    heading.textContent = compact && selected ? `Other machines waiting (${shown.length})` : "Waiting for approval";
    if (!compact && !failure) heading.appendChild(el(doc, "span", "panel-count", `· ${shown.length}`));
    if (failure) {
      status.textContent = isRegistrySkewError(failure)
        ? "This server can't list waiting machines yet. Open the link your terminal printed to approve it."
        : "Waiting machines could not be read.";
      if (!isRegistrySkewError(failure)) {
        const retry = el(doc, "button", "machines-retry", "Try again");
        retry.type = "button";
        retry.addEventListener("click", reload);
        status.appendChild(retry);
      }
      return;
    }
    if (!shown.length) {
      if (compact && !selected) {
        [el(doc, "span", null, "No machines are waiting. Run "),
          el(doc, "code", null, "yoke connect <server>"),
          el(doc, "span", null, " on the new machine, then open the link it prints.")]
          .forEach((node) => status.appendChild(node));
      }
      return;
    }
    list.appendChild(el(doc, "p", "machine-approval-lede", "Approve only machines you are connecting yourself. The code must match the terminal."));
    const wrap = el(doc, "div", "table-wrap");
    const table = el(doc, "table", "items table-stacks-narrow");
    table.appendChild(el(doc, "caption", "shell-visually-hidden", "Machines waiting for approval"));
    const titles = ["Code", "Machine", "Requested by", "Expires", "Review"];
    const thead = el(doc, "thead"), tr = el(doc, "tr"), tbody = el(doc, "tbody");
    for (const title of titles) {
      const th = el(doc, "th", null, title);
      th.setAttribute("scope", "col");
      tr.appendChild(th);
    }
    thead.appendChild(tr);
    [thead, tbody].forEach((node) => table.appendChild(node));
    let nextExpiry = Infinity;
    for (const request of shown) {
      const row = el(doc, "tr");
      row.setAttribute("aria-selected", String(request.code === selected));
      const cells = titles.map((title) => {
        const cell = el(doc, "td");
        cell.setAttribute("data-label", title);
        row.appendChild(cell);
        return cell;
      });
      cells[0].appendChild(el(doc, "span", "machine-approval-code", request.code));
      cells[1].appendChild(el(doc, "b", null, request.machine || "—"));
      const details = [request.platform, request.machine_id && `machine ${request.machine_id}`].filter(Boolean).join(" · ");
      if (details) cells[1].appendChild(el(doc, "div", "machine-approval-quiet", details));
      const actor = request.requested_by;
      cells[2].appendChild(el(doc, "span", null, actor ? `${actor.name} · actor #${actor.actor_id}` : "Not signed in yet"));
      const remaining = Date.parse(request.expires_at) - Date.now();
      const expired = request.state === "expired" || remaining <= 0;
      const time = el(doc, "time", null, new Date(request.expires_at).toLocaleTimeString([], {
        hour: "numeric", minute: "2-digit", timeZoneName: "short",
      }));
      time.setAttribute("datetime", request.expires_at);
      cells[3].appendChild(time);
      if (expired) cells[4].appendChild(el(doc, "span", "pill idle", "expired"));
      else {
        const minutes = Math.max(1, Math.ceil(remaining / 60000));
        cells[3].appendChild(el(doc, "span", "machine-approval-quiet", `in ${minutes} ${minutes === 1 ? "minute" : "minutes"}`));
        nextExpiry = Math.min(nextExpiry, remaining, 60000);
        const review = el(doc, "button", "item-button primary", "Review");
        review.type = "button";
        review.setAttribute("aria-expanded", String(request.code === selected));
        review.setAttribute("aria-controls", onSelect ? "machine-approval-selected" : card.id);
        review.addEventListener("click", () => select(request.code));
        cells[4].appendChild(review);
      }
      tbody.appendChild(row);
    }
    wrap.appendChild(table);
    list.appendChild(wrap);
    if (Number.isFinite(nextExpiry)) {
      expiryTimer = clock.setTimeout(paint, nextExpiry);
      expiryTimer?.unref?.();
    }
  }
  async function reload() {
    if (!active()) { stop(); return; }
    const current = ++sequence;
    try {
      const reply = await callFunction(context.client, "machine_authorization.pending", {});
      if (!reply.envelope?.success) throw reply.envelope?.error || {};
      if (current !== sequence || !active()) return;
      if (!Array.isArray(reply.envelope.result?.requests)) throw new Error("Pending requests unavailable");
      rows = reply.envelope.result.requests;
      failure = null;
    } catch (error) {
      if (current !== sequence || !active()) return;
      failure = error;
    }
    paint();
    schedule();
  }
  function visible() {
    if (!active()) { stop(); return; }
    if (doc.visibilityState === "visible") reload();
  }
  doc.addEventListener("visibilitychange", visible);
  signal?.addEventListener("abort", stop, { once: true });
  reload();
  return { reload };
}
