from __future__ import annotations

from html import escape
from typing import Any
import json


STYLE = """
:root{
  color-scheme:light;
  --bg:#f3f6f8;--surface:#ffffff;--surface-2:#edf2f5;--surface-3:#e4ebef;
  --text:#17222b;--muted:#60717d;--line:#ccd7dd;--line-strong:#aebdc6;
  --accent:#087e8b;--accent-strong:#075f69;--accent-soft:#d8f0f2;
  --info:#2856a3;--info-soft:#e7eefb;--good:#167347;--good-soft:#e1f3e9;
  --warn:#9a5a00;--warn-soft:#fff1d6;--bad:#a8323a;--bad-soft:#fbe7e8;
  --shadow:0 1px 2px rgba(21,35,45,.08),0 10px 30px rgba(21,35,45,.05);
  --radius:12px;--mono:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;
  --sans:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#0b1217;--surface:#111b22;--surface-2:#17242d;--surface-3:#1d2d37;
  --text:#e7eef2;--muted:#9aabb6;--line:#2a3b46;--line-strong:#415660;
  --accent:#55c5cd;--accent-strong:#7bd8de;--accent-soft:#163a3e;
  --info:#91b7ff;--info-soft:#1b2d4c;--good:#72d6a2;--good-soft:#183b2b;
  --warn:#f2bd68;--warn-soft:#3f2d14;--bad:#ff9ba1;--bad-soft:#441f25;
  --shadow:0 1px 2px rgba(0,0,0,.24),0 14px 36px rgba(0,0,0,.18);
}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{background:var(--bg);scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font:1rem/1.55 var(--sans)}
a{color:var(--accent-strong);text-underline-offset:3px}
a:hover{text-decoration-thickness:2px}
button,input,select,textarea{font:inherit}
button,input,select,textarea{border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--text);padding:.62rem .72rem}
button{cursor:pointer;background:var(--surface-2);font-weight:650}
button:hover:not(:disabled){border-color:var(--accent);background:var(--accent-soft)}
button:disabled{cursor:not-allowed;opacity:.48}
:focus-visible{outline:3px solid color-mix(in srgb,var(--accent) 55%,transparent);outline-offset:2px}
.site-header{border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--surface) 94%,transparent);position:sticky;top:0;z-index:20;backdrop-filter:blur(14px)}
.header-inner{max-width:1500px;margin:auto;padding:1rem 1.5rem;display:flex;align-items:center;gap:1.5rem}
.brand{min-width:15rem}.brand a{color:var(--text);text-decoration:none}.eyebrow{text-transform:uppercase;letter-spacing:.12em;color:var(--accent-strong);font-size:.7rem;font-weight:800}
.brand strong{display:block;font-size:1.08rem;line-height:1.2}
nav{display:flex;align-items:center;gap:.35rem;flex-wrap:wrap;margin-left:auto}
nav a{padding:.45rem .65rem;border-radius:7px;color:var(--muted);text-decoration:none;font-weight:650}
nav a:hover{background:var(--surface-2);color:var(--text)}
.theme-toggle{min-width:9.25rem;white-space:nowrap;flex:0 0 auto}
main{max-width:1500px;margin:auto;padding:1.4rem 1.5rem 4rem}
.page-heading{display:flex;align-items:end;justify-content:space-between;gap:1rem;margin:0 0 1.2rem}
.page-heading h1{font-size:clamp(1.7rem,3vw,2.5rem);line-height:1.08;margin:.15rem 0}
.page-heading p{color:var(--muted);max-width:66ch;margin:.25rem 0 0}
h1,h2,h3{letter-spacing:-.018em}h2{font-size:1.2rem;margin:0 0 .75rem}h3{font-size:1rem;margin:0 0 .5rem}
section,.panel{margin:0 0 1rem;padding:1.1rem;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
.section-heading{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.8rem}
.section-heading p{margin:0;color:var(--muted)}.section-heading>a{white-space:nowrap}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr));gap:.8rem}
.grid.two{grid-template-columns:repeat(2,minmax(0,1fr))}
.stack{display:grid;gap:.8rem}.split{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(280px,.65fr);gap:1rem}
.metric{padding:.82rem;background:var(--surface-2);border:1px solid var(--line);border-radius:9px;min-width:0}
.metric small{display:block;color:var(--muted);font-size:.75rem;margin-bottom:.24rem}
.metric strong{display:block;font-size:1.05rem;overflow-wrap:anywhere}
.metric.emphasis{background:var(--accent-soft);border-color:color-mix(in srgb,var(--accent) 38%,var(--line))}
.metric.danger{background:var(--bad-soft)}
.badge,.chip{display:inline-flex;align-items:center;gap:.3rem;border:1px solid var(--line);border-radius:999px;padding:.18rem .48rem;font-size:.74rem;font-weight:750;line-height:1.3}.badge{white-space:nowrap}.chip{max-width:100%;white-space:normal;overflow-wrap:anywhere}
.badge.good{background:var(--good-soft);color:var(--good);border-color:transparent}.badge.bad{background:var(--bad-soft);color:var(--bad);border-color:transparent}
.badge.warn{background:var(--warn-soft);color:var(--warn);border-color:transparent}.badge.info{background:var(--info-soft);color:var(--info);border-color:transparent}
.badge.neutral{background:var(--surface-2);color:var(--muted)}.chips{display:flex;flex-wrap:wrap;gap:.3rem}.nested-object{min-width:0;padding:.45rem;border:1px solid var(--line);border-radius:7px;background:var(--surface)}
.notice{min-height:1.2rem;color:var(--warn);font-weight:650}.error-state{padding:1rem;background:var(--bad-soft);color:var(--bad);border-radius:8px}
.empty-state{padding:2rem;text-align:center;color:var(--muted);border:1px dashed var(--line-strong);border-radius:9px}
.mono,.id{font-family:var(--mono);font-size:.86em}.id{overflow-wrap:anywhere}.id-value{display:inline-flex;align-items:center;gap:.3rem;max-width:100%}
.copy-id{min-height:2rem;padding:.2rem .42rem;font-size:.68rem;font-weight:700;color:var(--muted);background:transparent}
.truncate{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;overflow:hidden}
.table-wrap{max-width:100%;overflow:auto;border:1px solid var(--line);border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:.86rem}th,td{text-align:left;padding:.68rem .72rem;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--surface-2);color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;white-space:nowrap}
tbody tr:last-child td{border-bottom:0}tbody tr:hover{background:color-mix(in srgb,var(--accent-soft) 35%,transparent)}
.semantic-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:.5rem;margin:.55rem 0}
.semantic-field{min-width:0;padding:.58rem;background:var(--surface-2);border-radius:7px}
.semantic-field dt{font-size:.72rem;color:var(--muted);margin-bottom:.14rem}.semantic-field dd{margin:0;overflow-wrap:anywhere;font-weight:620}
.decision-list{display:grid;gap:.75rem}.decision-card,.suite-card,.turn-card{border:1px solid var(--line);border-radius:10px;padding:.9rem;background:var(--surface)}
.decision-head,.card-head{display:flex;justify-content:space-between;align-items:start;gap:.75rem}.decision-head h3,.card-head h3{margin:.05rem 0}.meta{font-size:.78rem;color:var(--muted)}
.decision-rationale{margin:.6rem 0;color:var(--text);max-width:88ch}
.effect{margin-top:.7rem;padding:.72rem;border-left:3px solid var(--info);background:var(--surface-2);border-radius:0 8px 8px 0}
.effect.good{border-color:var(--good)}.effect.bad{border-color:var(--bad)}.effect.warn{border-color:var(--warn)}
details{margin-top:.55rem;border-top:1px solid var(--line);padding-top:.55rem}summary{cursor:pointer;color:var(--accent-strong);font-weight:650}
pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:24rem;overflow:auto;background:var(--surface-2);border:1px solid var(--line);border-radius:8px;padding:.75rem;font:12px/1.5 var(--mono)}
label{display:grid;gap:.28rem;color:var(--muted);font-size:.82rem;font-weight:650}label input,label select,label textarea{color:var(--text);font-weight:400}
textarea{min-height:6rem;resize:vertical}.form-actions,.toolbar{display:flex;gap:.55rem;align-items:center;flex-wrap:wrap;margin-top:.8rem}
fieldset{border:1px solid var(--line);border-radius:10px;padding:1rem;margin:0 0 1rem}legend{font-weight:750;padding:0 .4rem}
.arm{position:relative;padding:.8rem;background:var(--surface-2);border-radius:9px;margin-bottom:.6rem}
.primary{background:var(--accent);border-color:var(--accent);color:#fff}.primary:hover:not(:disabled){background:var(--accent-strong);color:#fff}
.danger-button{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 40%,var(--line))}
.plan-callout{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.65rem;padding:1rem;background:var(--accent-soft);border:1px solid color-mix(in srgb,var(--accent) 38%,var(--line));border-radius:10px}
.plan-callout strong{font-size:1.4rem}.plan-callout span{display:block;color:var(--muted);font-size:.76rem}
.bar-row{display:grid;grid-template-columns:minmax(120px,220px) minmax(100px,1fr) auto;gap:.55rem;align-items:center;margin:.38rem 0}
.bar-track{height:.65rem;background:var(--surface-3);border-radius:99px;overflow:hidden}.bar-fill{height:100%;background:var(--accent);border-radius:99px}.bar-fill.cost{background:#8a64c7}.bar-fill.latency{background:#d28a32}
.answer{min-height:14rem}.answer h3{font-size:1.08rem}.answer .decision-card{height:100%}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:1100px){
  .header-inner{display:grid;grid-template-columns:1fr auto;align-items:center}.brand{min-width:0}
  nav{grid-column:1/-1;grid-row:2;margin:0;justify-content:flex-start;border-top:1px solid var(--line);padding-top:.45rem}
  .theme-toggle{grid-column:2;grid-row:1}
}
@media(max-width:900px){.split,.grid.two{grid-template-columns:1fr}.plan-callout{grid-template-columns:1fr}.hide-tablet{display:none}}
@media(max-width:700px){
  .site-header{position:static}.header-inner{padding:.8rem 1rem;display:grid;grid-template-columns:minmax(0,1fr) auto}.brand{grid-column:1}
  .brand strong a{display:inline-flex;align-items:center;min-height:2.75rem}
  nav{grid-column:1/-1;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));margin:0;overflow:visible;padding:.55rem 0 .1rem;gap:.3rem}nav a{min-height:2.75rem;display:grid;place-items:center;text-align:center;white-space:nowrap;font-size:.9rem}.theme-toggle{grid-column:2;grid-row:1;min-width:auto;min-height:2.75rem;padding:.52rem .62rem;font-size:.8rem;white-space:nowrap}
  input,select,button,.copy-id,.section-heading>a,.form-actions>a{min-height:2.75rem}
  .section-heading>a,.form-actions>a{display:inline-flex;align-items:center}
  main{padding:1rem .75rem 3rem}.page-heading{align-items:start}.page-heading h1{font-size:1.75rem}
  section,.panel{padding:.85rem;border-radius:10px}.grid{grid-template-columns:1fr}.table-wrap{border-radius:8px}
  .responsive-table table,.responsive-table thead,.responsive-table tbody,.responsive-table tr,.responsive-table th,.responsive-table td{display:block}
  .responsive-table thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
  .responsive-table tr{padding:.7rem;border-bottom:1px solid var(--line)}.responsive-table tr:last-child{border:0}
  .responsive-table td{display:grid;grid-template-columns:8rem minmax(0,1fr);gap:.65rem;padding:.3rem 0;border:0}
  .responsive-table td::before{content:attr(data-label);color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;font-weight:750}
  .bar-row{grid-template-columns:1fr auto}.bar-track{grid-column:1/-1}.decision-head,.card-head{display:grid}.form-actions button{flex:1 1 auto}
}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""


THEME_HEAD = """
<script>
(() => {
  const saved = localStorage.getItem('sglab-theme');
  const theme = saved === 'light' || saved === 'dark'
    ? saved : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.dataset.theme = theme;
})();
</script>
"""


COMMON_JS = r"""
const fragmentToken=new URLSearchParams(location.hash.slice(1)).get('token');
if(fragmentToken){
  sessionStorage.setItem('sglab-dashboard-token',fragmentToken);
  history.replaceState(null,'',location.pathname+location.search);
}
const token=fragmentToken||sessionStorage.getItem('sglab-dashboard-token');
const headers={'Content-Type':'application/json',...(token?{'Authorization':`Bearer ${token}`}:{})};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=v=>v===null||v===undefined?'Unavailable':Number(v).toLocaleString();
const fmtSeconds=v=>v===null||v===undefined?'Unavailable':`${Number(v).toLocaleString(undefined,{maximumFractionDigits:2})} s`;
const label=v=>String(v??'').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
const shortId=v=>{const s=String(v??'');return s.length>20?`${s.slice(0,11)}…${s.slice(-6)}`:s};
const safeJson=v=>{if(v===null||v===undefined||v==='')return null;if(typeof v==='object')return v;try{return JSON.parse(v)}catch{return null}};
const actionSpaceLabels=v=>{const parsed=safeJson(v);const actions=Array.isArray(parsed)?parsed:parsed?.actions;return Array.isArray(actions)?actions.map(label).join(', '):''};
const statusTone=v=>{const s=String(v??'').toLowerCase();if(/complete|valid|pass|applied|authorized|prepared/.test(s))return'good';if(/fail|invalid|reject|abort/.test(s))return'bad';if(/time|stop|block|pause|unknown/.test(s))return'warn';return'neutral'};
const badge=v=>`<span class="badge ${statusTone(v)}">${esc(label(v??'unknown'))}</span>`;
const idHtml=v=>v?`<span class="id-value"><span class="id" title="${esc(v)}">${esc(shortId(v))}</span><button type="button" class="copy-id" data-copy="${esc(v)}" aria-label="Copy full identifier">Copy</button></span>`:'—';
const field=(k,v)=>{const technicalKey=/(^|[\s_-])(id|ids|hash|sha-?256|fingerprint)($|[\s_-])|prompt|director state|output schema/i.test(k);return v===null||v===undefined||v===''?'':`<div class="semantic-field"><dt>${esc(label(k))}</dt><dd>${typeof v==='string'&&technicalKey?idHtml(v):esc(v)}</dd></div>`};
const technical=(title,value)=>value===null||value===undefined||value===''?'':`<details><summary>${esc(title)}</summary><pre>${esc(typeof value==='string'?value:JSON.stringify(value,null,2))}</pre></details>`;
async function api(path,options={}){const r=await fetch(path,{...options,headers:{...headers,...(options.headers||{})},cache:'no-store'});let b;try{b=await r.json()}catch{b={error:`HTTP ${r.status}`}}if(!r.ok)throw new Error(b.error||`HTTP ${r.status}`);return b}
function themeLabel(){const dark=document.documentElement.dataset.theme==='dark';const b=document.getElementById('theme-toggle');if(b){b.textContent=dark?'☀ Light theme':'☾ Dark theme';b.setAttribute('aria-pressed',String(dark))}}
document.getElementById('theme-toggle').addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=next;localStorage.setItem('sglab-theme',next);themeLabel()});themeLabel();
document.addEventListener('click',async event=>{const button=event.target.closest('[data-copy]');if(!button)return;try{await navigator.clipboard.writeText(button.dataset.copy);const old=button.textContent;button.textContent='Copied';setTimeout(()=>button.textContent=old,900)}catch{button.title='Copy unavailable in this browser context'}});
function semanticValue(value,key=''){
  if(value===null||value===undefined||value==='')return '';
  if(typeof value==='boolean')return value?'Yes':'No';
  if(typeof value==='number'){
    if(/share|diversity|rate|weight|confidence|yield/.test(key)&&Math.abs(value)<=1)return `${(value*100).toFixed(1)}%`;
    if(/seconds|latency|elapsed|wall/.test(key))return fmtSeconds(value);
    return Number(value).toLocaleString(undefined,{maximumFractionDigits:4});
  }
  if(Array.isArray(value)){
    if(value.some(x=>x&&typeof x==='object'))return `<div class="stack">${value.map(x=>`<div class="nested-object">${semanticValue(x,key)}</div>`).join('')}</div>`;
    return `<div class="chips">${value.map(x=>`<span class="chip" title="${esc(x)}">${esc(shortId(x))}</span>`).join('')}</div>`;
  }
  if(typeof value==='object')return semanticFields(value);
  return esc(value);
}
function semanticFields(obj){
  if(!obj||typeof obj!=='object')return '';
  const rows=Object.entries(obj).filter(([,v])=>v!==null&&v!==undefined&&v!=='');
  return `<dl class="semantic-list">${rows.map(([k,v])=>`<div class="semantic-field"><dt>${esc(label(k))}</dt><dd>${semanticValue(v,k)}</dd></div>`).join('')}</dl>`;
}
function actionName(type){return ({start_lane:'Start search lane',request_diagnostic:'Request diagnostic',set_review_trigger:'Set review trigger',promote_candidate:'Promote candidate',schedule_verification:'Schedule verification',stop_lane:'Stop search lane',patch_lane:'Change lane strategy',restart_lane:'Restart lane',fork_lane:'Fork lane',reallocate_resources:'Reallocate resources'})[type]||label(type||'Decision')}
function actionBody(action){
  const type=action.type||action.action_type||'decision';
  const source=action.spec?.spec||action.spec||action.parameters?.spec||action.parameters||{};
  const params=source.parameters||source.patch||source.review_trigger||source;
  let headline='';
  if(type==='start_lane')headline=field('Algorithm',label(source.algorithm))+field('Graph family',label(source.graph_family))+field('Seed',source.seed);
  else if(type==='request_diagnostic')headline=field('Diagnostic type',label(source.diagnostic_type||params.diagnostic_type))+field('Subjects',(source.subject_ids||params.subject_ids||[]).map(shortId).join(', '));
  else if(type==='schedule_verification')headline=field('Candidates',(source.candidate_ids||params.candidate_ids||[]).map(shortId).join(', '))+field('Priority',source.verification_priority||params.verification_priority);
  else if(type==='promote_candidate')headline=field('Candidate',source.candidate_id||params.candidate_id);
  else if(type==='set_review_trigger')headline=field('Event',params.event)+field('After evaluations',params.after_evaluations)+field('Minimum diversity',params.minimum_diversity);
  else if(type==='stop_lane')headline=field('Lane',action.target_lane_id||source.lane_id);
  else headline=field('Target lane',action.target_lane_id)+field('Candidate',source.candidate_id);
  const clean={...params};['algorithm','graph_family','seed','diagnostic_type','subject_ids','candidate_ids','candidate_id','verification_priority','event','after_evaluations','minimum_diversity','lane_id'].forEach(k=>delete clean[k]);
  return `<dl class="semantic-list">${headline}</dl>${Object.keys(clean).length?`<h4>Controls</h4>${semanticFields(clean)}`:''}`;
}
function decisionCard(decision,meta={}){
  const parsed=safeJson(decision)||{};
  const actions=parsed.actions||[];
  if(!actions.length&&meta.selected_action)actions.push({type:meta.selected_action,spec:safeJson(meta.selected_parameters_json)||{},rationale:meta.rationale});
  if(!actions.length)return `<div class="empty-state">No structured decision is available.</div>`;
  return actions.map(a=>`<article class="decision-card"><div class="decision-head"><div><span class="eyebrow">Director action</span><h3>${esc(actionName(a.type||a.action_type))}</h3></div><div class="chips">${meta.lifecycle_status?badge(meta.lifecycle_status):''}${meta.schema_valid!==undefined?badge(meta.schema_valid?'schema valid':'schema invalid'):''}${meta.semantic_valid!==undefined?badge(meta.semantic_valid?'semantic valid':'semantic invalid'):''}</div></div>${a.rationale?`<p class="decision-rationale">${esc(a.rationale)}</p>`:''}${actionBody(a)}${technical('Technical decision JSON',a)}</article>`).join('');
}
"""


def page(title: str, content: str, script: str = "", *, subtitle: str = "") -> bytes:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} — Structural Graph Lab</title>{THEME_HEAD}<style>{STYLE}</style></head>
<body><header class="site-header"><div class="header-inner"><div class="brand"><span class="eyebrow">Structural Graph Lab</span><strong><a href="/">Research control room</a></strong></div>
<nav aria-label="Primary navigation"><a href="/">Dashboard</a><a href="/comparisons">Comparisons</a><a href="/comparisons/new">New suite</a><a href="/model-cost-profiles">Cost profiles</a></nav>
<button type="button" id="theme-toggle" class="theme-toggle" aria-label="Toggle color theme"></button></div></header>
<main><div class="page-heading"><div><span class="eyebrow">Auditable workspace</span><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div></div>{content}<p id="notice" class="notice" role="status" aria-live="polite"></p></main>
<script>{COMMON_JS}
{script}
</script></body></html>""".encode("utf-8")


def error_page(status: int, title: str, message: str) -> bytes:
    content = f"""
<section><div class="error-state"><span class="eyebrow">HTTP {status}</span><h2>{escape(title)}</h2>
<p>{escape(message)}</p><div class="form-actions"><a href="/">Return to dashboard</a><a href="/comparisons">Browse comparisons</a></div></div></section>
"""
    return page(
        f"{status} — {title}",
        content,
        subtitle="The requested page could not be displayed.",
    )


def comparisons_page() -> bytes:
    content = """
<section><div class="section-heading"><div><h2>Filter suites</h2><p>Find comparable runs without losing the scientific context.</p></div></div>
<form id="filters" class="grid">
<label>Model<input name="model" placeholder="e.g. gpt-5.6-luna"></label><label>Effort<input name="effort" placeholder="medium, high, xhigh"></label>
<label>Context mode<input name="context_mode" placeholder="stateless_turns"></label><label>Fixture<input name="fixture" placeholder="fixture ID"></label>
<label>Status<input name="status" placeholder="completed"></label><button class="primary">Apply filters</button></form></section>
<section><div class="section-heading"><div><h2>Comparison suites</h2><p id="suite-count">Loading suites…</p></div><a href="/comparisons/new">Create suite →</a></div><div id="suite-list" class="stack"></div></section>
"""
    script = """
function suiteCard(s){return `<article class="suite-card"><div class="card-head"><div><div class="chips">${badge(s.status)}${s.measurement_only?badge('measurement only'):badge('execution')}</div><h3><a href="/comparisons/${esc(s.suite_id)}#${location.hash.slice(1)}">${esc(s.name)}</a></h3><div class="meta">${idHtml(s.suite_id)} · created ${esc(s.created_at)}</div></div><div class="metric emphasis"><small>Completed turns</small><strong>${s.completion_count} / ${s.planned_inference_count}</strong></div></div><div class="grid">${field('Fixture',s.fixture_reference)}${field('Models',s.models.join(', '))}${field('Efforts',s.efforts.join(', '))}${field('Context modes',s.context_modes.join(', '))}${field('Inference starts',`${s.consumed_inference_starts||0} / ${s.maximum_inference_starts}`)}${field('Total server tokens',fmt(s.total_server_tokens))}${field('Relative cost units',Number(s.relative_cost_units||0).toFixed(2))}${field('Timeouts / invalid',`${s.timeout_count} / ${s.invalid_decision_count}`)}</div></article>`}
async function load(){try{const q=new URLSearchParams(new FormData(document.getElementById('filters')));const d=await api('/api/comparisons?'+q);document.getElementById('suite-count').textContent=`${d.suites.length} suite${d.suites.length===1?'':'s'}`;document.getElementById('suite-list').innerHTML=d.suites.map(suiteCard).join('')||'<div class="empty-state"><strong>No comparison suites match these filters.</strong><p>Clear a filter or create a new measurement-only suite.</p></div>'}catch(e){notice.textContent=e.message}}
document.getElementById('filters').addEventListener('submit',e=>{e.preventDefault();load()});load();
"""
    return page(
        "Controlled comparisons",
        content,
        script,
        subtitle="Compare model, reasoning effort, and context mode under an immutable measurement-only plan.",
    )


def new_comparison_page(catalog: dict[str, list[str]], fixtures: list[dict[str, Any]]) -> bytes:
    fixture_options = "".join(
        f'<option value="{escape(str(row["fixture_id"]))}">{escape(str(row["display_name"]))}</option>'
        for row in fixtures
    )
    catalog_json = json.dumps(catalog, sort_keys=True)
    content = f"""
<section class="panel"><div class="plan-callout"><div><span>Decision execution</span><strong>Disabled</strong></div><div><span>Default mode</span><strong>Measurement only</strong></div><div><span>Authorization</span><strong>Separate step</strong></div></div>
<p>Creating a suite only saves a draft. Preparation freezes the exact plan; authorization and execution remain separate protected actions.</p></section>
<section><div class="section-heading"><div><h2>Start from a preset</h2><p>Presets fill the form and never bypass validation.</p></div></div>
<div class="grid"><button type="button" data-preset="context">Luna xhigh<br><small>stateless vs persistent</small></button><button type="button" data-preset="sol-high">Luna xhigh vs Sol high<br><small>stateless</small></button><button type="button" data-preset="sol-xhigh">Luna xhigh vs Sol xhigh<br><small>stateless</small></button><button type="button" data-preset="custom">Custom matrix</button></div></section>
<form id="suite">
<fieldset><legend>Suite identity</legend><div class="grid"><label>Suite name<input name="name" required maxlength="120" placeholder="A concise scientific question"></label>
<label>Fixture<select name="fixture_id">{fixture_options}</select></label></div><label>Description<textarea name="description" maxlength="2000" placeholder="What should this comparison establish?"></textarea></label></fieldset>
<fieldset><legend>Bounded execution plan</legend><div class="grid">
<label>Timeout per turn (seconds)<input name="timeout_seconds" type="number" min="1" max="900" value="300"></label>
<label>Arm ordering<select name="ordering"><option value="fixed">Fixed</option><option value="randomized">Randomized with saved seed</option></select></label>
<label>Random seed<input name="ordering_seed" type="number" min="0" value="0"></label>
<label>Hard maximum inference starts<input name="maximum_inference_starts" type="number" min="1" max="64" value="2"></label>
<label>Maximum total server tokens (optional)<input name="maximum_total_server_tokens" type="number" min="1"></label>
<label>Client-owned token limit / turn<input name="maximum_client_owned_tokens_per_turn" type="number" min="100" max="12000" value="12000"></label>
<label>Worker wall limit (seconds)<input name="maximum_worker_wall_seconds" type="number" min="1" max="86400" value="7200"></label>
<label>App Server stdout bound (bytes)<input name="maximum_stdout_bytes" type="number" min="4096" max="67108864" value="1048576"></label>
<label>App Server stderr bound (bytes)<input name="maximum_stderr_bytes" type="number" min="4096" max="16777216" value="262144"></label>
<label>Wire-log bound (bytes)<input name="maximum_wire_log_bytes" type="number" min="4096" max="134217728" value="8388608"></label>
<label>Preserved artifacts bound (bytes)<input name="max_preserved_artifact_bytes" type="number" min="1048576" max="1073741824" value="67108864"></label>
<label>Runtime scratch bound (bytes)<input name="max_runtime_scratch_bytes" type="number" min="1048576" max="4294967296" value="536870912"></label>
<label>Single preserved file bound (bytes)<input name="max_single_preserved_artifact_bytes" type="number" min="1024" max="1073741824" value="33554432"></label>
<label>Single runtime file bound (bytes)<input name="max_single_runtime_file_bytes" type="number" min="1024" max="4294967296" value="268435456"></label>
</div><div class="grid two"><label><span><input type="checkbox" name="measurement_only" checked disabled> Measurement only</span><small>Returned actions are recorded, never dispatched.</small></label>
<label><span><input type="checkbox" name="fail_closed" checked> Fail closed</span><small>Stop after the first invalid or incomplete arm.</small></label></div></fieldset>
<fieldset><legend>Comparison arms</legend><div id="arms"></div><button type="button" id="add-arm">＋ Add arm</button></fieldset>
<fieldset><legend>Notes</legend><label>Internal notes<textarea name="notes" maxlength="2000" placeholder="Assumptions, caveats, or review instructions"></textarea></label></fieldset>
<div class="form-actions"><button type="submit" class="primary">Create draft suite</button><a href="/comparisons">Cancel</a></div></form>
"""
    script = f"""
const catalog={catalog_json};let armCount=0;
function arm(modelName='gpt-5.6-luna',effort='xhigh',mode='stateless_turns',name='Arm'){{const id=armCount++;const models=Object.keys(catalog).map(x=>`<option ${{x===modelName?'selected':''}}>${{esc(x)}}</option>`).join('');const efforts=['medium','high','xhigh'].map(x=>`<option ${{x===effort?'selected':''}}>${{x}}</option>`).join('');document.getElementById('arms').insertAdjacentHTML('beforeend',`<div class="arm"><div class="card-head"><strong>Arm ${{id+1}}</strong><button type="button" class="danger-button remove-arm">Remove</button></div><div class="grid"><label>Display name<input data-k="display_name" value="${{esc(name)}}"></label><label>Model<select data-k="model">${{models}}</select></label><label>Reasoning effort<select data-k="reasoning_effort">${{efforts}}</select></label><label>Context mode<select data-k="context_mode"><option value="stateless_turns" ${{mode==='stateless_turns'?'selected':''}}>Stateless turns</option><option value="persistent_thread" ${{mode==='persistent_thread'?'selected':''}}>Persistent thread</option><option value="compacted_thread" ${{mode==='compacted_thread'?'selected':''}}>Compacted thread (experimental)</option></select></label><label>Repetitions<input data-k="repetitions" type="number" min="1" max="8" value="1"></label><label>Conversation group (optional)<input data-k="conversation_group_id" maxlength="120"></label><label><span><input data-k="resume_prior_thread" type="checkbox"> Resume prior arm in group</span></label></div></div>`);document.querySelector('#arms .arm:last-child .remove-arm').onclick=e=>e.currentTarget.closest('.arm').remove()}}
function preset(kind){{arms.innerHTML='';armCount=0;if(kind==='context'){{arm('gpt-5.6-luna','xhigh','stateless_turns','Luna stateless');arm('gpt-5.6-luna','xhigh','persistent_thread','Luna persistent')}}else if(kind==='sol-high'){{arm('gpt-5.6-luna','xhigh','stateless_turns','Luna xhigh');arm('gpt-5.6-sol','high','stateless_turns','Sol high')}}else if(kind==='sol-xhigh'){{arm('gpt-5.6-luna','xhigh','stateless_turns','Luna xhigh');arm('gpt-5.6-sol','xhigh','stateless_turns','Sol xhigh')}}else arm()}}
document.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>preset(b.dataset.preset));document.getElementById('add-arm').onclick=()=>arm();preset('context');
document.getElementById('suite').onsubmit=async e=>{{e.preventDefault();const f=new FormData(e.target);const payload={{name:f.get('name'),description:f.get('description')||'',fixture_id:f.get('fixture_id'),timeout_seconds:Number(f.get('timeout_seconds')),ordering:f.get('ordering'),ordering_seed:Number(f.get('ordering_seed')),measurement_only:true,execute_decisions:false,fail_closed:f.has('fail_closed'),maximum_inference_starts:Number(f.get('maximum_inference_starts')),maximum_total_server_tokens:f.get('maximum_total_server_tokens')?Number(f.get('maximum_total_server_tokens')):null,maximum_client_owned_tokens_per_turn:Number(f.get('maximum_client_owned_tokens_per_turn')),maximum_worker_wall_seconds:Number(f.get('maximum_worker_wall_seconds')),maximum_stdout_bytes:Number(f.get('maximum_stdout_bytes')),maximum_stderr_bytes:Number(f.get('maximum_stderr_bytes')),maximum_wire_log_bytes:Number(f.get('maximum_wire_log_bytes')),max_preserved_artifact_bytes:Number(f.get('max_preserved_artifact_bytes')),max_runtime_scratch_bytes:Number(f.get('max_runtime_scratch_bytes')),max_single_preserved_artifact_bytes:Number(f.get('max_single_preserved_artifact_bytes')),max_single_runtime_file_bytes:Number(f.get('max_single_runtime_file_bytes')),notes:f.get('notes')||'',arms:[...document.querySelectorAll('.arm')].map(a=>Object.fromEntries([...a.querySelectorAll('[data-k]')].map(x=>[x.dataset.k,x.dataset.k==='repetitions'?Number(x.value):x.dataset.k==='resume_prior_thread'?x.checked:x.value])))}};try{{const d=await api('/api/comparisons',{{method:'POST',body:JSON.stringify(payload)}});location.href=`/comparisons/${{d.suite_id}}#${{location.hash.slice(1)}}`}}catch(e){{notice.textContent=e.message}}}};
"""
    return page(
        "New comparison suite",
        content,
        script,
        subtitle="Build a bounded, exact model/effort/context matrix. Nothing is authorized or executed here.",
    )


def comparison_detail_page(suite_id: str) -> bytes:
    content = f"""
<section id="summary"><div class="empty-state">Loading suite summary…</div></section>
<section id="preflight"><div class="empty-state">Loading immutable plan…</div></section>
<section id="worker-progress"><div class="empty-state">Loading worker status…</div></section>
<section id="auth-panel"><div class="section-heading"><div><h2>Runtime readiness</h2><p>Credential contents and paths are never shown.</p></div></div><div id="auth-status"></div></section>
<section id="suite-actions"><div class="section-heading"><div><h2>Lifecycle controls</h2><p>Every state-changing action requires the dashboard bearer token.</p></div></div><div class="form-actions"><button id="prepare">Prepare immutable plan</button><button id="authorize">Authorize exact plan</button><button id="start" class="primary">Start authorized suite</button><button id="stop" class="danger-button">Stop</button><a href="/comparisons/{escape(suite_id)}/blind">Open blind comparison →</a></div></section>
<section><div class="section-heading"><div><h2>Measured turns</h2><p>Decisions are semantic by default; raw evidence remains expandable.</p></div></div><div id="turns" class="decision-list"></div></section>
<section><div class="section-heading"><div><h2>Usage, cost, latency, and quality</h2><p>Cached input and reasoning output are subsets and are not double-counted.</p></div></div><div id="charts"></div></section>
<section id="rating-panel"><div class="section-heading"><div><h2>Manual rating</h2><p>Ratings are append-only and kept separate from automatic validity.</p></div></div><form id="rating" class="grid"><label>Completed valid turn<select name="comparison_turn_id" id="rating-turn"></select></label><label>Scientific usefulness<input name="scientific_usefulness" type="number" min="1" max="5" value="3"></label><label>Clarity<input name="clarity" type="number" min="1" max="5" value="3"></label><label>Novelty<input name="novelty" type="number" min="1" max="5" value="3"></label><label>Would execute<select name="would_execute"><option value="uncertain">Uncertain</option><option value="yes">Yes</option><option value="no">No</option></select></label><label>Comment<input name="comment" maxlength="2000"></label><button class="primary">Save append-only rating</button></form><div id="rating-empty" class="empty-state" hidden>No completed, schema-valid, semantically valid turn can be rated yet.</div></section>
"""
    script = f"""
const sid={json.dumps(suite_id)};let current;
const summary=document.getElementById('summary'),preflight=document.getElementById('preflight'),workerProgress=document.getElementById('worker-progress'),turns=document.getElementById('turns'),charts=document.getElementById('charts'),rating=document.getElementById('rating'),prepare=document.getElementById('prepare'),authorize=document.getElementById('authorize'),start=document.getElementById('start'),stop=document.getElementById('stop');
function planCard(s,arms){{const separated=Number(s.resource_accounting_version||1)>=2;return `<div class="section-heading"><div><h2>Immutable execution plan</h2><p>Authorization is bound to this exact fingerprint.</p></div>${{badge(s.authorization_status||'not authorized')}}</div><div class="plan-callout"><div><span>Planned paid inferences</span><strong>${{s.planned_inference_count}}</strong></div><div><span>Hard maximum starts</span><strong>${{s.maximum_inference_starts}}</strong></div><div><span>Expected search / tools</span><strong>0 / 0</strong></div></div><div class="grid" style="margin-top:.8rem">${{field('Plan fingerprint',s.plan_fingerprint)}}${{field('Fixture hash',s.fixture_sha256)}}${{field('Timeout per turn',fmtSeconds(s.timeout_seconds))}}${{field('Maximum total server tokens',fmt(s.maximum_total_server_tokens))}}${{field('Client-owned tokens / turn',fmt(s.maximum_client_owned_tokens_per_turn))}}${{field('Decision execution','Disabled')}}${{field('Measurement only',Boolean(s.measurement_only)?'Yes':'No')}}${{field('Fail closed',Boolean(s.fail_closed)?'Yes':'No')}}${{field('Ordering',s.randomized_arm_order?'Randomized':'Fixed')}}${{field('Random seed',s.ordering_seed)}}</div><h3 style="margin-top:1rem">Resource limits</h3><div class="grid">${{field('Accounting contract',separated?'Separated categories v2':'Legacy ambiguous artifact-directory v1')}}${{field('Preserved artifacts',fmt(separated?s.max_preserved_artifact_bytes:s.maximum_artifact_directory_bytes))}}${{field('Runtime scratch',separated?fmt(s.max_runtime_scratch_bytes):'Not separately authorized')}}${{field('Single preserved file',separated?fmt(s.max_single_preserved_artifact_bytes):'Not separately authorized')}}${{field('Single runtime file',separated?fmt(s.max_single_runtime_file_bytes):'Not separately authorized')}}${{field('Wire log',fmt(s.maximum_wire_log_bytes))}}${{field('Stderr',fmt(s.maximum_stderr_bytes))}}${{field('Stdout / JSONL',fmt(s.maximum_stdout_bytes))}}${{field('Worker wall time',fmtSeconds(s.maximum_worker_wall_seconds))}}</div><h3 style="margin-top:1rem">Authorized arm contract</h3><div class="stack">${{arms.map(a=>`<article class="suite-card"><div class="card-head"><div><strong>${{esc(a.display_name)}}</strong><div class="meta">Order ${{a.effective_order+1}}</div></div>${{badge(a.display_lifecycle_state||a.lifecycle_state||a.status)}}</div><div class="grid">${{field('Model',a.model)}}${{field('Reasoning effort',a.reasoning_effort)}}${{field('Context mode',a.context_mode)}}${{field('Prompt hash',a.prompt_sha256)}}${{field('Director state hash',a.director_state_sha256)}}${{field('Base instructions hash',a.base_instructions_sha256)}}${{field('Output schema hash',a.output_schema_sha256)}}${{field('Evidence registry hash',a.evidence_registry_sha256)}}${{field('Advisory registry hash',a.advisory_registry_sha256)}}${{field('Executable registry hash',a.executable_registry_sha256)}}${{field('Applicable action space hash',a.applicable_action_space_sha256)}}${{field('Campaign budget hash',a.campaign_budget_sha256)}}${{field('Relative cost multiplier',a.relative_cost_multiplier_snapshot)}}</div></article>`).join('')}}</div>${{technical('Complete technical plan',{{suite_id:s.suite_id,plan_fingerprint:s.plan_fingerprint,fixture_sha256:s.fixture_sha256,resource_accounting_version:s.resource_accounting_version,limits:{{maximum_inference_starts:s.maximum_inference_starts,maximum_total_server_tokens:s.maximum_total_server_tokens,maximum_client_owned_tokens_per_turn:s.maximum_client_owned_tokens_per_turn,maximum_worker_wall_seconds:s.maximum_worker_wall_seconds,maximum_stdout_bytes:s.maximum_stdout_bytes,maximum_stderr_bytes:s.maximum_stderr_bytes,maximum_wire_log_bytes:s.maximum_wire_log_bytes,max_preserved_artifact_bytes:s.max_preserved_artifact_bytes,max_runtime_scratch_bytes:s.max_runtime_scratch_bytes,max_single_preserved_artifact_bytes:s.max_single_preserved_artifact_bytes,max_single_runtime_file_bytes:s.max_single_runtime_file_bytes}},arms}})}}`}}
function safeResourceLabel(value){{if(!value)return 'Unavailable';const text=String(value),parts=text.split('/'),name=parts.at(-1);return text.includes('/arg0/')?`app-server-tmp/arg0/${{name}}`:text.startsWith('runtime-groups/')?`runtime-scratch/${{name}}`:text}}
function workerCard(d){{
 const w=d.worker||{{}},lease=w.lease||{{}},request=w.stop_request||{{}},samples=w.resource_samples||[];
 const heartbeat=lease.heartbeat_at?Math.max(0,(Date.now()-Date.parse(lease.heartbeat_at))/1000):null;
 const sample=(category,kind)=>samples.filter(x=>x.category===category&&x.sample_kind===kind).at(-1);
 const scratch=sample('runtime_scratch','latest')||sample('runtime_scratch','terminal')||{{}},preserved=sample('preserved_artifacts','latest')||sample('preserved_artifacts','terminal')||{{}},crossing=sample('runtime_scratch','threshold_crossing')||{{}};
 const oldErrors=safeJson(crossing.accounting_errors_json)||[];
 const wrappers=['apply_patch','applypatch','codex-execve-wrapper','codex-linux-sandbox'];
 const legacyWrapperRejected=!d.suite.failure_domain&&d.suite.resource_exceeded_category==='runtime_scratch'&&Number(d.suite.resource_peak_bytes)<=Number(d.suite.resource_exceeded_limit_bytes)&&(crossing.enforcement_decision==='accounting_error'||scratch.enforcement_decision==='accounting_error')&&oldErrors.some(x=>wrappers.includes(String(x).split('/').at(-1)));
 const legacyFailure=!d.suite.resource_exceeded_category&&String(d.suite.failure_reason||'').includes('artifact directory limit exceeded');
 const failureDomain=d.suite.failure_domain||(legacyWrapperRejected?'filesystem_policy':legacyFailure?'byte_quota':d.suite.resource_exceeded_category?'byte_quota':null);
 const failureCode=d.suite.failure_code||(legacyWrapperRejected?'legacy_expected_runtime_wrapper_rejected':legacyFailure?'legacy_ambiguous_artifact_limit':null);
 const actualByteExceeded=d.suite.byte_quota_exceeded===null||d.suite.byte_quota_exceeded===undefined?(failureDomain==='byte_quota'&&Number(d.suite.resource_peak_bytes)>Number(d.suite.resource_exceeded_limit_bytes)):Boolean(d.suite.byte_quota_exceeded);
 const scratchMeasured=legacyWrapperRejected?crossing.current_apparent_bytes:scratch.current_apparent_bytes;
 const scratchLimit=d.suite.max_runtime_scratch_bytes;
 const policyLabel=safeResourceLabel(d.suite.resource_policy_label||oldErrors[0]||d.suite.resource_largest_contributor);
 const largest=safeResourceLabel(scratch.largest_contributor_relative_path||preserved.largest_contributor_relative_path||d.suite.resource_largest_contributor);
 let failure='';
 if(failureDomain==='filesystem_policy'||failureDomain==='accounting_error'){{failure=`<div class="error-state" style="margin-top:.8rem"><strong>Filesystem policy violation</strong><div class="grid" style="margin-top:.6rem">${{field('Failure',legacyWrapperRejected?'Normal App Server wrapper symlinks were incorrectly rejected':failureCode||'Filesystem accounting error')}}${{field('Policy code',failureCode||'Unavailable')}}${{field('Lifecycle stage',d.suite.resource_enforcement_stage||crossing.lifecycle_stage||'Unavailable')}}${{field('Safe relative label',policyLabel)}}${{field('Actual byte quota exceeded',actualByteExceeded?'Yes':'No')}}${{field('Scratch current / limit',scratchMeasured===undefined?'Unavailable':`${{fmt(scratchMeasured)}} B / ${{fmt(scratchLimit)}} B`)}}${{field('Active turn completed',d.suite.resource_active_turn_completed?'Yes':'No')}}${{field('Later arms blocked',d.arms.some(a=>a.display_lifecycle_state==='blocked / not started'||a.lifecycle_state==='blocked')?'Yes':'No')}}${{field('Comparison complete','No')}}</div></div>`}}
 else if(failureDomain){{const title=d.suite.resource_exceeded_category==='runtime_scratch'?'Runtime scratch exceeded':'Resource limit exceeded';failure=`<div class="error-state" style="margin-top:.8rem"><strong>${{title}}</strong><div class="grid" style="margin-top:.6rem">${{field('Failure domain',failureDomain)}}${{field('Current / peak / limit',`${{fmt(crossing.current_apparent_bytes??d.suite.resource_peak_bytes)}} / ${{fmt(d.suite.resource_peak_bytes)}} / ${{fmt(d.suite.resource_exceeded_limit_bytes)}} B`)}}${{field('Largest contributor',safeResourceLabel(d.suite.resource_largest_contributor))}}${{field('Stage',d.suite.resource_enforcement_stage||(legacyFailure?'post-arm artifact check':'Unavailable'))}}${{field('Actual byte quota exceeded',actualByteExceeded?'Yes':'No')}}${{field('Later arms blocked',d.arms.some(a=>a.display_lifecycle_state==='blocked / not started'||a.lifecycle_state==='blocked')?'Yes':'No')}}${{field('Comparison complete','No')}}</div></div>`}}
 return `<div class="section-heading"><div><h2>Comparison worker progress</h2><p>Bounded live status from the persisted lease, transitions, resource peaks, and filesystem policy.</p></div>${{badge(lease.released_at?'released':lease.lease_id?'active':'inactive')}}</div><div class="grid">${{field('Completed arms',`${{w.completed_arms||0}} / ${{w.planned_arms||d.arms.length}}`)}}${{field('Worker PID',lease.pid??'Inactive')}}${{field('Heartbeat age',heartbeat===null?'Unavailable':fmtSeconds(heartbeat))}}${{field('Lease released',lease.released_at?'Yes':'No')}}${{field('Stop state',request.state||'Not requested')}}${{field('Inference starts',`${{d.suite.consumed_inference_starts}} / ${{d.suite.maximum_inference_starts}}`)}}${{field('Scratch current / peak',scratch.current_apparent_bytes===undefined?'Unavailable':`${{fmt(scratch.current_apparent_bytes)}} / ${{fmt(scratch.peak_apparent_bytes)}}`)}}${{field('Preserved current / peak',preserved.current_apparent_bytes===undefined?'Unavailable':`${{fmt(preserved.current_apparent_bytes)}} / ${{fmt(preserved.peak_apparent_bytes)}}`)}}${{field('Largest runtime contributor',largest)}}${{field('Quota status',actualByteExceeded?'Exceeded':failureDomain?'Byte limits not exceeded':'Within configured limits')}}${{field('Filesystem policy',d.suite.symlink_policy_status||crossing.symlink_policy_status||(legacyWrapperRejected?'legacy false rejection':'No violation recorded'))}}${{field('Cleanup status',d.suite.resource_cleanup_status||'Not recorded')}}${{field('Total server tokens',fmt(w.total_server_tokens||0))}}</div>${{failure}}`}}
function effectCard(t){{const missing=v=>v===null||v===undefined||v===''||v==='null';const scoreMissing=missing(t.best_score_before)||missing(t.best_score_after);const delta=scoreMissing?null:t.best_score_after-t.best_score_before;const tone=delta===null?'':delta<0?'good':delta>0?'bad':'warn';return `<div class="effect ${{tone}}"><div class="card-head"><strong>Measured downstream effect</strong>${{badge(t.exact_verifier_result||'not measured')}}</div><dl class="semantic-list">${{field('Score',scoreMissing?'Unavailable':`${{t.best_score_before}} → ${{t.best_score_after}}`)}}${{field('Delta',delta===null?'Unavailable':delta)}}${{field('Candidate evaluations',fmt(t.candidate_evaluations))}}${{field('CPU time',fmtSeconds(t.cpu_seconds))}}${{field('Time to improvement',fmtSeconds(t.time_to_improvement))}}</dl></div>`}}
function turnCard(t){{const issues=safeJson(t.validation_issues_json)||[];return `<article class="turn-card"><div class="card-head"><div><div class="chips">${{badge(t.lifecycle_status)}}${{badge(t.context_mode)}}${{t.measurement_only?badge('measurement only'):''}}</div><h3>${{esc(t.display_name)}}</h3><div class="meta">${{esc(t.model)}} · ${{esc(label(t.reasoning_effort))}} reasoning · ${{esc(t.thread_lifecycle||'thread unavailable')}}</div></div><div class="metric"><small>Server-reported total</small><strong>${{fmt(t.server_reported_total_tokens)}} tokens</strong></div></div><div class="grid">${{field('Input tokens',fmt(t.input_tokens))}}${{field('Cached input',fmt(t.cached_input_tokens))}}${{field('Cache write',fmt(t.cache_write_input_tokens))}}${{field('Output tokens',fmt(t.output_tokens))}}${{field('Reasoning output',fmt(t.reasoning_output_tokens))}}${{field('Total wall time',fmtSeconds(t.total_wall_seconds))}}${{field('First item',fmtSeconds(t.first_item_latency_seconds))}}${{field('Final answer',fmtSeconds(t.final_answer_latency_seconds))}}</div><div class="chips" style="margin:.7rem 0">${{badge(t.schema_valid?'schema valid':'schema invalid')}}${{badge(t.semantic_valid?'semantic valid':'semantic invalid')}}${{badge(t.executed?'executed':'not executed')}}${{badge(t.tool_call_count?`${{t.tool_call_count}} tool calls`:'zero tool calls')}}</div>${{issues.length?`<div class="error-state"><strong>Validation issues</strong><ul>${{issues.map(x=>`<li>${{esc(x)}}</li>`).join('')}}</ul></div>`:''}}${{decisionCard(t.normalized_decision_json,t)}}${{effectCard(t)}}<div class="grid">${{field('Active executable lanes',t.active_executable_lane_count)}}${{field('Active candidate targets',t.active_candidate_target_count)}}${{field('Historical evidence targets',t.historical_evidence_target_count)}}${{field('Applicable actions',actionSpaceLabels(t.applicable_action_space_json))}}</div>${{technical('Raw server decision',t.raw_decision_json)}}${{technical('Normalized decision JSON',t.normalized_decision_json)}}${{technical('Applicable action space',t.applicable_action_space_json)}}</article>`}}
function bars(turns,key,title,kind=''){{const available=turns.filter(t=>t[key]!==null&&t[key]!==undefined);if(!available.length)return `<div><h3>${{title}}</h3><p class="meta">No authoritative values are available.</p></div>`;const max=Math.max(1,...available.map(t=>Number(t[key])));return `<div><h3>${{title}}</h3>${{available.map(t=>`<div class="bar-row"><span>${{esc(t.display_name)}}</span><div class="bar-track"><div class="bar-fill ${{kind}}" style="width:${{100*Number(t[key])/max}}%"></div></div><strong>${{fmt(t[key])}}</strong></div>`).join('')}}</div>`}}
function costBars(turns){{const rows=turns.filter(t=>t.cost?.relative_cost_units!==null&&t.cost?.relative_cost_units!==undefined);if(!rows.length)return '<div><h3>Relative cost units</h3><p class="meta">No cost profile snapshot is available.</p></div>';const max=Math.max(1,...rows.map(t=>Number(t.cost.relative_cost_units)));return `<div><h3>Relative cost units</h3>${{rows.map(t=>`<div class="bar-row"><span>${{esc(t.display_name)}}</span><div class="bar-track"><div class="bar-fill cost" style="width:${{100*t.cost.relative_cost_units/max}}%"></div></div><strong>${{fmt(t.cost.relative_cost_units)}}</strong></div>`).join('')}}</div>`}}
function quality(metrics){{const ratings=metrics.mean_manual_usefulness;const pair=Object.values(metrics.pairwise||{{}}).reduce((a,v)=>({{wins:a.wins+(v.wins||0),draws:a.draws+(v.draws||0),losses:a.losses+(v.losses||0)}}),{{wins:0,draws:0,losses:0}});return `<div><h3>Quality evidence</h3><div class="grid">${{field('Valid response rate',metrics.valid_response_rate===null?'Unavailable':`${{(100*metrics.valid_response_rate).toFixed(1)}}%`)}}${{field('Mean usefulness',ratings===null?'Not rated':Number(ratings).toFixed(2))}}${{field('Pairwise record',`${{pair.wins}} wins · ${{pair.draws}} draws · ${{pair.losses}} losses`)}}</div><p class="meta">${{ratings===null?'No quality coordinate or Pareto claim is shown until manual usefulness ratings exist.':'Quality and cost remain separate measurements.'}}</p></div>`}}
async function load(){{try{{current=await api(`/api/comparisons/${{sid}}`);const s=current.suite,m=current.comparison_metrics;summary.innerHTML=`<div class="section-heading"><div><div class="chips">${{badge(s.status)}}${{s.read_only?badge('read only'):''}}</div><h2>${{esc(s.name)}}</h2><p>${{esc(s.description||'No description supplied.')}}</p></div></div><div class="grid">${{field('Fixture',s.fixture_reference)}}${{field('Completed / planned',`${{current.turns.filter(t=>t.lifecycle_status==='completed').length}} / ${{s.planned_inference_count}}`)}}${{field('Consumed / maximum starts',`${{s.consumed_inference_starts}} / ${{s.maximum_inference_starts}}`)}}${{field('Recommendation',s.recommendation_status||'Pending')}}${{field('Recommendation basis',s.recommendation_basis||'Unavailable')}}${{field('Created',s.created_at)}}</div>`;preflight.innerHTML=planCard(s,current.arms);const a=current.auth_availability;document.getElementById('auth-status').innerHTML=`<div class="grid">${{field('Server configuration',a.configured?'Configured':'Not configured')}}${{field('Auth source availability',a.available?'Available':'Unavailable')}}${{field('Credential path exposed','No')}}</div>`;turns.innerHTML=current.turns.length?current.turns.map(turnCard).join(''):'<div class="empty-state"><strong>No measured turns yet.</strong><p>Prepare and authorize the exact plan before starting a future comparison.</p></div>';charts.innerHTML=`<div class="grid two">${{bars(current.turns,'server_reported_total_tokens','Server-reported total tokens')}}${{costBars(current.turns)}}${{bars(current.turns,'total_wall_seconds','Total latency','latency')}}${{quality(m)}}</div>`;const valid=current.turns.filter(t=>t.lifecycle_status==='completed'&&t.schema_valid&&t.semantic_valid);document.getElementById('rating-turn').innerHTML=valid.map(t=>`<option value="${{esc(t.comparison_turn_id)}}">${{esc(t.display_name)}}</option>`).join('');rating.hidden=!valid.length;document.getElementById('rating-empty').hidden=Boolean(valid.length);const terminal=['completed','failed','stopped'].includes(s.status);prepare.disabled=s.read_only||s.status!=='draft';authorize.disabled=s.read_only||s.status!=='prepared';start.disabled=s.read_only||s.status!=='authorized';stop.disabled=s.read_only||terminal;document.querySelector(`#suite-actions p`).textContent=s.read_only?'This imported historical suite is immutable.':terminal?'This suite is terminal; controls remain visible for audit but are disabled.':'Every state-changing action requires the dashboard bearer token.'}}catch(e){{notice.textContent=e.message}}}}
async function loadProgress(){{try{{const progress=await api(`/api/comparisons/${{sid}}/progress`);workerProgress.innerHTML=workerCard(progress);if(progress.suite.status!==current?.suite?.status)await load()}}catch(e){{workerProgress.innerHTML=`<div class="error-state">${{esc(e.message)}}</div>`}}}}
document.getElementById('prepare').onclick=async()=>{{try{{await api(`/api/comparisons/${{sid}}/prepare`,{{method:'POST',body:'{{}}'}});load()}}catch(e){{notice.textContent=e.message}}}};document.getElementById('authorize').onclick=async()=>{{try{{await api(`/api/comparisons/${{sid}}/authorize`,{{method:'POST',body:JSON.stringify({{plan_fingerprint:current.suite.plan_fingerprint}})}});load()}}catch(e){{notice.textContent=e.message}}}};document.getElementById('start').onclick=async()=>{{try{{await api(`/api/comparisons/${{sid}}/start`,{{method:'POST',body:'{{}}'}});load()}}catch(e){{notice.textContent=e.message}}}};document.getElementById('stop').onclick=async()=>{{try{{await api(`/api/comparisons/${{sid}}/stop`,{{method:'POST',body:'{{}}'}});load()}}catch(e){{notice.textContent=e.message}}}};
rating.onsubmit=async e=>{{e.preventDefault();const f=new FormData(e.target);const p=Object.fromEntries(f);for(const k of ['scientific_usefulness','clarity','novelty'])p[k]=Number(p[k]);try{{await api(`/api/comparisons/${{sid}}/ratings`,{{method:'POST',body:JSON.stringify(p)}});notice.textContent='Rating saved as a new history entry.';load()}}catch(e){{notice.textContent=e.message}}}};load().then(loadProgress);setInterval(loadProgress,2000);
"""
    return page(
        "Comparison suite",
        content,
        script,
        subtitle="Inspect the immutable plan, authoritative usage, hard validity, and human quality evidence.",
    )


def blind_page(suite_id: str) -> bytes:
    content = """
<section><div class="section-heading"><div><h2>Blind scientific review</h2><p>Model, effort, context, usage, latency, and cost remain hidden until submission.</p></div></div>
<div id="blind-pair" class="grid two"><article class="answer"><span class="eyebrow">Answer A</span><div id="a"></div></article><article class="answer"><span class="eyebrow">Answer B</span><div id="b"></div></article></div>
<div id="blind-empty" class="empty-state" hidden><strong>Not enough valid responses</strong><p>Two completed, schema-valid turns are required for ordinary blind quality review. Failed or invalid turns remain available in the suite reliability view.</p></div>
<div id="blind-controls"><div class="form-actions"><button data-v="left">A better</button><button data-v="equal">Equal</button><button data-v="right">B better</button><button data-v="skip">Skip</button></div><label style="margin-top:.8rem">Optional comment<input id="comment" maxlength="2000"></label></div><div id="reveal"></div></section>
"""
    script = f"""
const sid={json.dumps(suite_id)};let pair=[];let blindSeed=0;
async function load(){{try{{const d=await api(`/api/comparisons/${{sid}}?blind=1`);blindSeed=d.blind_order_seed;pair=d.turns.filter(t=>t.lifecycle_status==='completed'&&t.schema_valid).slice(0,2);if(pair.length<2){{a.innerHTML=b.innerHTML='';document.getElementById('blind-pair').hidden=true;document.getElementById('blind-empty').hidden=false;document.getElementById('blind-controls').hidden=true;return}}a.innerHTML=decisionCard(pair[0].normalized_decision_json,{{}});b.innerHTML=decisionCard(pair[1].normalized_decision_json,{{}})}}catch(e){{document.getElementById('blind-pair').hidden=true;document.getElementById('blind-empty').hidden=false;document.getElementById('blind-controls').hidden=true;notice.textContent=e.message}}}}
document.querySelectorAll('[data-v]').forEach(x=>x.onclick=async()=>{{try{{await api(`/api/comparisons/${{sid}}/pairwise-ratings`,{{method:'POST',body:JSON.stringify({{left_turn_id:pair[0].comparison_turn_id,right_turn_id:pair[1].comparison_turn_id,preferred:x.dataset.v,comment:comment.value,blind_order_seed:blindSeed}})}});const full=await api(`/api/comparisons/${{sid}}`);const left=full.turns.find(t=>t.comparison_turn_id===pair[0].comparison_turn_id),right=full.turns.find(t=>t.comparison_turn_id===pair[1].comparison_turn_id);reveal.innerHTML=`<div class="effect good"><strong>Rating saved.</strong><p>Answer A was <b>${{esc(left.display_name)}}</b>. Answer B was <b>${{esc(right.display_name)}}</b>.</p></div>`;document.getElementById('blind-controls').hidden=true}}catch(e){{notice.textContent=e.message}}}});load();
"""
    return page(
        "Blind pairwise comparison",
        content,
        script,
        subtitle="Judge the scientific response before revealing its runtime contract or cost.",
    )


def cost_profiles_page(catalog: dict[str, list[str]]) -> bytes:
    content = """
<section><div class="section-heading"><div><h2>Cost semantics</h2><p>Relative multipliers are editable assumptions. API rates are optional estimates, never subscription charges.</p></div></div>
<div class="grid"><div class="metric"><small>Authoritative usage</small><strong>Server-reported total tokens</strong></div><div class="metric"><small>Relative comparison</small><strong>User-configured units</strong></div><div class="metric"><small>Optional estimate</small><strong>API-equivalent only</strong></div></div></section>
<section><h2>Add a versioned cost profile</h2><form id="profile" class="grid"><label>Model<select name="model" id="model"></select></label><label>Reasoning effort<select name="reasoning_effort"><option>medium</option><option>high</option><option>xhigh</option></select></label><label>Display name<input name="display_name" required maxlength="120"></label><label>Relative multiplier<input name="relative_cost_multiplier" type="number" min="0" step="0.001" value="1"></label><label>API input / million<input name="api_input_per_million" type="number" min="0" step="0.0001"></label><label>API cached input / million<input name="api_cached_input_per_million" type="number" min="0" step="0.0001"></label><label>API output / million<input name="api_output_per_million" type="number" min="0" step="0.0001"></label><label>Currency<input name="currency" maxlength="12" placeholder="USD"></label><label>Source label<input name="source_label" required maxlength="200"></label><label>Effective from<input name="effective_from" required placeholder="2026-07-25"></label><button class="primary">Append profile</button></form></section>
<section><div class="section-heading"><div><h2>Profile history</h2><p>Historical rendered comparisons keep their selected profile snapshot.</p></div></div><div id="profiles"></div></section>
"""
    script = f"""
const catalog={json.dumps(catalog, sort_keys=True)};model.innerHTML=Object.keys(catalog).map(x=>`<option>${{esc(x)}}</option>`).join('');
function rate(value,currency){{return value===null?'Not configured':`${{Number(value).toLocaleString(undefined,{{maximumFractionDigits:4}})}} ${{currency||''}}`.trim()}}
function profileCard(p){{return `<article class="suite-card"><div class="card-head"><div><div class="chips">${{badge(p.enabled?'enabled':'disabled')}}${{badge(p.reasoning_effort)}}</div><h3>${{esc(p.display_name)}}</h3><div class="meta">${{esc(p.model)}} · effective ${{esc(p.effective_from)}}</div></div><div class="metric emphasis"><small>Relative multiplier</small><strong>${{Number(p.relative_cost_multiplier).toFixed(3)}}×</strong></div></div><div class="grid">${{field('API input / million',rate(p.api_input_per_million,p.currency))}}${{field('API cached input / million',rate(p.api_cached_input_per_million,p.currency))}}${{field('API output / million',rate(p.api_output_per_million,p.currency))}}${{field('Source',p.source_label)}}${{field('Profile ID',p.profile_id)}}</div>${{technical('Technical profile record',p)}}</article>`}}
async function load(){{try{{const d=await api('/api/model-cost-profiles');profiles.innerHTML=d.profiles.map(profileCard).join('')||'<div class="empty-state">No cost profiles are configured.</div>'}}catch(e){{notice.textContent=e.message}}}}profile.onsubmit=async e=>{{e.preventDefault();const f=Object.fromEntries(new FormData(e.target));for(const k of ['relative_cost_multiplier','api_input_per_million','api_cached_input_per_million','api_output_per_million'])f[k]=f[k]===''?null:Number(f[k]);f.enabled=true;try{{await api('/api/model-cost-profiles',{{method:'POST',body:JSON.stringify(f)}});notice.textContent='Cost profile appended.';load()}}catch(e){{notice.textContent=e.message}}}};load();
"""
    return page(
        "Model cost profiles",
        content,
        script,
        subtitle="Keep authoritative token usage separate from relative assumptions and optional API-equivalent estimates.",
    )
