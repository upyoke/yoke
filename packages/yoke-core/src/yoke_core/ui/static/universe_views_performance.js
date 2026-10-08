import { callFunction, el } from "./universe_view_support.js";
import { drawPerformanceChart } from "./universe_performance_chart.js";
import { inspectBucket } from "./universe_performance_inspector.js";

export const WINDOWS = [[1, "Last hour"], [12, "12h"], [24, "24h"], [72, "3 days"], [168, "Week"], [720, "Month"]];
export const localInput = (value) => {
  const date = new Date(value);
  const pad = n => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};
export function validateRange(from, to) {
  const start = new Date(from), end = new Date(to);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end) {
    throw new Error("performance_range_invalid: From must be a valid time before To.");
  }
  return { since: start.toISOString(), until: end.toISOString() };
}

export function renderPerformanceView(context, main, scope) {
  const documentNode = context.document;
  const routeSignal = context.signal;
  const panel = el(documentNode, "section", "panel performance-panel");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, "Yoke Events"));
  const refresh = el(documentNode, "button", null, "Refresh");
  refresh.type = "button";
  header.appendChild(refresh);
  const toolbar = el(documentNode, "div", "performance-toolbar");
  const windows = el(documentNode, "div", "performance-windows");
  const dates = el(documentNode, "div", "performance-dates");
  const from = el(documentNode, "input"), to = el(documentNode, "input");
  for (const [input, name] of [[from, "From"], [to, "To"]]) {
    input.type = "datetime-local";
    const label = el(documentNode, "label", null, name);
    label.appendChild(input);
    dates.appendChild(label);
  }
  const custom = el(documentNode, "button", "performance-custom", "Custom");
  custom.type = "button";
  const status = el(documentNode, "p", "performance-status");
  status.setAttribute("role", "status");
  const chartHost = el(documentNode, "div", "performance-chart");
  const coverage = el(documentNode, "details", "performance-coverage");
  coverage.appendChild(el(documentNode, "summary", null, "Collection and timing coverage"));
  const note = el(documentNode, "p");
  coverage.appendChild(note);
  for (const node of [windows, dates]) toolbar.appendChild(node);
  for (const node of [header, toolbar, status, chartHost, coverage]) panel.appendChild(node);
  main.replaceChildren(panel);
  const scopePayload = { project_ids: scope === "all" ? null : scope.map(Number) };
  let selected = 24, sequence = 0, controller = null, disposePlot = null;
  const buttons = [];
  function setWindow(hours) {
    selected = hours;
    const end = Date.now();
    to.value = localInput(end);
    from.value = localInput(end - hours * 3600000);
    updateButtons();
  }
  function updateButtons() {
    for (const [button, hours] of buttons) button.setAttribute("aria-pressed", String(selected === hours));
    custom.setAttribute("aria-pressed", String(selected === null));
  }
  for (const [hours, label] of WINDOWS) {
    const button = el(documentNode, "button", null, label);
    button.type = "button";
    button.addEventListener("click", () => { setWindow(hours); load(); });
    buttons.push([button, hours]);
    windows.appendChild(button);
  }
  windows.appendChild(custom);
  async function load() {
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;
    const token = ++sequence;
    disposePlot?.(); disposePlot = null;
    chartHost.replaceChildren();
    let range;
    try { range = validateRange(from.value, to.value); }
    catch (error) { status.textContent = error.message; return; }
    const points = Math.max(20, Math.min(160, Math.round((chartHost.clientWidth || 800) / 7)));
    status.textContent = "Loading retained timing observations…";
    note.textContent = "";
    try {
      const response = await callFunction(context.client, "events.performance.aggregate", {
        ...scopePayload, ...range, points,
      }, null, { signal });
      if (signal.aborted || routeSignal?.aborted || token !== sequence) return;
      if (!response.envelope.success) throw new Error(response.envelope.error?.message || "performance_query_failed: use Refresh to retry");
      const result = response.envelope.result;
      const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      status.textContent = `${result.bucket_seconds}s buckets · ${zone} · last observation ${result.last_observation ? new Date(result.last_observation).toLocaleString() : "Unknown"} · queried ${new Date(result.queried_at).toLocaleString()}`;
      note.textContent = result.coverage;
      if (!result.observation_count) {
        chartHost.appendChild(el(documentNode, "p", "empty", "Unknown · no retained timing observations for this scope and range."));
        return;
      }
      disposePlot = await drawPerformanceChart({ documentNode, host: chartHost, result, signal,
        inspect: bucket => inspectBucket({ ...context, signal }, scopePayload, bucket, chartHost) });
    } catch (error) {
      if (!signal.aborted && !routeSignal?.aborted && token === sequence) status.textContent = `${error.message}. Use Refresh to retry.`;
    }
  }
  function datesChanged() {
    const hours = (Date.parse(to.value) - Date.parse(from.value)) / 3600000;
    selected = WINDOWS.some(([value]) => value === hours) ? hours : null;
    updateButtons(); load();
  }
  custom.addEventListener("click", () => { selected = null; updateButtons(); from.focus(); });
  from.addEventListener("change", datesChanged);
  to.addEventListener("change", datesChanged);
  refresh.addEventListener("click", () => { if (selected !== null) setWindow(selected); load(); });
  routeSignal?.addEventListener("abort", () => { sequence++; controller?.abort(); disposePlot?.(); }, { once: true });
  setWindow(24);
  load();
}
