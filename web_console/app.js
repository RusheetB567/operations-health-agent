/* Local operations console. No third-party scripts or telemetry. */
'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let model = null, editing = null, deleting = null, loading = false, toastTimer;
const titles = {
 reliability: ['RELIABILITY OVER TIME', 'Turn observations into objectives.', 'Understand sampled health, evidence coverage and your failure allowance.', 'Reliability'],
 incidents: ['RESPOND WITH CONTEXT', 'Give every failure a clear next step.', 'Acknowledge failures, record your investigation and verify recovery.', 'Incidents'],
 overview: ['YOUR OPERATIONS, IN ONE PLACE', 'A clearer view of your services.', 'Check what’s running. Understand what isn’t. Keep the evidence.', 'Overview'],
 services: ['YOUR SERVICE LANDSCAPE', 'Every endpoint, accounted for.', 'Connect, pause and check the services running on this device.', 'Services'],
 runs: ['OBSERVATION HISTORY', 'Know what changed.', 'Inspect completed checks and compare the observations over time.', 'Check history'],
 triage: ['FROM NOISE TO SIGNAL', 'Find the pattern in your logs.', 'Summarise errors locally without retaining raw messages.', 'Log triage'],
 evidence: ['KEEP THE CONTEXT', 'Evidence you can inspect.', 'Review existing investigation packs and verify their integrity.', 'Evidence library']
};
function toast(message, bad=false) {
 clearTimeout(toastTimer); $('toast').textContent = message; $('toast').className = 'toast' + (bad ? ' bad' : ''); $('toast').hidden=false;
 toastTimer=setTimeout(() => $('toast').hidden=true, 5000);
}
async function api(path, method='GET', body) {
 const response = await fetch(path, {method, headers: {'X-Console-Token': document.querySelector('meta[name="console-token"]').content, ...(body === undefined ? {} : {'Content-Type':'application/json'})}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
 const result = await response.json();
 if (!response.ok) throw new Error(result.error || 'The request could not complete.');
 return result;
}
const badge = state => `<span class="badge ${esc(state)}">${esc(state.replaceAll('_',' '))}</span>`;
const date = value => value ? new Date(value).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : 'Not checked';
const duration = value => Number.isFinite(value) ? `${Math.round(value)} ms` : '—';
const empty = (title, description) => `<div class="empty-state"><div class="empty-icon">⌁</div><strong>${esc(title)}</strong><p>${esc(description)}</p></div>`;
function serviceTable(items, compact=false) {
 if (!items.length) return empty('No services here yet', 'Add a local endpoint or start the controlled lab.');
 return `<div class="table-wrap"><table><thead><tr><th>Service</th><th>Status</th><th>Duration</th>${compact ? '' : '<th>Group</th>'}<th>Actions</th></tr></thead><tbody>${items.map(s => `<tr><td><div class="service-cell"><span class="service-glyph">${s.type === 'http' ? 'H' : 'T'}</span><div><div class="service-name">${esc(s.name)} ${s.is_demo ? '<span class="protocol">LAB</span>' : ''}</div><div class="service-target" title="${esc(s.target)}">${esc(s.target)}</div></div></div></td><td>${badge(!s.enabled ? 'paused' : s.maintenance ? 'maintenance' : s.last?.status || 'unchecked')}</td><td class="mono">${duration(s.last?.detail?.duration_ms)}</td>${compact ? '' : `<td>${esc(s.group)}</td>`}<td><div class="row-actions"><button class="text-button" data-check="${s.id}" ${!s.enabled || s.maintenance || model.active_run ? 'disabled' : ''}>Check</button>${compact ? '' : `<button class="text-button" data-edit="${s.id}">Edit</button><button class="text-button" data-toggle="${s.id}">${s.enabled ? 'Pause' : 'Enable'}</button><button class="text-button" data-maintenance="${s.id}">${s.maintenance ? 'View maintenance' : 'Maintenance'}</button><button class="text-button destructive" data-delete="${s.id}">Remove</button>`}</div></td></tr>`).join('')}</tbody></table></div>`;
}
function runTable(items) {
 if (!items.length) return empty('Your check history starts here', 'Run a check to save an observation.');
 return `<div class="table-wrap"><table><thead><tr><th>Started</th><th>State</th><th>Trigger</th><th>Healthy / total</th><th>Actions</th></tr></thead><tbody>${items.map(r => `<tr><td>${date(r.started_at)}</td><td>${badge(r.state)}</td><td>${esc(r.source || 'manual')}</td><td>${r.report ? `${r.report.summary.healthy} / ${r.report.summary.total}` : '—'}</td><td><button class="text-button" data-run="${r.id}">View details</button></td></tr>`).join('')}</tbody></table></div>`;
}
function renderServices() {
 if (!model) return;
 const search=$('service-search').value.toLowerCase(), group=$('group-filter').value;
 const items=model.services.filter(s => (!group || s.group===group) && `${s.name} ${s.target}`.toLowerCase().includes(search));
 $('service-table').innerHTML=serviceTable(items);
 $('service-count-label').textContent=`${items.length} of ${model.services.length} services`;
}
function render() {
 const {summary:s,services,runs,host,lab}=model;
 renderIncidents();
 renderSchedule();
 renderMaintenance();
 renderRunChoices();
 $('nav-service-count').textContent=s.total;
 $('metric-enabled').textContent=s.enabled; $('metric-healthy').textContent=s.healthy; $('metric-warning').textContent=s.warning;
 $('metric-enabled-caption').textContent=`${s.total-s.enabled} paused · ${s.maintenance} in maintenance · ${s.unchecked} unchecked`;
 $('metric-warning-caption').textContent=s.warning ? 'Review the latest observations' : 'No warnings in checked services';
 $('metric-duration').textContent=duration(s.p95_ms);
 $('overview-service-table').innerHTML=serviceTable(services.slice(0,5),true);
 const selected=$('group-filter').value;
 $('group-filter').innerHTML='<option value="">All groups</option>'+[...new Set(services.map(s=>s.group))].sort().map(g=>`<option value="${esc(g)}">${esc(g)}</option>`).join('');
 $('group-filter').value=selected; renderServices();
 $('runs-table').innerHTML=runTable(runs);
 $('recent-runs').innerHTML=runs.length ? runs.slice(0,3).map(r=>`<div class="run-line"><span class="run-symbol">${r.state==='completed' ? '✓' : '⌁'}</span><div><strong>${r.report ? `${r.report.summary.total} services checked` : esc(r.state)}</strong><p>${date(r.started_at)}</p></div>${badge(r.report?.status || r.state)}<button class="text-button" data-run="${r.id}">Details</button></div>`).join('') : empty('No check runs yet','Start the lab or connect your first service.');
 const monitored=s.monitoring;
 const pct=monitored ? Math.round(s.healthy/monitored*100) : 0;
 $('health-percent').textContent=monitored ? `${pct}%` : '—';
 $('health-ring').style.background=`conic-gradient(#28a381 0% ${pct}%, #f0b74b ${pct}% ${monitored ? (s.healthy+s.warning)/monitored*100 : 0}%, #e9edf4 0%)`;
 $('health-legend').innerHTML=[['Healthy',s.healthy,'#28a381'],['Warning',s.warning,'#f0b74b'],['Unchecked',s.unchecked,'#dce2ed']].map(([label,n,color])=>`<div class="legend-item"><span class="legend-square" style="background:${color}"></span>${label}<strong>${n}</strong></div>`).join('');
 $('host-name').textContent=host.hostname; $('host-memory').textContent=`${host.memory_percent}%`; $('memory-bar').style.width=`${host.memory_percent}%`;
 $('host-uptime').textContent=`${Math.floor(host.uptime_seconds/86400)}d ${Math.floor(host.uptime_seconds%86400/3600)}h`;
 $('lab-title').textContent=!lab.loaded ? 'Meet your new operations workspace' : lab.degraded ? 'A controlled failure is ready to investigate' : 'Recovery confirmed by your next check';
 $('lab-description').textContent=!lab.loaded ? 'Start with a local lab: three real endpoints, one controlled failure, and a recovery you can verify.' : lab.degraded ? 'The lab worker returns HTTP 503. Restore it and compare the saved observations.' : 'The lab worker now returns HTTP 200. Introduce another failure whenever you want to practise.';
 $('lab-action').textContent=!lab.loaded ? 'Start local lab' : lab.degraded ? 'Recover lab worker' : 'Simulate failure';
 $('lab-action').disabled=Boolean(model.active_run);
 $('run-checks-button').disabled=Boolean(model.active_run) || !s.monitoring;
 $('run-checks-button').querySelector('span').textContent=model.active_run ? 'Checking…' : 'Run checks';
 $('updated-at').textContent=`Updated ${new Date().toLocaleTimeString()}`;
}
async function refresh() {
 if (loading) return;
 loading=true;
 try { model=await api('/api/overview'); render(); $('connection-error').hidden=true; }
 catch(error) { $('connection-error').textContent=`Connection interrupted. ${error.message}`; $('connection-error').hidden=false; }
 finally { loading=false; }
}
async function change(path,method,body) {
 try { const result=await api(path,method,body); await refresh(); return result; }
 catch(error) { toast(error.message,true); return null; }
}
function navigate() {
 const view=location.hash.slice(1) in titles ? location.hash.slice(1) : 'overview';
 document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==`page-${view}`);
 document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b.dataset.view===view); b.setAttribute('aria-current',b.dataset.view===view ? 'page' : 'false');});
 const t=titles[view]; ['page-eyebrow','page-title','page-subtitle','breadcrumb-label'].forEach((id,i)=>$(id).textContent=t[i]);
 if(view==='reliability') loadReliability();
 if(view==='evidence') loadEvidence();
 if(view==='triage') api('/api/triage/latest').then(r=>renderTriage(r.summary)).catch(e=>toast(e.message,true));
}
function openService(id=null) {
 editing=id; const s=model.services.find(s=>s.id===id);
 $('service-form').reset(); $('service-form-error').hidden=true;
 $('service-dialog-title').textContent=s ? 'Edit local service' : 'Connect a service';
 for(const [id,key] of [['name','name'],['group','group'],['type','type'],['target','target'],['timeout','timeout'],['status','expected_status']]) if(s) $(`field-${id}`).value=s[key];
 $('expected-status-label').hidden=$('field-type').value!=='http';
 $('service-dialog').showModal();
}
$('service-form').addEventListener('submit',async event=>{
 event.preventDefault(); const button=$('save-service-button'); button.disabled=true;
 try {
  const existing=model.services.find(s=>s.id===editing);
  const payload={name:$('field-name').value,group:$('field-group').value,type:$('field-type').value,target:$('field-target').value,timeout:Number($('field-timeout').value),expected_status:Number($('field-status').value),enabled:existing?.enabled ?? true};
  await api(editing ? `/api/services/${editing}` : '/api/services',editing ? 'PATCH' : 'POST',payload);
  $('service-dialog').close(); await refresh(); toast('Service saved. Run a check to observe its health.');
 } catch(e) { $('service-form-error').textContent=e.message; $('service-form-error').hidden=false; }
 finally {button.disabled=false;}
});
$('field-type').addEventListener('change',()=>{$('expected-status-label').hidden=$('field-type').value!=='http';});
$('add-service-button').onclick=()=>openService();
$('refresh-button').onclick=()=>{refresh(); if(location.hash==='#evidence') loadEvidence();};
$('run-checks-button').onclick=()=>change('/api/checks','POST',{});
$('lab-action').onclick=()=>change('/api/demo','POST',{action:!model.lab.loaded ? 'seed' : model.lab.degraded ? 'recover' : 'degrade'});
$('service-search').oninput=renderServices; $('group-filter').onchange=renderServices;
document.addEventListener('click',async event=>{
 const button=event.target.closest('button'); if(!button) return;
 const d=button.dataset;
 if(d.view || d.go) location.hash=d.view || d.go;
 if(d.close) $(d.close).close();
 if(d.incident) openIncident(d.incident);
 if(d.maintenance) openMaintenance(d.maintenance);
 if(d.endMaintenance) {if(await change(`/api/maintenance/${d.endMaintenance}/end`,'POST',{})) {toast('Maintenance ended. The next check can observe this service.');}}
 if(d.objective) openObjective(d.objective);
 if(d.edit) openService(d.edit);
 if(d.check) await change('/api/checks','POST',{service_ids:[d.check]});
 if(d.toggle) {
  const s=model.services.find(s=>s.id===d.toggle);
  const payload=Object.fromEntries(['name','group','type','target','timeout','expected_status','enabled'].map(k=>[k,s[k]])); payload.enabled=!s.enabled;
  await change(`/api/services/${s.id}`,'PATCH',payload);
 }
 if(d.delete) {deleting=d.delete; $('delete-description').textContent=`Remove ${model.services.find(s=>s.id===deleting).name} from this workspace?`; $('delete-dialog').showModal();}
 if(d.run) {
  const r=model.runs.find(r=>r.id===d.run);
  $('run-details').innerHTML=`<div class="run-detail-summary">${badge(r.state)} <span>${date(r.started_at)}</span></div>${r.error ? `<p>${esc(r.error)}</p>` : ''}${r.report ? `<p>${r.report.summary.healthy} healthy · ${r.report.summary.warning} warnings</p><div class="table-wrap"><table><thead><tr><th>Service</th><th>Status</th><th>Observation</th><th>Duration</th></tr></thead><tbody>${r.report.services.map(s=>`<tr><td>${esc(s.name)}</td><td>${badge(s.status)}</td><td>${esc(s.detail.status)}${s.detail.http_status ? ` · HTTP ${esc(s.detail.http_status)}` : ''}</td><td>${duration(s.detail.duration_ms)}</td></tr>`).join('')}</tbody></table></div>` : '<p>The run has no completed report yet.</p>'}`;
  $('run-dialog').showModal();
 }
 if(d.verify) {
  button.disabled=true; button.textContent='Verifying…';
  try {const r=await api(`/api/evidence/${encodeURIComponent(d.verify)}/verify`,'POST',{}); toast(r.status==='verified' ? 'All declared evidence files verified.' : `Evidence needs review: ${(r.issues || []).length} issues.`,r.status!=='verified'); await loadEvidence();}
  catch(e){toast(e.message,true); button.disabled=false;button.textContent='Verify integrity';}
 }
});
$('confirm-delete').onclick=async()=>{if(await change(`/api/services/${deleting}`,'DELETE')) {$('delete-dialog').close();toast('Service removed. Previous check history was kept.');}};
$('sample-log').onclick=()=>{
 const timestamp=new Date().toISOString(); $('log-input').value=['request timed out after 3 seconds','request timed out after 3 seconds','database connection refused','worker started'].map((message,i)=>JSON.stringify({timestamp,level:i===3 ? 'INFO' : 'ERROR',message})).join('\n');
};
$('log-file').onchange=async event=>{
 const file=event.target.files[0]; if(!file)return;
 if(file.size>262144){toast('Choose a file smaller than 256 KiB.',true);event.target.value='';return;}
 try{$('log-input').value=await file.text();}catch(e){toast('The file could not be read.',true);}
};
function renderTriage(r) {
 if(!r){$('triage-results').innerHTML=empty('A useful summary starts here','Paste a log or load the sample to inspect recurring errors.');return;}
 $('triage-results').innerHTML=`<div class="triage-cards">${[['Records',r.counts.selected_records],['Errors',(r.levels.ERROR || 0)+(r.levels.CRITICAL || 0)],['Malformed',r.counts.malformed_lines]].map(([label,n])=>`<div class="triage-card"><strong>${n}</strong><span>${label}</span></div>`).join('')}</div>${r.truncated ? '<div class="notice info">Input limit reached. This is a partial summary.</div>' : ''}<h3 class="section-label">ERROR CATEGORIES</h3>${Object.entries(r.categories).map(([c,n])=>`<div class="category-line"><span>${esc(c)}</span><strong>${n}</strong></div>`).join('') || '<p class="muted">No classified errors.</p>'}<h3 class="section-label">RECURRING PATTERNS</h3>${r.patterns.slice(0,10).map(p=>`<div class="pattern-item"><div><strong>${esc(p.category)}</strong><span>${p.count} occurrence${p.count===1 ? '' : 's'}</span></div><code>${esc(p.fingerprint.slice(0,18))}</code></div>`).join('') || '<p class="muted">No error patterns found.</p>'}<p class="small-note left">Fingerprints are private to this analysis. Raw messages are not saved.</p>`;
}
$('triage-button').onclick=async()=>{
 const b=$('triage-button');b.disabled=true;b.textContent='Analysing…';
 try {const r=await api('/api/triage','POST',{text:$('log-input').value});renderTriage(r);$('log-input').value='';$('log-file').value='';toast('Summary saved locally. Raw input discarded.');}
 catch(e){toast(e.message,true);}finally{b.disabled=false;b.textContent='Analyse log';}
};
async function loadEvidence() {
 try {const r=await api('/api/evidence');$('evidence-grid').innerHTML=r.items.length ? r.items.map(e=>`<article class="panel evidence-card"><div class="evidence-icon">▱</div><h2>${esc(e.name)}</h2><p class="muted">${date(e.created_at)}</p><div class="evidence-status">${badge(e.status)} ${badge(e.integrity)}</div><div class="evidence-numbers"><div><strong>${e.events}</strong><span>Events</span></div><div><strong>${e.errors}</strong><span>Errors</span></div><div><strong>${e.artifacts}</strong><span>Files</span></div></div><div class="evidence-actions"><button class="button secondary" data-verify="${esc(e.name)}">Verify integrity</button><a class="button primary" target="_blank" rel="noopener" href="/api/evidence/${encodeURIComponent(e.name)}/timeline">Open timeline</a></div></article>`).join('') : empty('No investigation packs yet','Existing packs in reports/investigations appear here automatically.');}
 catch(e){$('evidence-grid').innerHTML=empty('Evidence unavailable',e.message);}
}
let incidentSelection = null;
function renderIncidents() {
 const items=model.incidents || [];
 for(const state of ['open','acknowledged','resolved']) $(`incidents-${state}`).textContent=items.filter(i=>i.state===state).length;
 $('nav-incident-count').textContent=items.filter(i=>i.state!=='resolved').length;
 const filter=$('incident-filter').value;
 const shown=items.filter(i=>filter==='all' || (filter==='active' ? i.state!=='resolved' : i.state==='resolved'));
 $('incident-table').innerHTML=shown.length ? `<div class="table-wrap"><table><thead><tr><th>Service</th><th>Status</th><th>Owner</th><th>Failed checks</th><th>Last warning</th><th>Actions</th></tr></thead><tbody>${shown.map(i=>`<tr><td><strong>${esc(i.service_name)}</strong><div class="service-target">${esc(i.target)}</div></td><td>${badge(i.state)}</td><td>${esc(i.owner || 'Unassigned')}</td><td>${i.failures}</td><td>${date(i.last_seen)}</td><td><button class="text-button" data-incident="${i.id}">Investigate</button></td></tr>`).join('')}</tbody></table></div>` : empty('No incidents in this view', 'Run a check or use the local lab to investigate a controlled failure.');
}
function openIncident(identity) {
 const incident=model.incidents.find(i=>i.id===identity); if(!incident)return;
 incidentSelection={id:identity,version:incident.version};
 $('export-notes').checked=false;
 resetIncidentExport();
 $('incident-title').textContent=incident.service_name;
 $('incident-summary').innerHTML=`<div class="run-detail-summary">${badge(incident.state)}<span>Opened ${date(incident.opened_at)}</span></div><p class="mono incident-target">${esc(incident.target)}</p><p>${incident.failures} failed checks observed${incident.resolution ? ` · ${esc(incident.resolution.replaceAll('_',' '))} at ${date(incident.resolved_at)}` : ''}</p>`;
 $('incident-owner').value=incident.owner; $('incident-note').value=''; $('incident-form-error').hidden=true;
 $('incident-owner').disabled=incident.state==='resolved';
 $('incident-acknowledge').hidden=incident.state!=='open'; $('incident-assign').hidden=incident.state==='resolved';
 $('incident-events').innerHTML=incident.events.map(e=>`<article class="incident-event"><div><strong>${esc(e.kind)}</strong><time>${date(e.created_at)}</time></div><p>${esc(e.detail)}</p></article>`).join('');
 if(!$('incident-dialog').open)$('incident-dialog').showModal();
}
async function updateIncident(action) {
 if(!incidentSelection)return;
 const controls=[...$('incident-form').querySelectorAll('button')];controls.forEach(b=>b.disabled=true);
 try {
  await api(`/api/incidents/${incidentSelection.id}`,'PATCH',{version:incidentSelection.version,action,owner:$('incident-owner').value,note:$('incident-note').value});
  await refresh();openIncident(incidentSelection.id);toast('Incident updated.');
 } catch(error) {$('incident-form-error').textContent=error.message;$('incident-form-error').hidden=false;}
 finally {controls.forEach(b=>b.disabled=false);}
}
$('incident-filter').onchange=renderIncidents;
$('incident-form').onsubmit=event=>{event.preventDefault();updateIncident('acknowledge');};
$('incident-assign').onclick=()=>updateIncident('assign');
$('incident-add-note').onclick=()=>updateIncident('note');
let scheduleBusy = false, scheduleInitialised = false;
function renderSchedule() {
 const schedule=model.schedule;
 if(!schedule)return;
 $('schedule-state').textContent=schedule.enabled ? 'Running' : 'Stopped';
 $('schedule-state').className='badge '+(schedule.enabled ? 'healthy' : 'paused');
 $('schedule-next').textContent=schedule.enabled ? `Next check: ${date(schedule.next_check_at)} · every ${schedule.interval_seconds} seconds` : 'Schedules are stopped. Manual checks remain available.';
 $('schedule-last').textContent=`${schedule.last_result}. Schedules stay stopped after a console restart.`;
 if(!scheduleInitialised){$('schedule-interval').value=schedule.interval_seconds;scheduleInitialised=true;}
 $('schedule-start').textContent=schedule.enabled ? 'Update interval' : 'Start schedule';
 $('schedule-start').disabled=scheduleBusy;
 $('schedule-stop').disabled=scheduleBusy || !schedule.enabled;
}
async function setSchedule(enabled) {
 const interval=Number($('schedule-interval').value);
 if(enabled && !$('schedule-form').reportValidity())return;
 scheduleBusy=true;renderSchedule();
 try {
  await api('/api/schedule','PATCH',{enabled,interval_seconds:enabled ? interval : model.schedule.interval_seconds});
  await refresh();toast(enabled ? 'Schedule enabled. First check runs after the selected interval.' : 'Schedule stopped. A running check will finish.');
 } catch(error){toast(error.message,true);}
 finally{scheduleBusy=false;renderSchedule();}
}
$('schedule-form').onsubmit=event=>{event.preventDefault();setSchedule(true);};
$('schedule-stop').onclick=()=>setSchedule(false);
let maintenanceService = null;
const windowDate=value=>date(new Date(value*1000).toISOString());
function renderMaintenance() {
 const windows=model.maintenance_windows || [];
 $('maintenance-history').innerHTML=windows.length ? `<div class="table-wrap"><table><thead><tr><th>Service</th><th>Reason</th><th>Status</th><th>Planned end</th><th>Actions</th></tr></thead><tbody>${windows.map(w=>`<tr><td>${esc(w.service_name)}</td><td class="maintenance-reason">${esc(w.reason)}</td><td>${badge(w.state)}</td><td>${windowDate(w.expires_at)}</td><td>${w.state==='active' ? `<button class="text-button" data-end-maintenance="${w.id}">End now</button>` : '—'}</td></tr>`).join('')}</tbody></table></div>` : empty('No maintenance windows yet','Use a service’s Maintenance control before planned work.');
}
function openMaintenance(identity) {
 const service=model.services.find(s=>s.id===identity);if(!service)return;
 if(service.maintenance){location.hash='services';toast(`Maintenance until ${windowDate(service.maintenance.expires_at)}: ${service.maintenance.reason}`);return;}
 maintenanceService=identity;
 $('maintenance-service-name').textContent=service.name;
 $('maintenance-form').reset();$('maintenance-error').hidden=true;
 $('maintenance-dialog').showModal();
}
$('maintenance-form').onsubmit=async event=>{
 event.preventDefault();$('maintenance-save').disabled=true;
 try {
  await api(`/api/services/${maintenanceService}/maintenance`,'POST',{duration_minutes:Number($('maintenance-duration').value),reason:$('maintenance-reason').value});
  $('maintenance-dialog').close();await refresh();toast('Maintenance started. Existing incidents stay open.');
 }catch(error){$('maintenance-error').textContent=error.message;$('maintenance-error').hidden=false;}
 finally{$('maintenance-save').disabled=false;}
};
const comparisonLabels={new_failure:'New failure',recovered:'Recovered',ongoing_failure:'Ongoing failure',unchanged_healthy:'Still healthy',added_to_run:'Added to run',absent_from_run:'Absent from run',configuration_changed:'Configuration changed',maintenance_boundary:'Maintenance boundary'};
let comparisonBusy=false;
function renderRunChoices() {
 const completed=model.runs.filter(r=>r.state==='completed');
 for(const id of ['compare-baseline','compare-current']) {
  const select=$(id),previous=select.value;
  if(document.activeElement===select)continue;
  select.innerHTML=completed.map(r=>`<option value="${r.id}">${date(r.started_at)} · ${esc(r.source || 'manual')} · ${r.report.summary.healthy}/${r.report.summary.total} healthy · ${r.id.slice(0,6)}</option>`).join('');
  if(completed.some(r=>r.id===previous))select.value=previous;
  else select.value=(id==='compare-baseline' ? completed[1] : completed[0])?.id || '';
 }
 $('compare-submit').disabled=comparisonBusy || completed.length<2;
 if(completed.length<2 && !$('compare-results').hasChildNodes())$('compare-results').innerHTML=empty('Two completed runs are needed','Run checks before and after a change, then compare the observations.');
}
$('compare-form').onsubmit=async event=>{
 event.preventDefault();comparisonBusy=true;$('compare-submit').disabled=true;$('compare-error').hidden=true;
 try {
  const report=await api('/api/runs/compare','POST',{baseline_id:$('compare-baseline').value,current_id:$('compare-current').value});
  const changes=Object.entries(report.counts).filter(([,count])=>count>0);
  $('compare-results').innerHTML=`<div class="comparison-summary">${changes.map(([key,count])=>`<div><strong>${count}</strong><span>${comparisonLabels[key]}</span></div>`).join('')}</div><p class="small-note left comparison-caption">Baseline ${date(report.baseline.started_at)} compared with ${date(report.current.started_at)}. Absent services may be paused, in maintenance or outside a partial check. Duration differences are observations, not a performance guarantee.</p><div class="table-wrap"><table><thead><tr><th>Service</th><th>Change</th><th>Before</th><th>After</th><th>Duration difference</th></tr></thead><tbody>${report.services.map(s=>`<tr><td>${esc(s.name)}</td><td>${comparisonLabels[s.classification]}</td><td>${s.previous_status ? badge(s.previous_status) : 'Not observed'}</td><td>${s.current_status ? badge(s.current_status) : 'Not observed'}</td><td class="mono">${s.duration_delta_ms===null ? 'Not comparable' : `${s.duration_delta_ms>0 ? '+' : ''}${s.duration_delta_ms} ms`}</td></tr>`).join('')}</tbody></table></div>`;
 }catch(error){$('compare-error').textContent=error.message;$('compare-error').hidden=false;$('compare-results').replaceChildren();}
 finally{comparisonBusy=false;renderRunChoices();}
};
let incidentExport=null;
function resetIncidentExport() {
 incidentExport=null;$('export-save-local').disabled=true;$('export-saved').hidden=true;$('export-download').disabled=true;$('export-content').hidden=true;$('export-content').textContent='';$('export-summary').hidden=true;$('export-error').hidden=true;
}
$('export-format').onchange=resetIncidentExport;
$('export-notes').onchange=resetIncidentExport;
$('export-preview').onclick=async()=>{
 if(!incidentSelection)return;
 const selected=incidentSelection.id,format=$('export-format').value,includeNotes=$('export-notes').checked;
 resetIncidentExport();$('export-preview').disabled=true;
 try {
  const result=await api(`/api/incidents/${selected}/export`,'POST',{format,include_notes:includeNotes});
  if(incidentSelection.id!==selected || $('export-format').value!==format || $('export-notes').checked!==includeNotes)return;
  incidentExport=result;$('export-content').textContent=result.content;$('export-content').hidden=false;
  $('export-summary').textContent=`${result.summary.state} · ${result.summary.activity_entries} activity entries · ${result.summary.evidence_entries} retained observations · notes ${result.summary.notes_included ? 'included' : 'excluded'}`;
  $('export-summary').hidden=false;$('export-download').disabled=false;$('export-save-local').disabled=false;
 } catch(error){$('export-error').textContent=error.message;$('export-error').hidden=false;}
 finally{$('export-preview').disabled=false;}
};
$('export-save-local').onclick=async()=>{
 if(!incidentExport)return;
 const preview=incidentExport.preview_id;$('export-save-local').disabled=true;$('export-error').hidden=true;
 try {
  const saved=await api(`/api/exports/${preview}/save`,'POST',{});
  if(incidentExport?.preview_id!==preview)return;
  $('export-saved').textContent=`Saved: ${saved.path} · ${saved.bytes} bytes · SHA-256: ${saved.sha256}`;$('export-saved').hidden=false;
  toast('Previewed report saved in reports/incident-exports.');
 }catch(error){$('export-error').textContent=error.message;$('export-error').hidden=false;}
 finally{if(incidentExport?.preview_id===preview)$('export-save-local').disabled=false;}
};
$('export-download').onclick=()=>{
 if(!incidentExport)return;
 const url=URL.createObjectURL(new Blob([incidentExport.content],{type:incidentExport.media_type+';charset=utf-8'}));
 const link=document.createElement('a');link.href=url;link.download=incidentExport.filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
 toast('Report downloaded locally. Review it before sharing.');
};
let reliabilityData=null,reliabilityLoading=false,objectiveService=null;
const objectiveLabels={met:'Meeting target',below_target:'Below target',insufficient_data:'Need more samples'};
async function loadReliability() {
 if(reliabilityLoading)return;reliabilityLoading=true;
 try {
  reliabilityData=await api('/api/reliability');const services=reliabilityData.services;
  $('reliability-met').textContent=services.filter(s=>s.status==='met').length;
  $('reliability-below').textContent=services.filter(s=>s.status==='below_target').length;
  $('reliability-insufficient').textContent=services.filter(s=>s.status==='insufficient_data').length;
  $('reliability-table').innerHTML=services.length ? `<div class="table-wrap"><table><thead><tr><th>Service</th><th>Objective</th><th>Observed healthy</th><th>Evidence</th><th>Remaining allowance</th><th>Assessment</th><th>Actions</th></tr></thead><tbody>${services.map(s=>`<tr><td><strong>${esc(s.name)}</strong><div class="muted">${esc(s.group)}${!s.enabled ? ' · paused' : s.maintenance ? ' · maintenance' : ''}</div></td><td>${s.target_percent}% over ${s.window_hours}h<div class="muted">${s.configured ? 'Saved objective' : 'Suggested default'}</div></td><td>${s.achieved_percent===null ? 'No observations' : `${s.achieved_percent}%`}</td><td>${s.healthy} healthy / ${s.samples} checks<div class="muted">Minimum ${s.min_samples}</div></td><td>${s.samples ? `${s.remaining_allowance} checks` : 'No allowance yet'}</td><td><span class="badge ${s.status}">${objectiveLabels[s.status]}</span></td><td><button class="text-button" data-objective="${s.id}">Set objective</button></td></tr>`).join('')}</tbody></table></div>` : empty('No services to evaluate','Add a local service or start the lab, then collect check observations.');
  $('reliability-updated').textContent=`Evaluated ${date(reliabilityData.as_of)}. History retention is limited to 200 runs; sparse/manual checks may be unrepresentative.`;
 }catch(error){$('reliability-table').innerHTML=empty('Could not load reliability',error.message);}
 finally{reliabilityLoading=false;}
}
function openObjective(identity) {
 const service=reliabilityData?.services.find(s=>s.id===identity);if(!service)return;
 objectiveService=identity;$('objective-name').textContent=service.name;
 $('objective-target').value=service.target_percent;$('objective-window').value=service.window_hours;$('objective-minimum').value=service.min_samples;
 $('objective-error').hidden=true;$('objective-dialog').showModal();
}
$('objective-form').onsubmit=async event=>{
 event.preventDefault();$('objective-save').disabled=true;
 try {
  await api(`/api/services/${objectiveService}/objective`,'PATCH',{target_percent:Number($('objective-target').value),window_hours:Number($('objective-window').value),min_samples:Number($('objective-minimum').value)});
  $('objective-dialog').close();await loadReliability();toast('Service objective saved.');
 }catch(error){$('objective-error').textContent=error.message;$('objective-error').hidden=false;}
 finally{$('objective-save').disabled=false;}
};
$('reliability-refresh').onclick=loadReliability;
setInterval(()=>{if(!document.hidden && location.hash==='#reliability')loadReliability();},10000);
window.addEventListener('hashchange',navigate);
navigate();refresh();
setInterval(()=>{if(!document.hidden)refresh();},2000);

