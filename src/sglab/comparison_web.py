from __future__ import annotations

from html import escape
from typing import Any
import json


STYLE = """
:root{color-scheme:dark;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
body{margin:0;background:#081018;color:#dce8f3}header,main{padding:1.25rem 2rem}
header{border-bottom:1px solid #233343;background:#0d1722}nav{display:flex;gap:1rem}
a{color:#38bdf8}section{margin:1rem 0;padding:1rem;background:#0d1722;border:1px solid #233343;border-radius:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.75rem}
label{display:grid;gap:.3rem;color:#9cb0c2}input,select,textarea,button{font:inherit;color:#e7f1fa;background:#09131d;border:1px solid #334a5f;border-radius:4px;padding:.55rem}
button{cursor:pointer;background:#12314a}table{width:100%;border-collapse:collapse;font-size:.82rem}
th,td{text-align:left;padding:.5rem;border-bottom:1px solid #233343;vertical-align:top}
pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:28rem;overflow:auto}
.metric{padding:.7rem;background:#111f2d;border-left:3px solid #38bdf8}.metric small{display:block;color:#9cb0c2}
.notice{color:#fbbf24}.bad{color:#fda4af}.good{color:#86efac}.blind{font-family:system-ui,sans-serif;line-height:1.5}
svg{max-width:100%;height:auto}@media(max-width:700px){header,main{padding-inline:1rem}.scroll{overflow:auto}}
"""


def page(title: str, content: str, script: str = "") -> bytes:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} — Structural Graph Lab</title><style>{STYLE}</style></head>
<body><header><h1>{escape(title)}</h1><nav><a href="/">Dashboard</a><a href="/comparisons">Comparisons</a><a href="/comparisons/new">New suite</a><a href="/model-cost-profiles">Cost profiles</a></nav></header>
<main>{content}<p id="notice" class="notice"></p></main>
<script>
const token=new URLSearchParams(location.hash.slice(1)).get('token');
const headers={{'Content-Type':'application/json',...(token?{{'Authorization':`Bearer ${{token}}`}}:{{}})}};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
async function api(path,options={{}}){{const r=await fetch(path,{{...options,headers:{{...headers,...(options.headers||{{}})}},cache:'no-store'}});const b=await r.json();if(!r.ok)throw new Error(b.error||`HTTP ${{r.status}}`);return b}}
const fmt=v=>v===null||v===undefined?'unavailable':Number(v).toLocaleString();
{script}
</script></body></html>""".encode("utf-8")


def comparisons_page() -> bytes:
    content = """
<section><form id="filters" class="grid">
<label>Model<input name="model"></label><label>Effort<input name="effort"></label>
<label>Context mode<input name="context_mode"></label><label>Fixture<input name="fixture"></label>
<label>Status<input name="status"></label><button>Apply filters</button></form></section>
<section class="scroll"><table><thead><tr><th>Suite</th><th>Fixture</th><th>Arms / turns</th><th>Models</th><th>Efforts</th><th>Modes</th><th>Status</th><th>Timeouts / invalid</th><th>Total tokens</th><th>Relative units</th><th>Dates</th></tr></thead><tbody id="rows"></tbody></table></section>
"""
    script = """
async function load(){try{const q=new URLSearchParams(new FormData(document.getElementById('filters')));const d=await api('/api/comparisons?'+q);document.getElementById('rows').innerHTML=d.suites.map(s=>`<tr><td><a href="/comparisons/${esc(s.suite_id)}#${location.hash.slice(1)}">${esc(s.name)}</a><br><small>${s.measurement_only?'measurement only':'execution'}</small></td><td>${esc(s.fixture_reference)}</td><td>${s.arm_count} / ${s.completion_count} of ${s.planned_inference_count}</td><td>${esc(s.models.join(', '))}</td><td>${esc(s.efforts.join(', '))}</td><td>${esc(s.context_modes.join(', '))}</td><td>${esc(s.status)}</td><td>${s.timeout_count} / ${s.invalid_decision_count}</td><td>${fmt(s.total_server_tokens)}</td><td>${Number(s.relative_cost_units||0).toFixed(2)}</td><td>${esc(s.created_at)}<br>${esc(s.completed_at||'—')}</td></tr>`).join('')||'<tr><td colspan="11">No comparison suites.</td></tr>'}catch(e){notice.textContent=e.message}}
document.getElementById('filters').addEventListener('submit',e=>{e.preventDefault();load()});load();
"""
    return page("Controlled comparisons", content, script)


def new_comparison_page(catalog: dict[str, list[str]], fixtures: list[dict[str, Any]]) -> bytes:
    fixture_options = "".join(
        f'<option value="{escape(str(row["fixture_id"]))}">{escape(str(row["display_name"]))}</option>'
        for row in fixtures
    )
    catalog_json = json.dumps(catalog, sort_keys=True)
    content = f"""
<section><p>Creating a suite does not authorize or start inference. Decision execution is disabled in this milestone.</p>
<div class="grid"><button data-preset="context">Luna xhigh — stateless vs persistent</button><button data-preset="sol-high">Luna xhigh vs Sol high — stateless</button><button data-preset="sol-xhigh">Luna xhigh vs Sol xhigh — stateless</button><button data-preset="custom">Custom matrix</button></div></section>
<section><form id="suite"><div class="grid">
<label>Suite name<input name="name" required maxlength="120"></label>
<label>Fixture<select name="fixture_id">{fixture_options}</select></label>
<label>Timeout per turn<input name="timeout_seconds" type="number" min="1" max="900" value="300"></label>
<label>Ordering<select name="ordering"><option value="fixed">Fixed</option><option value="randomized">Randomized</option></select></label>
<label>Random seed<input name="ordering_seed" type="number" min="0" value="0"></label>
<label>Maximum inference starts<input name="maximum_inference_starts" type="number" min="1" max="64" value="2"></label>
<label>Maximum total server tokens (optional)<input name="maximum_total_server_tokens" type="number" min="1"></label>
<label>Client-owned token limit<input name="maximum_client_owned_tokens_per_turn" type="number" min="100" max="12000" value="12000"></label>
<label>Worker wall limit (seconds)<input name="maximum_worker_wall_seconds" type="number" min="1" max="86400" value="7200"></label>
<label>App Server stdout bound (bytes)<input name="maximum_stdout_bytes" type="number" min="4096" max="67108864" value="1048576"></label>
<label>App Server stderr bound (bytes)<input name="maximum_stderr_bytes" type="number" min="4096" max="16777216" value="262144"></label>
<label>Wire-log bound (bytes)<input name="maximum_wire_log_bytes" type="number" min="4096" max="134217728" value="8388608"></label>
<label>Artifact-directory bound (bytes)<input name="maximum_artifact_directory_bytes" type="number" min="1048576" max="1073741824" value="67108864"></label>
</div><label>Description<textarea name="description" maxlength="2000"></textarea></label>
<label>Notes<textarea name="notes" maxlength="2000"></textarea></label>
<label><input type="checkbox" name="measurement_only" checked disabled> Measurement only</label>
<label><input type="checkbox" name="fail_closed" checked> Fail closed</label>
<h2>Arms</h2><div id="arms"></div><button type="button" id="add-arm">Add arm</button><button type="submit">Create suite</button></form></section>
"""
    script = f"""
const catalog={catalog_json};let armCount=0;
function arm(model='gpt-5.6-luna',effort='xhigh',mode='stateless_turns',name='Arm'){{const id=armCount++;const models=Object.keys(catalog).map(x=>`<option ${{x===model?'selected':''}}>${{esc(x)}}</option>`).join('');const efforts=['medium','high','xhigh'].map(x=>`<option ${{x===effort?'selected':''}}>${{x}}</option>`).join('');document.getElementById('arms').insertAdjacentHTML('beforeend',`<div class="grid arm"><label>Name<input data-k="display_name" value="${{esc(name)}}"></label><label>Model<select data-k="model">${{models}}</select></label><label>Effort<select data-k="reasoning_effort">${{efforts}}</select></label><label>Context<select data-k="context_mode"><option ${{mode==='stateless_turns'?'selected':''}}>stateless_turns</option><option ${{mode==='persistent_thread'?'selected':''}}>persistent_thread</option><option ${{mode==='compacted_thread'?'selected':''}}>compacted_thread</option></select></label><label>Repetitions<input data-k="repetitions" type="number" min="1" max="8" value="1"></label><label>Conversation group (optional)<input data-k="conversation_group_id" maxlength="120"></label><label><input data-k="resume_prior_thread" type="checkbox"> Resume prior arm in group</label><button type="button" onclick="this.parentElement.remove()">Remove</button></div>`)}}
function preset(kind){{arms.innerHTML='';armCount=0;if(kind==='context'){{arm('gpt-5.6-luna','xhigh','stateless_turns','Luna stateless');arm('gpt-5.6-luna','xhigh','persistent_thread','Luna persistent')}}else if(kind==='sol-high'){{arm('gpt-5.6-luna','xhigh','stateless_turns','Luna xhigh');arm('gpt-5.6-sol','high','stateless_turns','Sol high')}}else if(kind==='sol-xhigh'){{arm('gpt-5.6-luna','xhigh','stateless_turns','Luna xhigh');arm('gpt-5.6-sol','xhigh','stateless_turns','Sol xhigh')}}else arm()}}
document.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>preset(b.dataset.preset));document.getElementById('add-arm').onclick=()=>arm();preset('context');
document.getElementById('suite').onsubmit=async e=>{{e.preventDefault();const f=new FormData(e.target);const payload={{name:f.get('name'),description:f.get('description')||'',fixture_id:f.get('fixture_id'),timeout_seconds:Number(f.get('timeout_seconds')),ordering:f.get('ordering'),ordering_seed:Number(f.get('ordering_seed')),measurement_only:true,execute_decisions:false,fail_closed:f.has('fail_closed'),maximum_inference_starts:Number(f.get('maximum_inference_starts')),maximum_total_server_tokens:f.get('maximum_total_server_tokens')?Number(f.get('maximum_total_server_tokens')):null,maximum_client_owned_tokens_per_turn:Number(f.get('maximum_client_owned_tokens_per_turn')),maximum_worker_wall_seconds:Number(f.get('maximum_worker_wall_seconds')),maximum_stdout_bytes:Number(f.get('maximum_stdout_bytes')),maximum_stderr_bytes:Number(f.get('maximum_stderr_bytes')),maximum_wire_log_bytes:Number(f.get('maximum_wire_log_bytes')),maximum_artifact_directory_bytes:Number(f.get('maximum_artifact_directory_bytes')),notes:f.get('notes')||'',arms:[...document.querySelectorAll('.arm')].map(a=>Object.fromEntries([...a.querySelectorAll('[data-k]')].map(x=>[x.dataset.k,x.dataset.k==='repetitions'?Number(x.value):x.dataset.k==='resume_prior_thread'?x.checked:x.value])))}};try{{const d=await api('/api/comparisons',{{method:'POST',body:JSON.stringify(payload)}});location.href=`/comparisons/${{d.suite_id}}#${{location.hash.slice(1)}}`}}catch(e){{notice.textContent=e.message}}}};
"""
    return page("New comparison suite", content, script)


def comparison_detail_page(suite_id: str) -> bytes:
    content = f"""
<section id="summary"></section><section id="preflight"></section>
<section><h2>Server-configured auth availability</h2><pre id="auth-status">Loading…</pre></section>
<section><button id="prepare">Prepare immutable plan</button> <button id="authorize">Authorize exact plan</button> <button id="start">Start authorized suite</button> <button id="stop">Stop</button> <a href="/comparisons/{escape(suite_id)}/blind">Blind comparison</a></section>
<section class="scroll"><h2>Turns</h2><div id="turns"></div></section>
<section><h2>Tokens, cost, latency and validity</h2><div id="charts"></div></section>
<section><h2>Manual rating</h2><form id="rating" class="grid"><label>Turn<select name="comparison_turn_id" id="rating-turn"></select></label><label>Scientific usefulness<input name="scientific_usefulness" type="number" min="1" max="5" value="3"></label><label>Clarity<input name="clarity" type="number" min="1" max="5" value="3"></label><label>Novelty<input name="novelty" type="number" min="1" max="5" value="3"></label><label>Would execute<select name="would_execute"><option>uncertain</option><option>yes</option><option>no</option></select></label><label>Comment<input name="comment"></label><button>Save append-only rating</button></form></section>
"""
    script = f"""
const sid={json.dumps(suite_id)};let current;
function table(turns){{return `<table><thead><tr><th>Arm</th><th>Contract</th><th>Status</th><th>Usage</th><th>Latency</th><th>Validity</th><th>Decision</th><th>Targets</th></tr></thead><tbody>${{turns.map(t=>`<tr><td>${{esc(t.display_name)}}</td><td>${{esc(t.model)}}:${{esc(t.reasoning_effort)}}<br>${{esc(t.context_mode)}}</td><td>${{esc(t.lifecycle_status)}}<br>final ${{esc(t.final_answer_present)}} / usage ${{esc(t.usage_present)}}</td><td>in ${{fmt(t.input_tokens)}} / cached ${{fmt(t.cached_input_tokens)}} / cache-write ${{fmt(t.cache_write_input_tokens)}}<br>out ${{fmt(t.output_tokens)}} / reasoning ${{fmt(t.reasoning_output_tokens)}} / total ${{fmt(t.server_reported_total_tokens)}}</td><td>${{fmt(t.first_item_latency_seconds)}} / ${{fmt(t.final_answer_latency_seconds)}} / ${{fmt(t.total_wall_seconds)}} s</td><td>schema ${{esc(t.schema_valid)}}; semantic ${{esc(t.semantic_valid)}}<br>${{esc(t.validation_issues_json)}}</td><td>${{esc(t.selected_action||'—')}} / ${{esc(t.selected_algorithm||'—')}}<details><summary>raw</summary><pre>${{esc(t.raw_decision_json||'unavailable')}}</pre></details><details><summary>normalized</summary><pre>${{esc(t.normalized_decision_json||'unavailable')}}</pre></details></td><td>lanes ${{t.active_executable_lane_count}}; candidates ${{t.active_candidate_target_count}}; history ${{t.historical_evidence_target_count}}<details><summary>action space</summary><pre>${{esc(t.applicable_action_space_json||'unavailable')}}</pre></details></td></tr>`).join('')}}</tbody></table>`}}
function bars(turns,key,label){{const max=Math.max(1,...turns.map(t=>Number(t[key]||0)));return `<h3>${{label}}</h3>${{turns.map(t=>`<div>${{esc(t.display_name)}} <span style="display:inline-block;background:#38bdf8;height:.7rem;width:${{Math.round(60*Number(t[key]||0)/max)}}%"></span> ${{fmt(t[key])}}</div>`).join('')}}`}}
function costBars(turns){{const rows=turns.map(t=>({{display_name:t.display_name,value:t.cost?.relative_cost_units}}));const max=Math.max(1,...rows.map(r=>Number(r.value||0)));return `<h3>Relative cost units</h3>${{rows.map(r=>`<div>${{esc(r.display_name)}} <span style="display:inline-block;background:#a78bfa;height:.7rem;width:${{Math.round(60*Number(r.value||0)/max)}}%"></span> ${{fmt(r.value)}}</div>`).join('')}}`}}
function scatter(metrics){{const pts=metrics.quality_cost_points.filter(p=>p.cost!==null&&p.quality!==null);if(!pts.length)return '<h3>Quality–cost scatter</h3><p>No manual scientific-usefulness coordinate is available; no quality point is fabricated.</p>';const max=Math.max(...pts.map(p=>p.cost),1);return `<h3>Quality–cost scatter</h3><svg viewBox="0 0 620 260" role="img" aria-label="relative cost versus manual scientific usefulness"><line x1="45" y1="220" x2="600" y2="220" stroke="#7f96aa"/><line x1="45" y1="20" x2="45" y2="220" stroke="#7f96aa"/>${{pts.map((p,i)=>{{const x=45+520*p.cost/max,y=220-40*p.quality;return `<circle cx="${{x}}" cy="${{y}}" r="${{p.pareto_frontier?8:5}}" fill="${{p.pareto_frontier?'#86efac':'#38bdf8'}}"><title>${{esc(p.label)}} cost ${{p.cost}}, usefulness ${{p.quality}}</title></circle><text x="${{x+8}}" y="${{y-7}}" fill="#dce8f3" font-size="10">${{esc(p.label)}}</text>`}}).join('')}}</svg><p>Large green points are nondominated only among points with both cost and human quality data.</p>`}}
async function load(){{try{{current=await api(`/api/comparisons/${{sid}}`);const s=current.suite,m=current.comparison_metrics,w=current.worker||{{}};const lease=w.lease||{{}};const heartbeat=lease.heartbeat_at?Math.max(0,(Date.now()-Date.parse(lease.heartbeat_at))/1000):null;summary.innerHTML=`<h2>${{esc(s.name)}}</h2><div class="grid">${{[['Status',s.status],['Fixture',s.fixture_reference],['Turns',`${{s.consumed_inference_starts}} / ${{s.planned_inference_count}}`],['Completed arms',`${{w.completed_arms||0}} / ${{w.planned_arms||current.arms.length}}`],['Worker PID',lease.pid??'inactive'],['Heartbeat age',heartbeat===null?'unavailable':heartbeat.toFixed(1)+' s'],['Lease',lease.released_at?'released':lease.lease_id?'active':'none'],['Stop',s.stop_state||'not requested'],['Maximum starts',s.maximum_inference_starts],['Total server tokens',w.total_server_tokens??0],['Measurement only',Boolean(s.measurement_only)],['Execute decisions',Boolean(s.execute_decisions)],['Valid response rate',m.valid_response_rate===null?'unavailable':(100*m.valid_response_rate).toFixed(1)+'%'],['Mean human usefulness',fmt(m.mean_manual_usefulness)],['Recommendation',s.recommendation_status||'pending'],['Failure',s.failure_reason||'—']].map(x=>`<div class="metric"><small>${{esc(x[0])}}</small>${{esc(x[1])}}</div>`).join('')}}</div>`;preflight.innerHTML=`<h2>Immutable preflight</h2><pre>${{esc(JSON.stringify({{suite_id:s.suite_id,plan_fingerprint:s.plan_fingerprint,fixture_sha256:s.fixture_sha256,planned_inference_count:s.planned_inference_count,maximum_inference_starts:s.maximum_inference_starts,maximum_total_server_tokens:s.maximum_total_server_tokens,maximum_client_owned_tokens_per_turn:s.maximum_client_owned_tokens_per_turn,maximum_worker_wall_seconds:s.maximum_worker_wall_seconds,maximum_stdout_bytes:s.maximum_stdout_bytes,maximum_stderr_bytes:s.maximum_stderr_bytes,maximum_wire_log_bytes:s.maximum_wire_log_bytes,maximum_artifact_directory_bytes:s.maximum_artifact_directory_bytes,timeout_seconds:s.timeout_seconds,measurement_only:Boolean(s.measurement_only),execute_decisions:Boolean(s.execute_decisions),expected_search_batches:0,expected_tool_calls:0,authorization_status:s.authorization_status,arms:current.arms.map(a=>({{order:a.effective_order,actual_order:a.actual_order,lifecycle:a.lifecycle_state,model:a.model,effort:a.reasoning_effort,context_mode:a.context_mode,model_contract:a.model_contract_matched,context_contract:a.context_contract_matched,conversation_group:a.conversation_group_id,sequence_index:a.sequence_index,prompt_sha256:a.prompt_sha256,state_sha256:a.director_state_sha256,schema_sha256:a.output_schema_sha256,cost_multiplier:a.relative_cost_multiplier_snapshot}}))}},null,2))}}</pre>`;turns.innerHTML=table(current.turns);charts.innerHTML=bars(current.turns,'server_reported_total_tokens','Server-reported total tokens')+costBars(current.turns)+bars(current.turns,'total_wall_seconds','Total latency')+`<h3>Schema / semantic validity</h3><pre>${{esc(JSON.stringify(current.turns.map(t=>({{arm:t.display_name,schema_valid:t.schema_valid,semantic_valid:t.semantic_valid}})),null,2))}}</pre><h3>Human ratings and pairwise wins/draws/losses</h3><pre>${{esc(JSON.stringify({{ratings:current.ratings,pairwise:m.pairwise}},null,2))}}</pre>`+scatter(m);document.getElementById('rating-turn').innerHTML=current.turns.filter(t=>t.lifecycle_status==='completed'&&t.schema_valid&&t.semantic_valid).map(t=>`<option value="${{esc(t.comparison_turn_id)}}">${{esc(t.display_name)}}</option>`).join('')}}catch(e){{notice.textContent=e.message}}}}
prepare.onclick=async()=>{{try{{await api(`/api/comparisons/${{sid}}/prepare`,{{method:'POST',body:'{{}}'}});load()}}catch(e){{notice.textContent=e.message}}}};authorize.onclick=async()=>{{try{{await api(`/api/comparisons/${{sid}}/authorize`,{{method:'POST',body:JSON.stringify({{plan_fingerprint:current.suite.plan_fingerprint}})}});load()}}catch(e){{notice.textContent=e.message}}}};start.onclick=async()=>{{try{{await api(`/api/comparisons/${{sid}}/start`,{{method:'POST',body:'{{}}'}});load()}}catch(e){{notice.textContent=e.message}}}};stop.onclick=async()=>{{try{{await api(`/api/comparisons/${{sid}}/stop`,{{method:'POST',body:'{{}}'}});load()}}catch(e){{notice.textContent=e.message}}}};
rating.onsubmit=async e=>{{e.preventDefault();const f=new FormData(e.target);const p=Object.fromEntries(f);for(const k of ['scientific_usefulness','clarity','novelty'])p[k]=Number(p[k]);try{{await api(`/api/comparisons/${{sid}}/ratings`,{{method:'POST',body:JSON.stringify(p)}});load()}}catch(e){{notice.textContent=e.message}}}};async function loadAuth(){{try{{const d=await api(`/api/comparisons/${{sid}}`);document.getElementById('auth-status').textContent=JSON.stringify(d.auth_availability,null,2)}}catch(e){{notice.textContent=e.message}}}}load();loadAuth();setInterval(load,2000);
"""
    return page("Comparison suite", content, script)


def blind_page(suite_id: str) -> bytes:
    content = """
<section><p>Model, effort, context, usage, latency and cost remain hidden until rating submission.</p><div class="grid"><article><h2>Answer A</h2><pre id="a" class="blind"></pre></article><article><h2>Answer B</h2><pre id="b" class="blind"></pre></article></div><div><button data-v="left">A better</button><button data-v="equal">Equal</button><button data-v="right">B better</button><button data-v="skip">Skip</button></div><label>Optional comment<input id="comment"></label><div id="reveal"></div></section>
"""
    script = f"""
const sid={json.dumps(suite_id)};let pair=[];
let blindSeed=0;async function load(){{try{{const d=await api(`/api/comparisons/${{sid}}?blind=1`);blindSeed=d.blind_order_seed;pair=d.turns.filter(t=>t.lifecycle_status==='completed'&&t.schema_valid).slice(0,2);if(pair.length<2)throw new Error('Two completed schema-valid turns are required');a.textContent=pair[0].normalized_decision_json;b.textContent=pair[1].normalized_decision_json}}catch(e){{notice.textContent=e.message}}}}document.querySelectorAll('[data-v]').forEach(x=>x.onclick=async()=>{{try{{await api(`/api/comparisons/${{sid}}/pairwise-ratings`,{{method:'POST',body:JSON.stringify({{left_turn_id:pair[0].comparison_turn_id,right_turn_id:pair[1].comparison_turn_id,preferred:x.dataset.v,comment:comment.value,blind_order_seed:blindSeed}})}});const full=await api(`/api/comparisons/${{sid}}`);reveal.innerHTML=`<p>Revealed: A = ${{esc(full.turns.find(t=>t.comparison_turn_id===pair[0].comparison_turn_id).display_name)}}; B = ${{esc(full.turns.find(t=>t.comparison_turn_id===pair[1].comparison_turn_id).display_name)}}</p>`}}catch(e){{notice.textContent=e.message}}}});load();
"""
    return page("Blind pairwise comparison", content, script)


def cost_profiles_page(catalog: dict[str, list[str]]) -> bytes:
    content = """
<section><p>Relative multipliers are user-configured. API rates are optional estimates and are never subscription charges.</p><form id="profile" class="grid"><label>Model<select name="model" id="model"></select></label><label>Effort<select name="reasoning_effort"><option>medium</option><option>high</option><option>xhigh</option></select></label><label>Display name<input name="display_name" required></label><label>Relative multiplier<input name="relative_cost_multiplier" type="number" min="0" step="0.001" value="1"></label><label>API input / million<input name="api_input_per_million" type="number" min="0" step="0.0001"></label><label>API cached input / million<input name="api_cached_input_per_million" type="number" min="0" step="0.0001"></label><label>API output / million<input name="api_output_per_million" type="number" min="0" step="0.0001"></label><label>Currency<input name="currency" maxlength="12"></label><label>Source label<input name="source_label" required></label><label>Effective from<input name="effective_from" required></label><button>Append profile</button></form></section><section><pre id="profiles"></pre></section>
"""
    script = f"""
const catalog={json.dumps(catalog, sort_keys=True)};model.innerHTML=Object.keys(catalog).map(x=>`<option>${{esc(x)}}</option>`).join('');
async function load(){{try{{profiles.textContent=JSON.stringify(await api('/api/model-cost-profiles'),null,2)}}catch(e){{notice.textContent=e.message}}}}profile.onsubmit=async e=>{{e.preventDefault();const f=Object.fromEntries(new FormData(e.target));for(const k of ['relative_cost_multiplier','api_input_per_million','api_cached_input_per_million','api_output_per_million'])f[k]=f[k]===''?null:Number(f[k]);f.enabled=true;try{{await api('/api/model-cost-profiles',{{method:'POST',body:JSON.stringify(f)}});load()}}catch(e){{notice.textContent=e.message}}}};load();
"""
    return page("Model cost profiles", content, script)
