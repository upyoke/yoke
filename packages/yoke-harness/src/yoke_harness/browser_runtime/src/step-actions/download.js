'use strict';

const fs = require('node:fs/promises');
const { createReadStream } = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { resolveTarget } = require('./target-helpers');

function refusePath() {
  return new Error(
    'browser_download_path_invalid: set path to a file beneath the walker scratch '
    + 'outputDir; supply a writable outputDir and remove traversal or outside symlinks.'
  );
}

function beneath(root, target) {
  const relative = path.relative(root, target);
  return relative && relative !== '..' && !relative.startsWith(`..${path.sep}`)
    && !path.isAbsolute(relative);
}

async function destination(outputDir, requested) {
  if (!outputDir || typeof requested !== 'string' || !requested.trim()) {
    throw refusePath();
  }
  const declaredRoot = path.resolve(outputDir);
  const declaredTarget = path.resolve(declaredRoot, requested);
  if (!beneath(declaredRoot, declaredTarget)) throw refusePath();
  await fs.mkdir(declaredRoot, { recursive: true });
  const root = await fs.realpath(declaredRoot);
  const target = path.join(root, path.relative(declaredRoot, declaredTarget));
  // Walk one directory at a time: never create directories through an outside link.
  let parent = root;
  for (const part of path.relative(root, path.dirname(target)).split(path.sep)) {
    if (!part) continue;
    parent = path.join(parent, part);
    await fs.mkdir(parent, { recursive: true });
    const real = await fs.realpath(parent);
    if (!beneath(root, real)) throw refusePath();
  }
  try {
    const stat = await fs.lstat(target);
    if (stat.isSymbolicLink() || !stat.isFile()) throw refusePath();
  } catch (err) {
    if (err.code !== 'ENOENT') throw err;
  }
  return target;
}

async function executeDownload(page, step, options, refMap) {
  let target;
  try {
    target = await destination(options.outputDir, step.path);
  } catch (err) {
    if (err.message.startsWith('browser_download_path_invalid:')) throw err;
    throw new Error(refusePath().message + ' ' + err.message);
  }
  const timeout = step.timeout_ms || options.timeout || 5000;
  const locator = resolveTarget(page, step.target, refMap);
  let download;
  try {
    [download] = await Promise.all([
      page.waitForEvent('download', { timeout }),
      locator.click({ timeout }),
    ]);
  } catch (err) {
    throw new Error(
      `browser_download_not_received: no download completed its trigger within ${timeout}ms. `
      + 'Check the target and page state, or raise timeout_ms for a slower download. '
      + err.message
    );
  }
  try {
    await download.saveAs(target);
    const hash = createHash('sha256');
    let size = 0;
    for await (const chunk of createReadStream(target)) {
      hash.update(chunk);
      size += chunk.length;
    }
    return {
      success: true,
      download: {
        path: target, filename: download.suggestedFilename(),
        size_bytes: size, sha256: hash.digest('hex'),
      },
    };
  } catch (err) {
    throw new Error(
      'browser_download_save_failed: check scratch space and the download response, '
      + 'then retry the download step. ' + err.message
    );
  }
}

module.exports = { executeDownload };
