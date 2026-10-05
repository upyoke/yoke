// Capture the real claimed review server, proving its committed source first.
// YOKE_REVIEW_URL names the tokenized URL printed by serve_workbench_for_review.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const [modulePath, output] = process.argv.slice(2);
const target = process.env.YOKE_REVIEW_URL;
// Deployment-bound cases carry the marker; lane cases run in their claimed cwd.
const candidate = JSON.parse(process.env.YOKE_QA_CANDIDATE_TREE || "null") || {
  head_sha: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
};
assert.equal(execFileSync("git", ["status", "--porcelain"], { encoding: "utf8" }).trim(), "");
assert(modulePath && output && target && candidate?.head_sha,
  "Require Playwright, output directory, review URL and QA candidate identity.");
const identity = new URL("/served-build", target);
identity.search = new URL(target).search;
const response = await fetch(identity);
assert(response.ok, "Review server must publish its identity.");
assert.equal((await response.text()).trim(), candidate.head_sha);
await mkdir(output, { recursive: true });
const { chromium } = createRequire(import.meta.url)(modulePath);
const browser = await chromium.launch({ headless: true });
const measurements = { head_sha: candidate.head_sha, pages: [] };
try {
  for (const width of [1280, 390]) {
    for (const [route, ready] of [["sessions", ".session-harness"], ["strategy", ".strategy-doc-state"]]) {
      const context = await browser.newContext({ viewport: { width, height: 1000 },
        isMobile: width === 390, hasTouch: width === 390 });
      const page = await context.newPage();
      const url = new URL(`/${route}`, target); url.search = new URL(target).search;
      await page.goto(url.href); await page.locator(ready).first().waitFor();
      const data = await page.locator(ready).evaluateAll((nodes) => nodes.map((n) => {
        const value = { text: n.textContent.trim(), width: n.getBoundingClientRect().width,
          grow: getComputedStyle(n).flexGrow };
        const clone = n.cloneNode(true);
        Object.assign(clone.style, { position: "absolute", width: "max-content", maxWidth: "none" });
        n.parentElement.append(clone);
        value.naturalWidth = clone.getBoundingClientRect().width; clone.remove();
        return value;
      }));
      assert(data.length > 0 && data.every((n) => n.width > 0 && n.width <= n.naturalWidth + 1 && n.grow === "0"),
        JSON.stringify({ route, width, data }));
      measurements.pages.push({ route, width, data });
      if (route === "sessions") await page.locator(".session-roster-filters").screenshot({
        path: path.join(output, `filters-${width}.png`),
      });
      await page.screenshot({ path: path.join(output, `${route}-${width}.png`), fullPage: true });
      await context.close();
    }
  }
  // Recheck identity after the captures so a changed server cannot earn credit.
  assert.equal((await (await fetch(identity)).text()).trim(), candidate.head_sha);
  await writeFile(path.join(output, "candidate-measurements.json"), JSON.stringify(measurements, null, 2));
  console.log(`Populated Sessions/Strategy captured at 1280/390 on ${candidate.head_sha}`);
} finally { await browser.close(); }
