#!/usr/bin/env node
/*
 * skill_maint.js — ZTB skill-catalogue maintenance ($0 tokens, no LLM).
 * Weekly systemd timer. Reads memory/skills/INDEX.md; for any skill whose
 * last-verified date is older than STALE_DAYS (90), POSTs ONE task to the Head
 * of Research: "Re-verify or prune stale skill: <name>". Deduped (won't re-post
 * if an open task with that title already exists). Config (API URL + company id)
 * comes from the same cost.env the cost-guard reads. SKILL_MAINT_DRY=1 parses +
 * reports without posting. This keeps the catalogue small, fresh, and honest;
 * it never invents skills and never touches strategies.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const FIRM = process.env.ZTB_FIRM_DIR || '/home/ubuntu/zero-alpha';
const OPS = process.env.ZTB_OPS_DIR || '/home/ubuntu/ztb-ops';
const STALE_DAYS = Number(process.env.SKILL_STALE_DAYS || 90);
const DRY = /^(1|true|yes)$/i.test(process.env.SKILL_MAINT_DRY || '');

function loadEnv(f) { const o = {}; try { for (const l of fs.readFileSync(f, 'utf8').split('\n')) { const m = l.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/); if (m) o[m[1]] = m[2]; } } catch (_) {} return o; }
// read config the same way the cost-guard does (cost.env); prefer the ops dir, fall back to the firm dir
const env = { ...loadEnv(path.join(FIRM, 'config', 'cost.env')), ...loadEnv(path.join(OPS, 'config', 'cost.env')), ...process.env };
const API = (env.PAPERCLIP_API_URL || 'http://127.0.0.1:3100/api').replace(/\/$/, '');
const CID = env.PAPERCLIP_COMPANY_ID;
const INDEX = path.join(FIRM, 'memory', 'skills', 'INDEX.md');
const asList = (d) => (Array.isArray(d) ? d : (d && (d.agents || d.issues || d.data)) || []);

function parseIndex() {
  const out = [];
  let txt; try { txt = fs.readFileSync(INDEX, 'utf8'); } catch (e) { throw new Error('cannot read INDEX.md: ' + e.message); }
  for (const line of txt.split('\n')) {
    if (!/^\|/.test(line)) continue;
    const cols = line.split('|').map((c) => c.trim());
    // table rows look like: ['', name, type, tags, when, file, lastVerified, '']
    if (cols.length < 7) continue;
    const name = cols[1], last = cols[6];
    if (!/^\d{4}-\d{2}-\d{2}$/.test(last)) continue; // skips header + separator
    out.push({ name, last });
  }
  return out;
}

(async () => {
  if (!CID && !DRY) { console.error('skill-maint: PAPERCLIP_COMPANY_ID missing'); process.exit(2); }
  const skills = parseIndex();
  const now = Date.now();
  const stale = skills.filter((s) => (now - Date.parse(s.last + 'T00:00:00Z')) / 86400000 > STALE_DAYS);
  console.log(`skill-maint: parsed ${skills.length} skills; ${stale.length} stale (> ${STALE_DAYS} days)${DRY ? ' [DRY]' : ''}`);
  if (DRY || !stale.length) { stale.forEach((s) => console.log('  would flag:', s.name, '(' + s.last + ')')); return; }

  // find Head of Research + existing open flag tasks (dedup)
  const agents = asList(await (await fetch(`${API}/companies/${CID}/agents`)).json());
  const hor = agents.find((a) => /head of research/i.test(a.name || ''));
  if (!hor) { console.error('skill-maint: Head of Research not found'); return; }
  const open = asList(await (await fetch(`${API}/companies/${CID}/issues?limit=200`)).json())
    .filter((i) => !['done', 'cancelled'].includes(i.status)).map((i) => String(i.title || ''));
  let posted = 0;
  for (const s of stale) {
    const title = `Re-verify or prune stale skill: ${s.name}`;
    if (open.some((t) => t.includes(title))) { console.log('  already open:', s.name); continue; }
    const r = await fetch(`${API}/companies/${CID}/issues`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, assigneeAgentId: hor.id, priority: 'low', workMode: 'standard',
        description: `Skill memory/skills/${s.name}.md was last verified ${s.last} (> ${STALE_DAYS} days ago). Re-verify it is still accurate (re-check the source) and update its last-verified date in INDEX.md, OR prune it if obsolete. Keep the catalogue small. This is process/fact maintenance only — never a trading edge.` }) });
    if (r.ok) { posted++; console.log('  flagged:', s.name); }
  }
  console.log(`skill-maint: posted ${posted} re-verify task(s).`);
})().catch((e) => { console.error('skill-maint error:', e.message); process.exit(1); });
