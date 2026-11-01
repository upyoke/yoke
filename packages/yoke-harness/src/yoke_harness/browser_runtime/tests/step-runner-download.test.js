'use strict';

const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { chromium } = require('playwright');
const { executeStep } = require('../src/step-runner');

(async () => {
  const scratch = await fs.realpath(
    await fs.mkdtemp(path.join(os.tmpdir(), 'browser-download-'))
  );
  const bytes = Buffer.from('archive bytes\x00\xff');
  const server = http.createServer((req, res) => {
    if (req.url === '/archive') {
      res.writeHead(200, {
        'Content-Type': 'application/octet-stream',
        'Content-Disposition': 'attachment; filename="export.bin"',
      });
      res.end(bytes);
    } else {
      res.setHeader('Content-Type', 'text/html');
      res.end('<a href="/archive">Download archive</a><button>Do nothing</button>');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const baseUrl = `http://127.0.0.1:${server.address().port}`;
    await page.goto(baseUrl);
    const options = { baseUrl, outputDir: scratch };
    const step = {
      action: 'download', target: 'text=Download archive', path: 'exports/archive.bin',
    };
    const result = await executeStep(page, step, options);
    assert.equal(result.success, true, result.error);
    assert.deepEqual(await fs.readFile(result.download.path), bytes);
    assert.deepEqual(result.download, {
      path: path.join(scratch, 'exports/archive.bin'),
      filename: 'export.bin', size_bytes: bytes.length,
      sha256: createHash('sha256').update(bytes).digest('hex'),
    });
    const absent = await executeStep(page, {
      ...step, target: 'button', timeout_ms: 150,
    }, options);
    assert.equal(absent.success, false);
    assert.match(absent.error, /browser_download_not_received/);
    assert.match(absent.error, /Check the target/);
    for (const invalid of ['../outside.bin', scratch, '/outside.bin']) {
      const refused = await executeStep(page, { ...step, path: invalid }, options);
      assert.equal(refused.success, false);
      assert.match(refused.error, /browser_download_path_invalid/);
    }
    await fs.symlink(os.tmpdir(), path.join(scratch, 'outside'));
    const link = await executeStep(page, { ...step, path: 'outside/escape.bin' }, options);
    assert.equal(link.success, false);
    assert.match(link.error, /browser_download_path_invalid/);
    const missing = await executeStep(page, step, { baseUrl });
    assert.equal(missing.success, false);
    assert.match(missing.error, /supply a writable outputDir/);
    const fileRoot = await executeStep(page, step, {
      baseUrl, outputDir: path.join(scratch, 'exports/archive.bin'),
    });
    assert.equal(fileRoot.success, false);
    assert.match(fileRoot.error, /browser_download_path_invalid/);
    console.log('Download saves served bytes and metadata; missing downloads and outside paths refuse.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
    await fs.rm(scratch, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exit(1); });
