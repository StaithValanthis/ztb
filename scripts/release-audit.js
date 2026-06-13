#!/usr/bin/env node
/*
 * release-audit.js — verify a release tag's CI status before audit sign-off.
 *
 * Usage:
 *   node scripts/release-audit.js --tag v1.0.5
 *
 * Exit codes:
 *   0 — CI success
 *   1 — CI failure
 *   2 — CI pending
 *   3 — no CI checks found for this SHA
 *
 * Optional integrity warnings (non-failing):
 *   - Version consistency: tag version matches ztb.__version__
 *   - CHANGELOG entry exists for this version
 */
'use strict';
const { execSync } = require('child_process');

const tagIdx = process.argv.indexOf('--tag');
const TAG = tagIdx !== -1 && tagIdx + 1 < process.argv.length
  ? process.argv[tagIdx + 1]
  : (process.argv.find((a) => a.startsWith('--tag=')) || '').split('=')[1];

if (!TAG) {
  console.error('release-audit: --tag is required');
  process.exit(3);
}

/** Run a command and return trimmed stdout. */
function run(cmd, opts = {}) {
  try {
    return execSync(cmd, { encoding: 'utf8', timeout: 15000, ...opts }).trim();
  } catch (e) {
    return '';
  }
}

/** Get a JSON field from `gh api` output. */
function gh(path) {
  try {
    const raw = execSync(`gh api "${path}"`, { encoding: 'utf8', timeout: 30000 });
    return JSON.parse(raw);
  } catch { return null; }
}

// ---- resolve tag to SHA ----
const sha = run(`git rev-parse "${TAG}"^{commit}`);
if (!sha) {
  console.error(`release-audit: tag "${TAG}" not found or not a valid commit`);
  process.exit(3);
}
console.log(`release-audit: tag=${TAG} sha=${sha.slice(0, 12)}`);

// ---- owner/repo from git remote ----
const remoteUrl = run('git remote get-url origin');
let owner = '', repo = '';
const m = remoteUrl.match(/github\.com[:\/]([^\/]+)\/([^\.]+)/);
if (m) { owner = m[1]; repo = m[2].replace('.git', ''); }
if (!owner || !repo) {
  console.error('release-audit: cannot parse owner/repo from remote');
  process.exit(3);
}

// ---- integrity: version match ----
const tagVer = TAG.replace(/^v/, '');
try {
  const src = require('fs').readFileSync('ztb/__init__.py', 'utf8');
  const verMatch = src.match(/__version__\s*=\s*"([^"]+)"/);
  if (verMatch && verMatch[1] !== tagVer) {
    console.warn(`WARNING: tag version "${tagVer}" != ztb.__version__ "${verMatch[1]}"`);
  }
} catch (_) { /* skip if file not accessible */ }

// ---- integrity: CHANGELOG entry ----
try {
  const cl = require('fs').readFileSync('CHANGELOG.md', 'utf8');
  if (!cl.includes(`## ${TAG}`) && !cl.includes(`## v${tagVer}`)) {
    console.warn(`WARNING: no CHANGELOG entry found for ${TAG}`);
  }
} catch (_) { /* skip if file not accessible */ }

// ---- fetch CI check runs ----
const data = gh(`/repos/${owner}/${repo}/commits/${sha}/check-runs?per_page=100`);
if (!data) {
  console.error('release-audit: failed to fetch CI check runs');
  process.exit(3);
}

const runs = (data.check_runs || []).filter((r) => r.name !== 'ztb/vr-pass');

if (runs.length === 0) {
  console.log(`release-audit: no CI checks found for ${sha.slice(0, 12)}`);
  process.exit(3);
}

const conclusions = runs.map((r) => r.conclusion || r.status || 'unknown');
const failures = conclusions.filter((c) => ['failure', 'cancelled', 'timed_out'].includes(c));
const pending = conclusions.filter((c) => !['success', 'failure', 'neutral', 'cancelled', 'timed_out', 'skipped'].includes(c));

runs.forEach((r) => {
  const c = r.conclusion || r.status || 'unknown';
  console.log(`  ${r.name}: ${c}`);
});

if (failures.length > 0) {
  console.log(`release-audit: FAILURE (${failures.length} check(s) failed)`);
  process.exit(1);
}
if (pending.length > 0) {
  console.log(`release-audit: PENDING (${pending.length} check(s) not yet complete)`);
  process.exit(2);
}

console.log(`release-audit: SUCCESS — all ${runs.length} CI check(s) passed`);
process.exit(0);
