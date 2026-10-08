import { el } from "./universe_view_support.js";

export const SERIES = [
  ["function", "avg_ms", "Function avg", "#5468dc"],
  ["function", "p95_ms", "Function p95", "#8c9af0"],
  ["relay", "p95_ms", "Relay long-poll p95 · right axis", "#d59647", "wait"],
  ["tool", "avg_ms", "Tool avg", "#319984"],
  ["tool", "p95_ms", "Tool p95", "#70b9a7"],
  ["watcher", "p95_ms", "Watcher wall p95 · right axis", "#b27944", "wait"],
  ["hook", "avg_ms", "Hook evaluator avg", "#ad69b1"],
  ["hook", "p95_ms", "Hook evaluator p95", "#ce9bd0"],
];
export const durationLabel = (value) => value === null || value === undefined
  ? "Unknown" : value >= 1000 ? `${(value / 1000).toFixed(2)}s` : `${Math.round(value)}ms`;

export function chartData(result) {
  return [result.buckets.map(b => b.start), ...SERIES.map(([family, metric]) =>
    result.buckets.map(b => b.metrics[family][metric])), result.buckets.map(() => 2000)];
}

export async function drawPerformanceChart({ documentNode, host, result, signal, inspect }) {
  const { default: uPlot } = await import("./uplot.js");
  if (signal?.aborted) return null;
  const data = chartData(result);
  const tooltip = el(documentNode, "div", "performance-hover");
  tooltip.setAttribute("role", "status");
  tooltip.hidden = true;
  host.appendChild(tooltip);
  let picked = 0;
  const range = result.buckets.length
    ? [result.buckets[0].start, result.buckets.at(-1).end] : [0, 1];
  const dateLabel = (stamp) => new Date(stamp * 1000).toLocaleString([], {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
  const tickLabel = stamp => {
    const date = new Date(stamp * 1000);
    return `${date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}\n${date.toLocaleDateString([], { month: "short", day: "numeric" })}`;
  };
  function hover(plot) {
    const index = plot.cursor.idx;
    if (index === null || index === undefined) { tooltip.hidden = true; return; }
    picked = index;
    const bucket = result.buckets[index];
    tooltip.replaceChildren(el(documentNode, "strong", null,
      `${dateLabel(bucket.start)} – ${dateLabel(bucket.end)}`));
    SERIES.forEach(([family, metric, label], seriesIndex) => {
      if (!plot.series[seriesIndex + 1].show) return;
      const value = bucket.metrics[family];
      tooltip.appendChild(el(documentNode, "div", null,
        `${label}: ${durationLabel(value[metric])} · ${value.timed_count}/${value.count} timed · ${value.resolution_seconds}s buckets`));
      if (value.count > value.timed_count) tooltip.appendChild(el(documentNode, "small", null,
        `Unknown ${value.unknown_count}, pending ${value.pending_count}, unsupported ${value.unsupported_count}`));
    });
    tooltip.hidden = false;
    tooltip.style.left = `${Math.max(0, Math.min(plot.cursor.left + 10, host.clientWidth - 310))}px`;
    tooltip.style.top = `${Math.max(0, plot.cursor.top - 70)}px`;
  }
  const color = getComputedStyle(host).getPropertyValue("--yoke-muted").trim() || "#7b8393";
  const plot = new uPlot({
    width: Math.max(260, host.clientWidth), height: 340,
    legend: { show: false }, cursor: { drag: { x: false, y: false } },
    series: [{}, ...SERIES.map(([family, metric, label, stroke, scale], index) => ({
      label, stroke, scale: scale || "y", width: 1, spanGaps: false,
      points: { show: true, filter: (_, seriesIndex) => {
        const values = data[seriesIndex];
        const sparse = values.filter(v => v !== null).length <= 30;
        return values.flatMap((value, n) => value !== null &&
          (sparse ||
           ((values[n - 1] ?? null) === null && (values[n + 1] ?? null) === null)) ? [n] : []);
      }, size: 4, width: 1 },
      dash: metric === "p95_ms" && !scale ? [3, 2] : [],
    })), { label: "2s diagnostic target · ordinary latency only", stroke: color,
      scale: "y", width: 1, dash: [5, 5], points: { show: false } }],
    scales: { x: { time: true, range: () => range }, y: { auto: true }, wait: { auto: true } },
    axes: [{ stroke: color, space: 100, size: 60, grid: { show: false }, values: (_, ticks) => ticks.map(tickLabel) },
      { stroke: color, grid: { stroke: color, width: .25 }, size: 60, label: "Ordinary latency", values: (_, ticks) => ticks.map(durationLabel) },
      { scale: "wait", side: 1, size: 65, stroke: "#b27944", label: "Intentional wait wall time",
        grid: { show: false }, values: (_, ticks) => ticks.map(durationLabel) }],
    hooks: { setCursor: [hover] },
  }, data, host);
  const toggles = el(documentNode, "div", "performance-series");
  SERIES.forEach(([, , label, stroke], index) => {
    const button = el(documentNode, "button", null, label);
    button.type = "button";
    button.style.setProperty("--series-color", stroke);
    button.setAttribute("aria-pressed", "true");
    button.addEventListener("click", () => {
      const show = !plot.series[index + 1].show;
      plot.setSeries(index + 1, { show });
      button.setAttribute("aria-pressed", String(show));
    });
    toggles.appendChild(button);
  });
  host.after(toggles);
  host.tabIndex = 0;
  host.setAttribute("role", "group");
  host.setAttribute("aria-label", "Duration chart. Arrow keys select a bucket; Enter opens its contributing calls.");
  plot.over.addEventListener("click", () => inspect(result.buckets[picked]));
  const keydown = event => {
    if (event.key === "Enter") inspect(result.buckets[picked]);
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      picked = Math.max(0, Math.min(result.buckets.length - 1, picked + (event.key === "ArrowLeft" ? -1 : 1)));
      plot.setCursor({ left: plot.valToPos(data[0][picked], "x"), top: 30 });
    }
  };
  host.addEventListener("keydown", keydown);
  const observer = new ResizeObserver(() => plot.setSize({ width: Math.max(260, host.clientWidth), height: 340 }));
  observer.observe(host);
  let destroyed = false;
  const destroy = () => {
    if (destroyed) return;
    destroyed = true;
    signal?.removeEventListener("abort", destroy);
    host.removeEventListener("keydown", keydown);
    observer.disconnect(); plot.destroy(); toggles.remove(); tooltip.remove();
  };
  signal?.addEventListener("abort", destroy, { once: true });
  return destroy;
}
