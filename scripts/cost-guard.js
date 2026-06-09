#!/usr/bin/env node
/*
 * cost-guard.js — ZTB deterministic spend circuit-breaker ($0 tokens, no LLM).
 * Run by a systemd user timer every 10 min. Reads config/cost.env.
 *
 * THREE-LAYER DEFENSE (the prepaid balance is the only guaranteed ceiling):
 *   Layer 0  prepaid DeepSeek balance — polled here as an INDEPENDENT cross-check
 *            (HALT if today's balance-delta exceeds the daily cap; covers the case
 *             where Paperclip metering ever under-reports).
 *   Layer 1  daily cost-guard (this script) — bounds a runaway to ~one day.
 *   Layer 2  per-agent budgetMonthlyCents (set in Paperclip; advisory unless verified).
 *
 * SAFETY (BD-13): a HALT pauses ONLY Paperclip LLM agents (and, on hard-cap,
 * stops the shared paperclip.service). It MUST NEVER stop `ztb run` or the
 * trading kill-switch — those are separate Board-owned units this guard does not
 * know about and never touches. Pausing compute must never abandon open positions.
 *
 * A trip LATCHES (writes logs/cost-guard.state) and RE-ASSERTS the pause every run
 * until an operator clears it (rm the state file). Daily baseline resets each UTC day.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');

const FIRM_DIR = process.env.ZTB_FIRM_DIR || '/home/ubuntu/zero-alpha';
const ENV_FILE = path.join(FIRM_DIR, 'config', 'cost.env');
const STATE_FILE = path.join(FIRM_DIR, 'logs', 'cost-guard.state');
const DAILY_FILE = path.join(FIRM_DIR, 'logs', 'cost-guard.daily.json');

function loadEnv(f) { const o = {}; try { for (const l of fs.readFileSync(f, 'utf8').split('\n')) { const m = l.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/); if (m) o[m[1]] = m[2]; } } catch (_) {} return o; }
const env = { ...loadEnv(ENV_FILE), ...process.env };
const API = (env.PAPERCLIP_API_URL || 'http://127.0.0.1:3100/api').replace(/\/$/, '');
const CID = env.PAPERCLIP_COMPANY_ID;
const WEBHOOK = env.DISCORD_WEBHOOK_URL;
const DS_KEY = env.DEEPSEEK_API_KEY;
const CAP = Number(env.COST_DAILY_CAP_CENTS || 110);
const ALERT = Number(env.COST_ALERT_PCT || 0.7);
const HALT = Number(env.COST_HALT_PCT || 0.9);
const MAX_TASKS = Number(env.COST_MAX_TASKS || 25);
const WINDOW_MIN = Number(env.COST_WINDOW_MIN || 20);
const MAX_CONC = Number(env.COST_MAX_CONCURRENT || 6);
const ACTIVE = new Set(['running', 'queued', 'in_progress', 'active']);

const today = () => new Date().toISOString().slice(0, 10);
async function api(method, p, body) {
  const r = await fetch(`${API}${p}`, { method, headers: { 'Content-Type': 'application/json' }, body: body !== undefined ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(`${method} ${p} -> ${r.status}`);
  return r.status === 204 ? {} : r.json();
}
const post = async (p) => { try { const r = await fetch(`${API}${p}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); return r.ok; } catch { return false; } };
const asList = (d) => (Array.isArray(d) ? d : (d && (d.agents || d.runs || d.issues || d.data)) || []);
async function discord(content) { if (!WEBHOOK) return; try { await fetch(WEBHOOK, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'ZTB cost-guard', content }) }); } catch (_) {} }
function stopPaperclip() { try { execFile('systemctl', ['--user', 'stop', 'paperclip.service'], () => {}); } catch (_) {} } // NEVER ztb run

async function pauseAllAgents() { let n = 0; for (const a of asList(await api('GET', `/companies/${CID}/agents`))) { if (await post(`/agents/${a.id}/pause`)) n++; } return n; }

// Layer 0: poll DeepSeek prepaid balance; track today's spend as an independent cross-check.
async function balanceDeltaCents(daily) {
  if (!DS_KEY) return null;
  try {
    const r = await fetch('https://api.deepseek.com/user/balance', { headers: { Authorization: `Bearer ${DS_KEY}` } });
    if (!r.ok) return null;
    const j = await r.json();
    const usd = (j.balance_infos || []).find((b) => /USD/i.test(b.currency)) || (j.balance_infos || [])[0];
    const bal = usd ? parseFloat(usd.total_balance) : null;
    if (bal == null || isNaN(bal)) return null;
    if (daily.balanceStartUsd == null) { daily.balanceStartUsd = bal; }
    return Math.max(0, Math.round((daily.balanceStartUsd - bal) * 100));
  } catch { return null; }
}

async function main() {
  if (!CID) { console.error('cost-guard: PAPERCLIP_COMPANY_ID missing'); process.exit(2); }
  const company = await api('GET', `/companies/${CID}`).catch(() => null);
  const spentNow = company ? (company.spentMonthlyCents || 0) : 0;

  // daily baseline (resets each UTC day)
  let daily = {}; try { daily = JSON.parse(fs.readFileSync(DAILY_FILE, 'utf8')); } catch (_) {}
  if (daily.date !== today()) daily = { date: today(), baselineSpentMonthlyCents: spentNow, balanceStartUsd: null };

  // --- latch handling: re-assert (same day) or auto-clear (new day, non-abuse) ---
  if (fs.existsSync(STATE_FILE)) {
    let st = {}; try { st = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch (_) {}
    const abuse = (st.reasons || []).some((r) => /task rate|concurrency|balance/i.test(String(r)));
    const newDay = String(st.haltedAt || '').slice(0, 10) !== today();
    if (newDay && !abuse && !st.hardCap) {
      fs.unlinkSync(STATE_FILE);
      fs.writeFileSync(DAILY_FILE, JSON.stringify({ date: today(), baselineSpentMonthlyCents: spentNow, balanceStartUsd: null }));
      await discord(':arrows_counterclockwise: ZTB cost-guard: new day — daily budget reset, agents may resume.');
      console.log('cost-guard: new day -> cleared daily-cap latch');
    } else {
      const re = await pauseAllAgents().catch(() => -1);
      console.log(`cost-guard: HALTED (re-asserted, re-paused ${re}); ${abuse || st.hardCap ? 'manual reset required' : 'auto-resumes next UTC day'}: rm ${STATE_FILE}`);
      return;
    }
  }

  const baseline = daily.baselineSpentMonthlyCents ?? spentNow;
  const dailySpend = Math.max(0, spentNow - baseline);
  const balDelta = await balanceDeltaCents(daily);
  fs.writeFileSync(DAILY_FILE, JSON.stringify(daily));

  // task rate + concurrency
  let taskRate = 0, conc = 0;
  try { const cutoff = Date.now() - WINDOW_MIN * 60000; taskRate = asList(await api('GET', `/companies/${CID}/issues?limit=200`)).filter((i) => new Date(i.createdAt).getTime() >= cutoff).length; } catch (_) {}
  try { conc = asList(await api('GET', `/companies/${CID}/heartbeat-runs?limit=100`)).filter((r) => ACTIVE.has(String(r.status || '').toLowerCase())).length; } catch (_) {}

  const reasons = [];
  const hardCap = dailySpend >= CAP || (balDelta != null && balDelta >= CAP);
  if (dailySpend >= HALT * CAP) reasons.push(`daily spend ${dailySpend}c >= ${Math.round(HALT * CAP)}c (${Math.round(HALT * 100)}% of ${CAP}c)`);
  if (balDelta != null && balDelta >= HALT * CAP) reasons.push(`balance-poll delta ${balDelta}c >= ${Math.round(HALT * CAP)}c (independent Layer-0 check)`);
  if (taskRate > MAX_TASKS) reasons.push(`task rate ${taskRate}/${WINDOW_MIN}min > ${MAX_TASKS}`);

  console.log(`cost-guard: dailySpend=${dailySpend}c balDelta=${balDelta == null ? '?' : balDelta + 'c'} tasks/${WINDOW_MIN}m=${taskRate} conc=${conc} | trips=${reasons.length}`);

  if (reasons.length) {
    const paused = await pauseAllAgents().catch(() => -1);
    if (hardCap) stopPaperclip();
    fs.writeFileSync(STATE_FILE, JSON.stringify({ halted: true, haltedAt: new Date().toISOString(), reasons, dailySpend, balDelta, taskRate, concurrency: conc, hardCap, agentsPaused: paused }, null, 2));
    await discord(`:rotating_light: **ZTB cost-guard HALT** — ${reasons.join('; ')}. Paused ${paused} agents${hardCap ? ' + stopped paperclip.service' : ''}. Manual reset: rm cost-guard.state. (ztb run / kill-switch untouched.)`);
    console.error('cost-guard: TRIPPED ->', reasons.join('; '));
    return;
  }
  // soft alert (once/day), concurrency warn
  if (dailySpend >= ALERT * CAP && daily.alertedDay !== today()) { daily.alertedDay = today(); fs.writeFileSync(DAILY_FILE, JSON.stringify(daily)); await discord(`:warning: ZTB cost-guard: daily spend ${dailySpend}c >= ${Math.round(ALERT * 100)}% of ${CAP}c.`); }
  if (conc > MAX_CONC) await discord(`:warning: ZTB cost-guard: concurrency ${conc} > ${MAX_CONC}.`);
}
main().catch((e) => { console.error('cost-guard error:', e.message); process.exit(1); });
