// Render the real Inbox against synthetic data; this is source review evidence.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const [playwrightModule, output] = process.argv.slice(2);
assert(playwrightModule && output, "Supply PLAYWRIGHT_MODULE and OUTPUT_DIR.");
const { chromium } = createRequire(import.meta.url)(playwrightModule);
const checkout = fileURLToPath(new URL("../../", import.meta.url));
const root = path.join(checkout, "packages/yoke-core/src/yoke_core/ui/static");
const git = (...args) => execFileSync("git", ["-C", checkout, ...args], { encoding: "utf8" }).trim();
const head = git("rev-parse", "HEAD");
assert.equal(git("status", "--porcelain"), "", "Commit the capture source first.");
const entry = await readFile(path.join(root, "index.html"), "utf8");
const styles = [...entry.matchAll(/href="(?:\.\/|\/)assets\/([^\"]+\.css)"/g)].map((match) => match[1]);
const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
${styles.map((name) => `<link rel="stylesheet" href="/assets/${name}">`).join("\n")}
<style>body{margin:0;background:var(--yoke-bg);color:var(--yoke-ink);font-family:var(--yoke-font-sans)}
main{max-width:960px;margin:auto;padding:16px}footer{font-size:11px;overflow-wrap:anywhere;margin-top:20px}</style></head>
<body><main class="universe-app-root"><h1>Inbox</h1><div id="inbox"></div><footer>Source fixture · ${head}</footer></main>
<script type="module">
import {renderInboxView} from '/assets/universe_views_inbox.js';
const state=new URL(location.href).searchParams.get('state');
const stamp=new Date(Date.now()-300000).toISOString();
const question={id:7,kind:'operator_question',status:'pending',project_id:10,created_at:stamp,
requesting_session_label:'Morgan',actions:['reply','freeform'],subject_context:{question:'Which response should we send?',
options:[{id:'reply',label:'Send the response'}],recommended_option:'reply',allow_freeform:true}};
let posts=[{id:4,project_id:10,title:'Review a request',body:'Please read the details and mark this post Done when the shared work is complete.',
source:'External form',fields:{Contact:'person@example.test',Details:'Plain text stays readable: <b>this is not markup</b>.'}}];
if(state==='long')posts[0]={...posts[0],title:'A'.repeat(160),fields:{['A long field name '.repeat(8)]:'https://example.test/'+('segment'.repeat(90))}};
window.calls=[];
const client={async call(request){window.calls.push(request);
if(request.function==='inbox.posts.done'){
if(state==='error')return {status:403,envelope:{success:false,error:{code:'not_in_audience',message:'Ask a current audience member to mark it Done.'}}};
posts=[];return {status:200,envelope:{success:true,result:{post:{done_by:'Morgan',done_at:'2026-11-05T12:00:00Z',already_done:state==='done'}}}};}
return {status:200,envelope:{success:true,result:{needs_decision:[question],posts,messages:[
{message_id:'sample-message',body:'The request is ready for your review.',sender_actor_label:'Taylor',created_at:stamp,actor_receipt:{state:'pending'}},
{message_id:'sample-result',body:'Verification passed.',notice_kind:'qa_result',created_at:stamp,actor_receipt:{state:'pending'}}]}}};}};
renderInboxView({document,client,isMounted:()=>true,projects:()=>[{id:10,name:'Example project'}]},document.getElementById('inbox'),'all');
</script></body></html>`;
const server = createServer(async (request, response) => {
  try {
    const pathname = new URL(request.url, "http://localhost").pathname;
    if (pathname === "/served-build") { response.setHeader("Content-Type", "application/json"); response.end(JSON.stringify({ source_commit: head, source: "source fixtures" })); return; }
    if (pathname === "/") { response.setHeader("Content-Type", "text/html"); response.end(html); return; }
    const name = pathname.slice("/assets/".length);
    assert(pathname.startsWith("/assets/") && !name.includes("/") && !name.includes(".."));
    response.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : "text/css");
    response.end(await readFile(path.join(root, name)));
  } catch (error) { response.statusCode = 500; response.end(String(error)); }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const captures = [];
try {
  for (const width of [1440, 375]) for (const state of ["open", "long", "error", "done"]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 }, colorScheme: "light" });
    const errors = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    await page.goto(`http://127.0.0.1:${server.address().port}/?state=${state}`);
    await page.locator(".inbox-post-card").waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${width} ${state} overflowed`);
    assert.equal(await page.locator(".inbox-post-card script, .inbox-post-card b").count(), 0);
    const button = page.locator(".inbox-post-card button");
    const height = await button.evaluate((node) => node.getBoundingClientRect().height);
    if (height < 44) await page.screenshot({ path: path.join(output, `${width}-${state}-failure.png`), fullPage: true });
    assert(height >= 44, `Done must be at least 44px high; observed ${height}px`);
    if (state === "error" || state === "done") {
      await button.click();
      if (state === "error") {
        await page.locator(".inbox-post-card .inbox-row-error").waitFor();
        assert.equal(await button.isDisabled(), false);
      } else {
        await page.locator(".inbox-post-completion").waitFor();
        assert.equal(await page.locator(".inbox-post-card").count(), 0);
        assert.match(await page.locator(".inbox-post-completion").textContent(), /Done by Morgan/);
      }
    }
    await page.screenshot({ path: path.join(output, `${width}-${state}.png`), fullPage: true });
    assert.deepEqual(errors, []);
    captures.push({ width, state, calls: await page.evaluate(() => window.calls) });
    await page.close();
  }
  await writeFile(path.join(output, "measurements.json"), JSON.stringify({ head, data_source: "source fixtures", captures }, null, 2));
  process.stdout.write(`Verified ${captures.length} responsive post states.\n`);
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
