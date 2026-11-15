'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const NS = 'http://www.w3.org/2000/svg';
  const permanentUrl = 'https://kilman-augustus--stoa-evidence-web.us-east.modal.run/';
  const nativePreview = ['localhost','127.0.0.1','[::1]'].includes(location.hostname) || location.hostname.endsWith('.trycloudflare.com');
  const state = { doc: null, page: null, answer: null, selected: null, busy: false, view: null, fit: true, requestPage: null, drag: null };
  const names = { native_source: 'Printed source evidence', calculated_from_source: 'Calculated from source evidence', model_proposed_unverified: 'Model-proposed evidence - review', none: 'No supporting evidence' };
  const statuses = { answered: 'Answered', needs_review: 'Review required', unsupported: 'Unsupported', error: 'Error' };
  const roles = { room_boundary: 'Room boundary', room_label: 'Room label', area_label: 'Printed area', scale_bar: 'Scale reference' };
  const units = { m2: 'm²', m3: 'm³', m: 'm', count: '', text: '', unknown: '' };
  const node = (tag, text, className) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; };
  const svgNode = (tag, attrs) => { const n = document.createElementNS(NS, tag); for (const [k,v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
  const finite = n => typeof n === 'number' && Number.isFinite(n);
  const displayValue = n => finite(n) ? new Intl.NumberFormat('en-US', {maximumFractionDigits: 2}).format(n) : String(n);
  const dollars = n => finite(n) ? '$' + n.toFixed(Math.abs(n) > 0 && Math.abs(n) < .0001 ? 8 : 4) : 'Unknown';
  $('workspaceContext').replaceChildren(node('i'), document.createTextNode(nativePreview ? 'Native-only preview' : 'Shared demonstration'));
  $('localPreview').hidden = !nativePreview;
  function notice(message, kind = '') { $('notice').textContent = message; $('notice').dataset.state = kind; }
  function controls() {
    const loaded = !!state.doc, busy = state.busy;
    $('submit').disabled = busy || !loaded || !$('question').value.trim();
    $('question').disabled = busy || !loaded;
    $('pages').disabled = busy || !loaded;
    $('file').disabled = busy;
    $('openRun').disabled = busy || !loaded;
    for (const id of ['fitPage','zoomIn','zoomOut']) $(id).disabled = !loaded;
    $('fitEvidence').disabled = !state.selected;
    $('submit').textContent = busy ? 'Working...' : 'Ask drawing ↗';
    $('scope').textContent = state.page ? `Question scope: Page ${state.page.page_index + 1}` : 'Question scope: no page';
    $('questionForm').setAttribute('aria-busy', String(busy));
  }
  function clearAnswer() {
    state.answer = null; state.selected = null; state.requestPage = null;
    $('result').hidden = true; $('evidenceList').replaceChildren(); $('shapes').replaceChildren(); controls();
  }
  function describe(value) {
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.map(describe).join('; ');
    if (value && typeof value === 'object') {
      if (value.msg) return (Array.isArray(value.loc) ? value.loc.join('.') + ': ' : '') + describe(value.msg);
      return Object.entries(value).map(([k,v]) => `${k}: ${describe(v)}`).join('; ');
    }
    return String(value ?? 'Unknown error');
  }
  async function request(url, options) {
    const r = await fetch(url, options);
    const text = await r.text(); let data;
    try { data = JSON.parse(text); } catch { data = null; }
    if (!r.ok) throw new Error(data ? describe(data.detail ?? data) : `HTTP ${r.status}: ${text.slice(0,400) || r.statusText}`);
    if (!data) throw new Error('The server returned an invalid response.');
    return data;
  }
  $('file').addEventListener('change', async e => {
    const file = e.target.files[0]; e.target.value = ''; if (!file || state.busy) return;
    // Every document change invalidates the old answer, even when the new upload fails.
    clearAnswer(); state.doc = null; state.page = null; state.view = null;
    $('drawingSvg').setAttribute('hidden', ''); $('emptyDrawing').hidden = false; $('pages').replaceChildren(node('option','Page -'));
    $('filename').textContent = 'No drawing loaded'; $('pageSize').textContent = ''; $('viewerHint').textContent = 'Evidence stays linked to its source.'; $('zoom').textContent = '100%'; $('imageError').hidden = true; controls();
    if (file.size > 25 * 1024 * 1024) { notice('Upload failed: the maximum file size is 25 MiB.', 'error'); return; }
    if (!/\.(pdf|png|jpe?g)$/i.test(file.name)) { notice('Upload failed: choose a PDF, PNG or JPEG file.', 'error'); return; }
    state.busy = true; controls(); notice('Uploading and preparing source pages...', 'uploading');
    try {
      const form = new FormData(); form.append('file', file);
      const doc = await request('/documents', { method:'POST', body:form });
      if (!doc.document_id || !doc.pages?.length || doc.pages.some(p => !(p.width > 0 && p.height > 0) || !p.image_url)) throw new Error('The upload response has no valid source pages.');
      state.doc = doc; $('filename').textContent = file.name; $('filename').title = file.name;
      $('pages').replaceChildren(...doc.pages.map(p => { const o = node('option', `Page ${p.page_index + 1}`); o.value = p.page_index; return o; }));
      showPage(doc.pages[0].page_index); notice('Source ready. Ask about the selected page.');
    } catch (error) { notice('Upload failed: ' + error.message, 'error'); }
    finally { state.busy = false; controls(); }
  });
  function showPage(index) {
    const page = state.doc?.pages.find(p => p.page_index === Number(index)); if (!page) return;
    state.page = page; $('pages').value = page.page_index; $('pageSize').textContent = `${page.width} × ${page.height} px`;
    $('pageImage').setAttribute('href', page.image_url); $('pageImage').setAttribute('width', page.width); $('pageImage').setAttribute('height', page.height);
    $('drawingSvg').removeAttribute('hidden'); $('emptyDrawing').hidden = true; $('imageError').hidden = true;
    state.selected = null; state.fit = true; fitPage(); renderEvidence(); controls();
  }
  $('pageImage').addEventListener('error', () => { $('imageError').hidden = false; });
  $('pages').addEventListener('change', e => {
    if (state.busy) return;
    clearAnswer(); showPage(e.target.value);
    notice(`Page ${state.page.page_index + 1} selected. Ask about this page.`);
  });
  function setView(view) {
    if (!state.page) return;
    state.view = view; $('drawingSvg').setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
    const full = fullView(); $('zoom').textContent = Math.round(full.w / view.w * 100) + '%'; updateMarkers();
  }
  function fullView() {
    const p = state.page, rect = $('viewport').getBoundingClientRect(), ratio = rect.width / Math.max(rect.height,1);
    const w = Math.max(p.width * 1.07, p.height * 1.07 * ratio), h = w / ratio;
    return { x:(p.width-w)/2, y:(p.height-h)/2, w, h };
  }
  function fitPage() { if (state.page) { state.fit = true; setView(fullView()); } }
  function zoom(factor, cx, cy) {
    const v = state.view; if (!v) return; const full = fullView();
    const w = Math.max(full.w / 30, Math.min(full.w * 2, v.w / factor)), h = w * v.h/v.w;
    const x = cx ?? v.x+v.w/2, y = cy ?? v.y+v.h/2;
    state.fit = false; setView({x:x-(x-v.x)*w/v.w,y:y-(y-v.y)*h/v.h,w,h});
  }
  function fitSelected() {
    const ev = state.answer?.evidence?.find(e => e.evidence_id === state.selected); if (!ev || !state.page) return;
    const [a,b,c,d] = ev.bbox, p=state.page, ratio=fullView().w/fullView().h;
    const w = Math.max((c-a)*p.width*1.9, (d-b)*p.height*1.9*ratio, p.width*.10), h=w/ratio;
    state.fit = false; setView({x:(a+c)*p.width/2-w/2,y:(b+d)*p.height/2-h/2,w,h});
  }
  $('fitPage').addEventListener('click', fitPage); $('fitEvidence').addEventListener('click', fitSelected);
  $('zoomIn').addEventListener('click', () => zoom(1.3)); $('zoomOut').addEventListener('click', () => zoom(1/1.3));
  new ResizeObserver(() => { if (!state.page) return; if (state.fit) fitPage(); else { const v=state.view,r=$('viewport').getBoundingClientRect(),h=v.w*r.height/r.width; setView({...v,y:v.y+(v.h-h)/2,h}); } }).observe($('viewport'));
  $('drawingSvg').addEventListener('wheel', e => { e.preventDefault(); if (!state.view) return; const r=$('drawingSvg').getBoundingClientRect(),v=state.view; zoom(e.deltaY<0 ? 1.12:1/1.12,v.x+(e.clientX-r.left)/r.width*v.w,v.y+(e.clientY-r.top)/r.height*v.h); }, {passive:false});
  $('drawingSvg').addEventListener('pointerdown', e => { if (e.button!==0 || e.target.closest('[data-evidence-id]')) return; state.drag={x:e.clientX,y:e.clientY,view:{...state.view}}; $('drawingSvg').setPointerCapture(e.pointerId); });
  $('drawingSvg').addEventListener('pointermove', e => { if (!state.drag) return; const d=state.drag,r=$('drawingSvg').getBoundingClientRect(); state.fit=false; setView({...d.view,x:d.view.x-(e.clientX-d.x)*d.view.w/r.width,y:d.view.y-(e.clientY-d.y)*d.view.h/r.height}); });
  for (const type of ['pointerup','pointercancel','lostpointercapture']) $('drawingSvg').addEventListener(type, () => {state.drag=null;});
  function selectEvidence(id, focusRow = false) {
    const ev = state.answer?.evidence?.find(e => e.evidence_id===id); if (!ev || ev.document_id!==state.doc.document_id) return;
    if (state.page.page_index!==ev.page_index) showPage(ev.page_index);
    state.selected=id;
    for (const row of $('evidenceList').querySelectorAll('button')) { const chosen=row.dataset.evidenceId===id; row.setAttribute('aria-pressed',String(chosen)); if (chosen && focusRow) { row.focus({preventScroll:true}); row.scrollIntoView({block:'nearest'}); } }
    for (const shape of $('shapes').querySelectorAll('[data-evidence-id]')) shape.classList.toggle('selected',shape.dataset.evidenceId===id);
    fitSelected(); controls(); $('viewerHint').textContent = `Source ${evidenceNumber(id)} selected · Drag to pan · Scroll to zoom`;
  }
  function evidenceNumber(id) { return (state.answer?.evidence || []).findIndex(e => e.evidence_id===id)+1; }
  function updateMarkers() {
    if (!state.view) return; const px=state.view.w/Math.max($('viewport').clientWidth,1);
    for (const marker of $('shapes').querySelectorAll('.evidence-marker')) {
      const x=Number(marker.dataset.x), y=Number(marker.dataset.y),size=21*px;
      marker.setAttribute('transform',`translate(${x},${y-size})`);
      const rect=marker.querySelector('rect'); rect.setAttribute('width',size);rect.setAttribute('height',size);rect.setAttribute('rx',3*px);
      const text=marker.querySelector('text');text.setAttribute('x',size/2);text.setAttribute('y',size/2);text.setAttribute('font-size',11*px);
    }
  }
  function renderEvidence() {
    $('shapes').replaceChildren(); $('evidenceList').replaceChildren();
    const all=state.answer?.evidence || [], visible=all.filter(e => e.document_id===state.doc?.document_id && e.page_index===state.page?.page_index);
    $('evidenceCount').textContent = `${visible.length} on page / ${all.length} total`;
    $('viewerHint').textContent = state.doc ? 'Drag to pan · Scroll to zoom · Select evidence to focus' : 'Evidence stays linked to its source.';
    $('evidenceHelp').textContent = visible.length ? 'Select a source to focus the drawing.' : 'No supporting evidence on this page.';
    // Draw polygons first so small label/scale targets remain reachable.
    const ordered=[...visible].sort((a,b)=>Number(!!b.polygon)-Number(!!a.polygon));
    for (const e of ordered) {
      const p=state.page,[a,b,c,d]=e.bbox, n=evidenceNumber(e.evidence_id), caption=`Source ${n}: ${e.original_text || roles[e.role] || 'Source region'}`;
      const attrs = e.polygon?.length>=3 ? {points:e.polygon.map(([x,y])=>`${x*p.width},${y*p.height}`).join(' ')} : {x:a*p.width,y:b*p.height,width:(c-a)*p.width,height:(d-b)*p.height};
      const shape=svgNode(e.polygon?.length>=3 ? 'polygon':'rect',{...attrs,class:`evidence-shape${e.role==='scale_bar'?' scale':''}${e.method==='model_proposed'?' proposed':''}`,tabindex:0,role:'button','aria-label':caption,'data-evidence-id':e.evidence_id});
      const title=svgNode('title',{});title.textContent=caption;shape.append(title);
      shape.addEventListener('click',()=>selectEvidence(e.evidence_id,true));shape.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectEvidence(e.evidence_id,true);}});
      $('shapes').append(shape);
    }
    for (const e of visible) {
      const n=evidenceNumber(e.evidence_id),[x,y]=e.bbox;
      const marker=svgNode('g',{class:'evidence-marker','data-evidence-id':e.evidence_id,'data-x':x*state.page.width,'data-y':y*state.page.height}); marker.append(svgNode('rect',{})); const number=svgNode('text',{});number.textContent=n;marker.append(number);marker.setAttribute('role','button');marker.setAttribute('aria-label',`Focus source ${n}`);marker.setAttribute('tabindex','0');marker.addEventListener('click',()=>selectEvidence(e.evidence_id,true));marker.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectEvidence(e.evidence_id,true);}});$('shapes').append(marker);
      const li=node('li'),button=node('button',undefined,'evidence-row');button.type='button';button.dataset.evidenceId=e.evidence_id;button.setAttribute('aria-pressed','false');button.title=e.evidence_id;
      const copy=node('span',undefined,'evidence-copy');copy.append(node('strong',e.original_text || roles[e.role] || 'Source region'),node('small',`${roles[e.role] || (e.method==='native'?'Native source':'Model proposal')} · Page ${e.page_index+1}`));
      button.append(node('span',String(n),'evidence-number'),copy,node('span','↗','evidence-arrow'));button.addEventListener('click',()=>selectEvidence(e.evidence_id));li.append(button);$('evidenceList').append(li);
    }
    updateMarkers();
  }
  $('question').addEventListener('input',controls);
  $('questionForm').addEventListener('submit',async event=>{
    event.preventDefault(); if(state.busy || !state.doc || !$('question').value.trim())return;
    clearAnswer();state.requestPage=state.page.page_index;state.busy=true;controls();notice(`Waiting for an answer from Page ${state.requestPage+1}. No automatic retries.`, 'waiting');
    try {
      const answer=await request('/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({document_ids:[state.doc.document_id],question:$('question').value.trim(),page_index:state.requestPage,runtime_model:'gpt-6.1-sol',use_cache:true})});
      presentAnswer(answer);
    } catch(error) {notice('Operational error: '+error.message+' The request did not complete; this is not a drawing-evidence result.','error');}
    finally {state.busy=false;controls();}
  });
  function addFact(parent,label,value) {parent.append(node('dt',label),node('dd',value===undefined||value===null?'Unknown':String(value)));}
  function evidenceLinks(parent,ids,label) {
    for (const id of ids || []) { const e=state.answer.evidence?.find(e=>e.evidence_id===id); if(!e)continue; const b=node('button',`${label || 'Source'} ${evidenceNumber(id)}${e.role==='scale_bar'?' · Scale':''}`,'evidence-link');b.type='button';b.title=id;b.addEventListener('click',()=>selectEvidence(id,true));parent.append(b); }
  }
  function operationalFailure(answer) {
    if (answer.status !== 'error') return null;
    const meta=answer.metadata || {}, code=[meta.error,meta.reason_code,...(answer.missing_inputs || [])].filter(Boolean).join(' ');
    if (/runtime_access_blocked/.test(code)) return nativePreview
      ? 'Model access is disabled in this local preview. Native printed-area and geometry queries remain available. Open permanent Corvid for model queries.'
      : 'Model access is unavailable in this deployment. This is an operational authorization problem, not missing drawing information.';
    if (/budget_exhausted|budget/.test(code)) return 'The API budget restriction blocked this request. No drawing conclusion was produced.';
    if (/provider|preflight|auth|credential|runtime/.test(code)) return 'The model provider request could not complete. Check runtime access or provider status; this is not a drawing-evidence result.';
    return 'The request could not complete because of a server or runtime problem. This is not a drawing-evidence result.';
  }
  function renderInlineCalculation(calc, answer) {
    const body=$('calculationInline');body.replaceChildren();body.hidden=!calc?.terms?.length;
    if (!calc?.terms?.length) return;
    body.append(node('p',calc.scope_complete===true?'Source calculation':'Incomplete source calculation','calculation-caption'));
    const equation=node('div',undefined,'calculation-equation');
    calc.terms.forEach((term,index)=>{
      if(index) equation.append(node('span','+','calculation-operator'));
      const button=node('button',undefined,'calculation-operand');button.type='button';
      const name=[term.room_id ? 'Room '+term.room_id : '',term.source_name].filter(Boolean).join(' · ') || 'Source term';
      button.append(node('span',name),node('strong',`${term.value_m2 == null ? 'Unknown' : displayValue(term.value_m2)} m²`));
      const refs=term.evidence_ids || [], evidence=state.answer.evidence || [];
      const focus=refs.find(id=>evidence.find(e=>e.evidence_id===id && e.role==='room_boundary')) || refs.find(id=>evidence.some(e=>e.evidence_id===id));
      button.disabled=!focus;if(focus)button.addEventListener('click',()=>selectEvidence(focus,true));
      const method=term.source_method || term.method;
      button.title=[name,method==='printed_area'?'Printed source value':method==='calibrated_geometry'?'Calibrated PDF geometry':method,term.source_measurement ? describe(term.source_measurement):''].filter(Boolean).join(' · ');
      equation.append(button);
    });
    equation.append(node('span','=','calculation-operator'),node('strong',`${answer.value == null ? 'Unknown' : displayValue(answer.value)} ${units[answer.unit] || ''}`,'calculation-total'));
    body.append(equation);
    if(calc.scope_complete!==true)body.append(node('p','Candidate subtotal only - requested scope is incomplete.','calculation-caption'));
  }
  function provenanceLabel(answer) {
    const meta=answer.metadata || {}, calc=meta.calculation || {};
    let basis=calc.source_basis;
    if (!basis && calc.terms?.length && calc.terms.every(t=>t.source_method)) {
      const methods=new Set(calc.terms.map(t=>t.source_method));basis=methods.size===1?[...methods][0]:'mixed';
    }
    if (!basis && ['native_printed_area','native_printed_sum'].includes(meta.route)) basis='printed_area';
    if (!basis && meta.route==='calibrated_geometry') basis='calibrated_geometry';
    if (basis==='printed_area') return calc.operation==='single_room' || answer.basis==='printed_area' ? 'Printed source evidence' : 'Calculated from printed areas';
    if (basis==='calibrated_geometry') return 'Calculated from PDF geometry';
    if (basis==='mixed') return 'Calculated from printed areas and PDF geometry';
    return names[answer.verification] || names.none;
  }
  function presentAnswer(answer, saved = false) {
    if (!answer.run_id || !statuses[answer.status]) throw new Error('Invalid answer response.');
    state.answer=answer;state.selected=null;const meta=answer.metadata || {},calc=meta.calculation, operational=operationalFailure(answer);
    $('result').hidden=false;$('status').textContent=statuses[answer.status];$('status').dataset.state=answer.status;$('answerCard').dataset.state=answer.status;
    $('verification').textContent=operational ? 'Operational failure - no drawing conclusion' : provenanceLabel(answer);
    const review=answer.status==='needs_review';$('candidate').hidden=!review;
    const success=answer.status==='answered'||review;
    $('answerValue').textContent=success && answer.value!==null && answer.value!==undefined ? `${displayValue(answer.value)}${units[answer.unit] ? ' '+units[answer.unit]:''}` : (answer.status==='unsupported'?'Unable to answer':answer.status==='error'?'Request failed':'No value returned');
    $('answerValue').classList.toggle('text-value',!finite(answer.value) || !success);
    const pages=meta.selected_pages || (state.requestPage!==null?[state.requestPage]:[]);
    $('answerScope').textContent=(pages.length?'Answer scope: '+pages.map(p=>'Page '+(p+1)).join(', '):'Answer page scope: unknown')+(calc?.scope_complete===false?' · Partial subtotal - scope incomplete':'');
    const bases={printed_area:'Basis: printed area label',native_text:'Basis: native source text',calculated:'Basis: source evidence calculation',model_visual:'Basis: model visual interpretation',unknown:'Basis: unknown'};
    $('basis').textContent=bases[answer.basis] || bases.unknown;
    $('explanation').textContent=operational || answer.counting_rule || meta.explanation || '';
    renderInlineCalculation(calc,answer);
    $('qualifications').replaceChildren();
    if (calc?.scope) $('qualifications').append(node('p','Calculation scope: '+describe(calc.scope)));
    if (calc && calc.scope_complete!==true) $('qualifications').append(node('p','Scope is not confirmed complete. This result must not be treated as a complete floor total.'));
    for (const id of calc?.missing_room_ids || []) $('qualifications').append(node('p',`Room ${id} was not found or could not be uniquely identified.`));
    for (const [reference, ids] of Object.entries(calc?.resolution_candidates || {})) {
      if (Array.isArray(ids) && ids.length) $('qualifications').append(node('p',`Ambiguous room reference “${reference}”. Candidate room IDs: ${ids.join(', ')}. Ask again with explicit IDs.`));
    }
    if (!operational && (answer.missing_inputs || []).length && !calc?.missing_room_ids?.length) $('qualifications').append(node('p','The requested operation or source evidence is unsupported or incomplete. See audit details.'));
    for (const item of answer.assumptions || []) $('qualifications').append(node('p','Assumption: '+describe(item)));
    if (answer.raw_model_count!==null && answer.raw_model_count!==undefined) $('qualifications').append(node('p','Raw model count: '+answer.raw_model_count));
    if (answer.evidence_tally!==null && answer.evidence_tally!==undefined) $('qualifications').append(node('p','Evidence tally: '+answer.evidence_tally));
    $('elapsed').textContent=finite(meta.elapsed_ms)?`${Math.round(meta.elapsed_ms)} ms · ${saved ? 'Saved query' : 'Current request'}`:'Elapsed time: Unknown';
    $('cost').textContent=meta.cache_hit ? `Reused answer · ${dollars(meta.incremental_cost_usd ?? 0)}` : `${saved ? 'Saved query cost' : 'Request cost'}: ${dollars(meta.cost_usd)}`;
    renderEvidence();renderCalculation(calc);renderAudit(answer, saved);
    if(operational && nativePreview){const link=node('a','Open permanent Corvid ↗');link.href=permanentUrl;$('qualifications').append(link);}
    notice(operational || (review?'Review the candidate and its source evidence before use.':answer.status==='answered'?'Answer received. Inspect the source evidence.': 'The server could not provide a supported answer.'),answer.status==='error'?'error':'');
  }
  function renderCalculation(calc) {
    $('calculation').hidden=!calc;$('calculationBody').replaceChildren();if(!calc)return;
    const body=$('calculationBody');body.append(node('p',`Operation: ${calc.operation || 'Unknown'} · Scope ${calc.scope_complete===true?'complete':calc.scope_complete===false?'incomplete':'unknown'}`));
    for (const term of calc.terms || []) { const div=node('div',undefined,'term'),title=node('div',undefined,'term-title');title.append(node('strong',('Room '+term.room_id)+(term.source_name?' · '+term.source_name:'')),node('span',`${term.value_m2 === null || term.value_m2 === undefined ? 'Unknown' : displayValue(term.value_m2)} m²`));div.append(title,node('p',Number.isInteger(term.page_index)?'Page '+(term.page_index+1):'Page unknown'));if(term.source_measurement)div.append(node('p','Source measurement: '+describe(term.source_measurement)+(term.source_unit?' '+term.source_unit:'')));if(term.source_method || term.method)div.append(node('p','Method: '+(term.source_method || term.method)));const boundary=(term.evidence_ids || []).find(id=>state.answer.evidence?.find(e=>e.evidence_id===id && e.role==='room_boundary'));if(boundary){const fit=node('button','Fit room '+term.room_id,'evidence-link');fit.type='button';fit.addEventListener('click',()=>selectEvidence(boundary,true));div.append(fit);}evidenceLinks(div,term.evidence_ids,'Focus source');body.append(div); }
    if(calc.included_room_ids?.length)body.append(node('p','Included rooms: '+calc.included_room_ids.join(', ')));
    for (const e of calc.excluded_rooms || []) { const div=node('div');div.append(node('p','Excluded room '+(e.room_id ?? '')+': '+(e.reason || 'Reason unspecified')));evidenceLinks(div,e.evidence_ids);body.append(div); }
    if(calc.missing_room_ids?.length)body.append(node('p','Missing rooms: '+calc.missing_room_ids.join(', ')));
    if(calc.calibration && (calc.calibration.points_per_metre != null || calc.calibration.scale_evidence_ids?.length)){const c=calc.calibration;body.append(node('p','Scale calibration: '+(c.validated===true?'validated':c.validated===false?'not validated':'unknown')));const dl=node('dl');addFact(dl,'Points / metre',c.points_per_metre);addFact(dl,'Interval disagreement',c.interval_relative_disagreement);body.append(dl);evidenceLinks(body,c.scale_evidence_ids,'Inspect scale');}
  }
  function renderAudit(answer, saved) {
    const m=answer.metadata || {},dl=node('dl');$('audit').replaceChildren(dl);
    addFact(dl,'Run ID',answer.run_id);addFact(dl,'Server value',answer.value);addFact(dl,'Original run',m.original_run_id);addFact(dl,'Document SHA256',state.doc.sha256);addFact(dl,'Model attempts',m.attempts);addFact(dl,'Original run cost',dollars(m.cost_usd));addFact(dl,'Cache reused',m.cache_hit===true?'Yes':'No');addFact(dl,'Requested model',m.model_requested || (saved ? 'Unknown' : 'gpt-6.1-sol'));addFact(dl,'Served model',m.model);addFact(dl,'Route',m.route);
    if(m.budget){addFact(dl,'Budget known',dollars(m.budget.known_usd));addFact(dl,'Budget reserved',dollars(m.budget.unknown_reserved_usd));addFact(dl,'Budget cap',dollars(m.budget.cap_usd));}
    addFact(dl,'Reason codes',JSON.stringify(answer.missing_inputs || []));
    for(const e of answer.evidence || []){const p=node('p',`Source ${evidenceNumber(e.evidence_id)} · ${e.evidence_id} · Page ${e.page_index+1} · ${e.method}`);$('audit').append(p);}
  }
  $('runForm').addEventListener('submit',async event=>{
    event.preventDefault();if(state.busy||!state.doc)return;const id=$('runId').value.trim();if(!id)return;
    state.busy=true;controls();notice('Opening saved run...', 'waiting');
    try {const answer=await request('/runs/'+encodeURIComponent(id));const docId=answer.metadata?.document_id || answer.evidence?.[0]?.document_id;if(docId!==state.doc.document_id)throw new Error('Upload the same source document before opening this run.');clearAnswer();state.requestPage=null;presentAnswer(answer, true);notice('Saved run opened. Timing and cost describe that saved request.');}
    catch(error){notice('Could not open run: '+error.message,'error');}finally{state.busy=false;controls();}
  });
  controls();
})();
