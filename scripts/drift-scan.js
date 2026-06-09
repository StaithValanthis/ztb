#!/usr/bin/env node
/*
 * drift-scan.js — ZTB off-mandate / rogue-daemon watchdog ($0 tokens, no LLM).
 * Run by a systemd user timer (~15 min). The old firm's worst failure was agents
 * spawning persistent python trading daemons and registering minute-level routines.
 * Enforce: the ONLY sanctioned long-lived processes are paperclip + its postgres +
 * `ztb run` (Board-owned) + named systemd services; the ONLY sanctioned Paperclip
 * routine is the single MD R&D review. Anything else -> Discord alert (no auto-kill;
 * the Board decides, so this never fights manual control).
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const FIRM_DIR = process.env.ZTB_FIRM_DIR || '/home/ubuntu/zero-alpha';
function loadEnv(f) { const o = {}; try { for (const l of fs.readFileSync(f, 'utf8').split('\n')) { const m = l.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/); if (m) o[m[1]] = m[2]; } } catch (_) {} return o; }
const env = { ...loadEnv(path.join(FIRM_DIR, 'config', 'cost.env')), ...process.env };
const API = (env.PAPERCLIP_API_URL || 'http://127.0.0.1:3100/api').replace(/\/$/, '');
const CID = env.PAPERCLIP_COMPANY_ID, WEBHOOK = env.DISCORD_WEBHOOK_URL;
const STATE = path.join(FIRM_DIR, 'logs', 'drift-scan.json');
const asList = (d) => (Array.isArray(d) ? d : (d && (d.routines || d.data)) || []);
async function discord(c) { if (!WEBHOOK) return; try { await fetch(WEBHOOK, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'ZTB drift-scan', content: c }) }); } catch (_) {} }

// long-lived processes (>5 min) that are SANCTIONED
const SANCTIONED = /paperclipai|postgres|\bztb\b run|systemd|sshd|node \/home\/ubuntu\/\.npm-global/i;

(async () => {
  const findings = [];
  // 1. rogue long-lived processes
  try {
    const ps = execSync("ps -eo etimes,comm,args --no-headers", { encoding: 'utf8' }).split('\n');
    for (const line of ps) {
      const m = line.trim().match(/^(\d+)\s+(\S+)\s+(.*)$/); if (!m) continue;
      const [, et, , args] = m;
      if (Number(et) > 300 && /python|node|streamlit/i.test(args) && !SANCTIONED.test(args) && !/drift-scan|cost-guard|cost-report/.test(args)) {
        findings.push(`rogue long-lived process (${et}s): ${args.slice(0, 90)}`);
      }
    }
  } catch (_) {}
  // 2. unexpected user crontab (agents must not register cron)
  try { const cron = execSync('crontab -l 2>/dev/null || true', { encoding: 'utf8' }).split('\n').filter((l) => l && !l.startsWith('#')); if (cron.length) findings.push(`user crontab has ${cron.length} entries (agents must not register cron): ${cron[0].slice(0, 60)}`); } catch (_) {}
  // 3. Paperclip routines — expect exactly ONE (the MD R&D review)
  try { const r = asList(await (await fetch(`${API}/companies/${CID}/routines`)).json()); if (r.length > 1) findings.push(`Paperclip has ${r.length} routines (only the single MD R&D review is sanctioned)`); } catch (_) {}

  let seen = {}; try { seen = JSON.parse(fs.readFileSync(STATE, 'utf8')); } catch (_) {}
  const key = findings.join('|');
  if (findings.length && seen.lastKey !== key) {
    await discord(`:warning: **ZTB drift-scan** — off-mandate activity detected:\n- ${findings.join('\n- ')}\nBoard: investigate (no auto-kill).`);
    fs.writeFileSync(STATE, JSON.stringify({ lastKey: key, at: new Date().toISOString() }));
    console.log('drift-scan: ALERTED ->', findings.join('; '));
  } else { if (!findings.length && seen.lastKey) fs.writeFileSync(STATE, JSON.stringify({ lastKey: '', at: new Date().toISOString() })); console.log(`drift-scan: ok (${findings.length} findings)`); }
})();
