#!/usr/bin/env node
/*
 * cost-report.js — ZTB daily cost digest to Discord ($0 tokens, no LLM).
 * Run by a systemd user timer at 22:00. Owned by Head of Operations (informational;
 * Ops may only tighten/recommend caps, never raise them). Reads config/cost.env.
 * Reports MTD spend, % of the 10-agent soft cap, top spenders, prepaid balance, and
 * token cache hit-rate (the cache is the cost lever — surface it).
 */
'use strict';
const fs = require('fs');
const path = require('path');
const FIRM_DIR = process.env.ZTB_FIRM_DIR || '/home/ubuntu/zero-alpha';
function loadEnv(f) { const o = {}; try { for (const l of fs.readFileSync(f, 'utf8').split('\n')) { const m = l.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/); if (m) o[m[1]] = m[2]; } } catch (_) {} return o; }
const env = { ...loadEnv(path.join(FIRM_DIR, 'config', 'cost.env')), ...process.env };
const API = (env.PAPERCLIP_API_URL || 'http://127.0.0.1:3100/api').replace(/\/$/, '');
const CID = env.PAPERCLIP_COMPANY_ID, WEBHOOK = env.DISCORD_WEBHOOK_URL, DS_KEY = env.DEEPSEEK_API_KEY;
const SOFT = Number(env.COST_SOFT_CAP_CENTS || 2640);
const asList = (d) => (Array.isArray(d) ? d : (d && (d.agents || d.runs || d.data)) || []);
const g = async (p) => { try { return await (await fetch(`${API}${p}`)).json(); } catch { return null; } };

(async () => {
  if (!WEBHOOK) { console.log('cost-report: no webhook'); return; }
  const company = await g(`/companies/${CID}`) || {};
  const mtd = company.spentMonthlyCents || 0;
  const agents = asList(await g(`/companies/${CID}/agents`)).filter((a) => a.name !== 'Smoke Test')
    .sort((a, b) => (b.spentMonthlyCents || 0) - (a.spentMonthlyCents || 0));
  const top = agents.slice(0, 5).map((a) => `${a.name} ${a.spentMonthlyCents || 0}c`).join(', ');
  // balance
  let bal = '?'; if (DS_KEY) { try { const r = await fetch('https://api.deepseek.com/user/balance', { headers: { Authorization: `Bearer ${DS_KEY}` } }); if (r.ok) { const j = await r.json(); const u = (j.balance_infos || [])[0]; if (u) bal = `${u.total_balance} ${u.currency}`; } } catch (_) {} }
  // cache hit-rate over recent runs
  let inTok = 0, cached = 0, out = 0, costUsd = 0, runs = 0;
  for (const r of asList(await g(`/companies/${CID}/heartbeat-runs?limit=100`))) {
    const u = r.usageJson; if (!u) continue; runs++;
    inTok += u.rawInputTokens || u.inputTokens || 0; cached += u.cachedInputTokens || 0; out += u.outputTokens || 0; costUsd += u.costUsd || 0;
  }
  const hitRate = inTok + cached > 0 ? Math.round((cached / (inTok + cached)) * 100) : 0;
  const msg = [
    `:bar_chart: **ZTB daily cost digest**`,
    `MTD spend: **${mtd}c** / soft cap ${SOFT}c (${Math.round((mtd / SOFT) * 100)}%)`,
    `Prepaid balance: **${bal}** (Layer-0 hard wall)`,
    `Top spenders: ${top || '(none yet)'}`,
    `Recent ${runs} runs: cache hit-rate ${hitRate}%, ~$${costUsd.toFixed(4)} USD, out ${out} tok`,
  ].join('\n');
  try { await fetch(WEBHOOK, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'ZTB cost-report', content: msg }) }); console.log('cost-report: sent'); } catch (e) { console.error('cost-report:', e.message); }
})();
