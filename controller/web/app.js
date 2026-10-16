'use strict';
const $ = id => document.getElementById(id);
let snapshot = {connected:false,device:{},jobs:[]}, selected = null, artwork = null, source = null;
let toastTimer, statusBusy = false, preparing = false, revision = 0;
let calibrationBusy=false, appliedCalibration=null, appliedPen=null, displayedPenAngle=null;
let speedBusy=false,speedDirty=false,speedBoot=null;
let waveChecked=false;
const cornerNames=['top_left','top_right','bottom_right','bottom_left'];
let currentPage=null,initialPageChosen=false;
let monitoredJobId=null,startBusy=false;
// Move the existing form intact: no duplicate controls or draft reset.
$('calibration-content').append($('calibration-card'));
$('monitor-controls').append($('robot-card'),$('speeds-card'));
function calibrationComplete(){
  const d=snapshot.device;
  return !!(snapshot.connected && snapshot.calibration && d.homed && d.calibration_id===snapshot.calibration.id && d.pen_calibrated && !snapshot.calibration_draft && !snapshot.pen_draft && !d.fault);
}
function renderRoute(){
  const hash=window.location?.hash;
  const page=hash==='#calibration'?'calibration':hash==='#monitor'?'monitor':['#prepare','#workspace'].includes(hash)?'prepare':currentPage||'prepare';
  const changed=page!==currentPage;currentPage=page;
  $('calibration-page').hidden=page!=='calibration';$('workspace-page').hidden=page!=='prepare';$('monitor-page').hidden=page!=='monitor';
  for(const name of ['prepare','monitor','calibration'])$('nav-'+name).setAttribute?.('aria-current',name===page?'page':'false');
  document.title=page==='calibration'?'Calibration · Drawy':page==='monitor'?'Print & monitor · Drawy':'Prepare · Drawy';
  if(changed && page==='prepare')draw();
}
function navigate(page){
  if(page==='workspace')page='prepare'; // Preserve existing calibration handoff and old bookmarks.
  currentPage=page;
  if(window.location)window.location.hash='#'+page;
  renderRoute();window.scrollTo?.({top:0,behavior:'instant'});
  if(page==='calibration')$('calibration-heading').focus?.({preventScroll:true});
  else if(page==='monitor')$('monitor-heading').focus?.({preventScroll:true});
  else {draw();$('workspace-heading').focus?.({preventScroll:true});}
}
function renderSetupNavigation(){
  const ready=calibrationComplete(),d=snapshot.device;
  if(!initialPageChosen && snapshot.connected){
    initialPageChosen=true;
    if(!window.location?.hash)navigate(snapshot.active?'monitor':ready?'prepare':'calibration');
  }
  const message=!snapshot.connected?'Robot offline':snapshot.active?'Drawing in progress':d.fault?'Reset required':snapshot.pen_draft?'Pen calibration in progress':snapshot.calibration_draft?'Paper calibration in progress':!d.pen_calibrated?'Set your pen-in and pen-out positions':!snapshot.calibration?'Capture the four paper corners':!d.homed || d.calibration_id!==snapshot.calibration.id?'Restore the saved top-left position':'Ready to draw';
  $('workspace-readiness').textContent=$('calibration-readiness').textContent=message;
  $('workspace-calibration-notice').hidden=ready;
  $('workspace-setup-help').textContent=snapshot.active?'The active job is in Print & monitor. You can prepare another image without changing it.':'Prepare artwork here, then finish calibration or restore position before starting the robot.';
  $('calibration-next-help').textContent=ready?'Saved calibration is ready. Continue to Prepare to convert and review your artwork.':message+'. No automatic movement will be performed.';
  $('calibration-continue').disabled=!ready;
  $('calibration-stop').disabled=!snapshot.connected || !!d.fault;
  renderRoute();
}
window.addEventListener?.('hashchange',renderRoute);
async function api(path, body) {
  const response = await fetch('/api/'+path, body === undefined ? {} : {
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}
function toast(message) {
  $('toast').textContent=message; $('toast').hidden=false;
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,7000);
}
async function act(fn) {
  try { await fn(); await refresh(); } catch(e) { toast(e.message); }
}
function duration(s) { return s<60 ? Math.round(s)+' sec' : Math.round(s/60)+' min'; }
async function refresh() {
  if (statusBusy) return;
  statusBusy=true;
  try { snapshot=await api('status'); render(); }
  catch(e) { toast('Controller unavailable. Reopen the private terminal URL.'); }
  finally { statusBusy=false; }
}
function render() {
  const d=snapshot.device, connected=snapshot.connected, active=snapshot.jobs.find(j=>j.id===snapshot.active);
  $('connection-badge').textContent=snapshot.simulation?'Simulation · no hardware':connected?'Robot connected':'Not connected';
  $('connection-badge').classList.toggle('online',connected);
  $('machine-state').textContent=!connected?'Offline':d.fault?'Reset required':d.homing?'Homing':d.paused?'Paused':d.homed?'Homed':'Needs homing';
  $('prepare').disabled=preparing; $('demo').disabled=preparing;
  $('prepare').textContent=preparing?'Converting…':'Convert & preview';
  $('position').textContent=connected && Number.isFinite(d.x)?d.x.toFixed(1)+', '+d.y.toFixed(1)+' mm'+(d.position_kind==='planned'?' · target':''):'—';
  $('pen-state').textContent=connected?(d.pen===d.pen_up?'Up':d.pen+'°'):'—';
  $('connection-message').textContent=snapshot.connection_message || (connected?'Linked by server configuration':'Connecting automatically');
  if ($('paper').options.length===1 && snapshot.papers) {
    $('paper').replaceChildren(...Object.keys(snapshot.papers).map(name=>{
      const option=document.createElement('option');option.value=name;option.textContent=name+(name.startsWith('A')?'':' in');return option;
    })); $('paper').value='18 × 24';
  }
  renderCalibration();
  renderPenCalibration();
  renderSpeeds();
  renderSetupNavigation();
  for (const id of ['home','pen-up','pen-down']) $(id).disabled=!connected || !!active || !!d.fault || !!d.paused;
  $('pen-down').disabled ||= !d.homed;
  for(const id of ['home','pen-up','pen-down'])$(id).disabled ||= !!snapshot.pen_draft;
  $('home').disabled ||= !d.switch_homing_enabled || !!snapshot.calibration || !!snapshot.calibration_draft;
  $('start').disabled=startBusy || preparing || !connected || !d.homed || !!d.fault || !!active || !selected || !$('reviewed').checked || !!d.paused || !!snapshot.calibration_draft || !!snapshot.pen_draft || !!d.pen_tuning;
  $('start').textContent=startBusy?'Uploading…':'Upload & start drawing';
  $('pause').disabled=!connected || !active || active.state!=='running';
  $('resume').disabled=!connected || (active ? active.state!=='paused' : !!d.busy) || !d.paused || !!d.moving || !!d.fault || !d.homed;
  $('resume').textContent=active?'Resume':'Resume robot';
  $('stop').disabled=!connected || !!d.fault;
  $('header-stop').disabled=$('stop').disabled;
  const monitored=active || snapshot.jobs.find(j=>j.id===monitoredJobId) || snapshot.jobs[0];
  if(monitored)monitoredJobId=monitored.id;
  $('monitor-job-title').textContent=monitored?.title||'No active drawing';
  $('monitor-job-state').textContent=monitored?.state?.toUpperCase()||'NO JOB SELECTED';
  $('monitor-job-details').textContent=monitored?monitored.paper+' · '+monitored.command_count.toLocaleString()+' commands · prepared estimate '+duration(monitored.estimated_seconds):'Prepare an image or select a job from the queue.';
  $('monitor-review').disabled=!monitored || !!active || startBusy;
  $('job-message').textContent=d.fault?'Reset the robot, then restore position.':monitored?.message||'No drawing running. Prepare artwork to get started.';
  const uploading=monitored?.state==='uploading',done=monitored?(uploading?monitored.accepted:monitored.completed)||0:0;
  const progress=monitored?100*done/monitored.command_count:0;
  $('progress').value=progress;
  const phase=uploading?'Uploading':monitored?.state==='completed'?'Completed':monitored?.state==='paused'?'Paused':monitored?.state==='queued'?'Not started':'Drawing';
  $('progress-label').textContent=monitored?phase+': '+Math.floor(progress)+'% · '+done+' / '+monitored.command_count+' commands':'No active drawing';
  const queue=$('queue'); queue.replaceChildren();
  if (!snapshot.jobs.length) {const p=document.createElement('p');p.className='help';p.textContent='Your prepared drawings will appear here.';queue.append(p);}
  for (const job of snapshot.jobs) {
    const button=document.createElement('button');button.className='queue-item'+(job.id===monitoredJobId?' selected':'');
    const title=document.createElement('strong');title.textContent=job.title;
    const meta=document.createElement('small');meta.textContent=job.paper+' · '+job.command_count.toLocaleString()+' commands · ~'+duration(job.estimated_seconds);
    const state=document.createElement('span');state.className='state';state.textContent=job.state;
    button.append(title,meta,state);button.onclick=()=>{monitoredJobId=job.id;navigate('monitor');render();};
    queue.append(button);
  }
}
function renderCalibration() {
  const d=snapshot.device, saved=snapshot.calibration, draft=snapshot.calibration_draft;
  const ready=snapshot.connected && d.calibration_api===1 && !d.fault && !snapshot.active;
  const valid=draft && draft.boot===d.boot && d.calibrating;
  const idle=ready && !calibrationBusy && !d.busy && !d.moving;
  if(!waveChecked && snapshot.papers){
    waveChecked=true;const wave=$('wave-option');
    if(snapshot.wave_available)$('image-mode').value='wave';
    else{wave.disabled=true;wave.textContent='Wavy line · unavailable (install python3-numpy on the controller)';$('image-mode').value='hatching';}
  }
  if($('cal-paper').options.length===1 && snapshot.papers){
    $('cal-paper').replaceChildren(...Object.keys(snapshot.papers).map(name=>{
      const o=document.createElement('option');o.value=name;o.textContent=name;return o;
    }));$('cal-paper').value=saved?.paper||'Letter';
  }
  if(saved && appliedCalibration!==saved.id){
    appliedCalibration=saved.id; revision++; selected=null;artwork=null;$('reviewed').checked=false;
    $('paper').value=saved.paper;$('left').value=saved.left.toFixed(3);$('top').value=saved.top.toFixed(3);
    $('cal-width').value=saved.width;$('cal-paper').value=saved.paper;showArtwork();
  }
  $('paper').disabled=!!saved;$('left').readOnly=$('top').readOnly=!!saved;
  const count=valid?Object.keys(draft.corners).length:0;
  $('calibration-status').textContent=!snapshot.connected?'Robot offline. Saved calibration is retained.':d.calibration_api!==1?'Update ESP32 firmware to enable manual calibration.':valid?
    count+'/4 corners captured. '+(count<4?'Next: '+cornerNames[count].replaceAll('_',' '):'All captured; validate and save.'):
    saved?(d.calibration_id===saved.id && d.homed?'Calibrated · normal drawing speeds enabled.':'Saved paper calibration · restore position at one saved corner before drawing.'):'No saved calibration. Start with the pen lifted.';
  $('cal-begin').disabled=!idle || !$('cal-confirmed').checked || !!snapshot.pen_draft || !!d.pen_tuning;
  $('cal-width').disabled=$('cal-paper').disabled=calibrationBusy;
  $('cal-jog-panel').hidden=!valid;
  $('cal-counts').textContent='Belt pulse offsets: '+(d.jog_steps||[0,0]).join(' / ');
  for(const id of ['cal-left-in','cal-left-out','cal-right-in','cal-right-out'])$(id).disabled=!idle || !valid;
  $('cal-capture').disabled=!idle || !valid || count>=4;
  $('cal-capture').textContent=count<4?'Capture '+cornerNames[count].replaceAll('_',' '):'All corners captured';
  $('cal-finish').disabled=!idle || !valid || count!==4;
  $('cal-restore-panel').hidden=!saved;
  $('cal-restore').disabled=!idle || !$('cal-at-reference').checked;
  $('cal-restore').textContent='Restore position at '+$('cal-restore-corner').value.replaceAll('_',' ');
}
async function calibrate(body){
  if(calibrationBusy)return;
  calibrationBusy=true;render();
  try { snapshot=await api('calibration',body);$('cal-at-reference').checked=false;render();if(['finish','restore'].includes(body.action) && calibrationComplete())navigate('workspace'); }
  catch(e){toast(e.message);}
  finally{calibrationBusy=false;await refresh();}
}
function renderSpeeds(){
  const d=snapshot.device,ready=snapshot.connected && d.speed_control_api===1 && !d.fault;
  if(ready && (speedBoot!==d.boot || (!speedDirty && !speedBusy))){
    $('stepper-speed').value=d.stepper_percent;$('servo-speed').value=d.servo_speed;
    speedBoot=d.boot;
  }
  $('stepper-speed-value').textContent=$('stepper-speed').value+'%';
  $('servo-speed-value').textContent=$('servo-speed').value+'°/s';
  for(const id of ['stepper-speed','servo-speed','speeds-apply'])$(id).disabled=!ready || speedBusy;
  $('speeds-status').textContent=!ready?'Updated firmware and an online, fault-free robot are required.':
    'Applied: steppers '+Number(d.stepper_percent_actual??d.stepper_percent).toFixed(0)+'% → '+d.stepper_percent+'% · pen '+d.servo_speed+'°/s'+(speedDirty?' · unapplied changes':'');
}
function renderPenCalibration(){
  const d=snapshot.device,draft=snapshot.pen_draft;
  if(snapshot.connected && Number.isFinite(d.pen_up) && Number.isFinite(d.pen_down)){
    const key=d.pen_up+':'+d.pen_down;
    if(appliedPen!==null && appliedPen!==key){revision++;selected=null;artwork=null;$('reviewed').checked=false;showArtwork();}
    appliedPen=key;
  }
  const valid=draft && draft.boot===d.boot;
  const idle=snapshot.connected && d.pen_calibration_api===1 && !d.fault && !snapshot.active && !d.busy && !d.moving && !calibrationBusy && !snapshot.calibration_draft && !d.calibrating;
  $('pen-cal-status').textContent=d.pen_calibration_api!==1?'Firmware update required for pen calibration.':
    valid?'Adjust gently and capture both positions.':
    (d.pen_calibrated?'Saved':'Default')+' · pen in '+d.pen_up+'° · pen out '+d.pen_down+'°';
  $('pen-cal-begin').disabled=!idle || !$('pen-cal-confirmed').checked || !!valid;
  $('pen-cal-panel').hidden=!valid;
  $('pen-cal-angle').textContent=valid?'Servo '+draft.angle+'° · in '+(draft.up??'not set')+' · out '+(draft.down??'not set'):'';
  if(valid && displayedPenAngle!==draft.angle){$('pen-angle-target').value=draft.angle;displayedPenAngle=draft.angle;}
  if(!valid)displayedPenAngle=null;
  for(const id of ['pen-minus-thirty','pen-minus-ten','pen-plus-ten','pen-plus-thirty','pen-minus-five','pen-minus-one','pen-plus-one','pen-plus-five','pen-angle-target','pen-angle-go','pen-capture-in','pen-capture-out','pen-cal-cancel'])$(id).disabled=!idle || !valid;
  $('pen-test-in').disabled=!idle || !valid || draft.up===null;
  $('pen-test-out').disabled=!idle || !valid || draft.down===null;
  $('pen-cal-save').disabled=!idle || !valid || draft.up===null || draft.down===null || draft.up===draft.down;
}
async function calibratePen(body){
  if(calibrationBusy)return;
  calibrationBusy=true;render();
  try{snapshot=await api('pen-calibration',body);render();if(body.action==='save' && calibrationComplete())navigate('workspace');}
  catch(e){toast(e.message);}
  finally{calibrationBusy=false;await refresh();}
}
function options() {
  return {paper:$('paper').value,left:$('left').value,top:$('top').value,margin:$('margin').value,feed:$('feed').value,
    quality:$('quality').value,image_mode:$('image-mode').value,threshold:$('threshold').value};
}
function invalidate() {
  revision++; selected=null; artwork=null; $('reviewed').checked=false; showArtwork(); render();
}
async function imagePayload(file, quality) {
  let bitmap;
  try { bitmap=await createImageBitmap(file); }
  catch(e) { throw new Error('Could not decode this image. Use a valid PNG, JPG or WebP file.'); }
  try {
    if(bitmap.width*bitmap.height>40000000)throw new Error('Image limit is 40 megapixels. Resize it first.');
    const max=snapshot.presets?.[quality]?.resolution || 512;
    const scale=Math.min(1,max/Math.max(bitmap.width,bitmap.height));
    const canvas=document.createElement('canvas');
    canvas.width=Math.max(2,Math.round(bitmap.width*scale));canvas.height=Math.max(2,Math.round(bitmap.height*scale));
    const ctx=canvas.getContext('2d',{willReadFrequently:true});
    ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);
    const rgba=ctx.getImageData(0,0,canvas.width,canvas.height).data;
    const gray=new Uint8Array(canvas.width*canvas.height);
    for(let i=0;i<gray.length;i++)gray[i]=Math.round(.2126*rgba[i*4]+.7152*rgba[i*4+1]+.0722*rgba[i*4+2]);
    let binary='';
    for(let i=0;i<gray.length;i+=32768)binary+=String.fromCharCode(...gray.subarray(i,i+32768));
    return {width:canvas.width,height:canvas.height,pixels:btoa(binary)};
  } finally { bitmap.close(); }
}
async function prepare() {
  if (preparing) return;
  if (!$('art-form').reportValidity()) return;
  if (!source) throw new Error('Choose an image, SVG or harmonic study first.');
  const current=revision, settings=options(), input=source;
  preparing=true;render();
  try {
    const payload=input.file?{image:await imagePayload(input.file,settings.quality),name:input.file.name}:input;
    const result=await api('import',{...payload,options:settings});
    if(current!==revision){toast('Settings changed during conversion. Convert again for an updated preview.');return;}
    artwork=result; selected=artwork.id;
    if(!snapshot.jobs.some(j=>j.id===result.id))snapshot.jobs.unshift(result);
    $('reviewed').checked=false;showArtwork();
  } finally { preparing=false;render(); }
}
function showArtwork() {
  $('empty-preview').hidden=!!artwork;
  $('drawing-title').textContent=artwork?artwork.title:'Your next drawing';
  $('paper-label').textContent=artwork?artwork.paper+(artwork.paper.startsWith('A')?'':' in'):'18 × 24 in';
  $('drawing-details').textContent=artwork?artwork.command_count.toLocaleString()+' commands · '+artwork.drawn_mm.toLocaleString()+' mm of line'+(artwork.quality?' · '+artwork.quality:''):'Paper coordinates are measured in millimetres.';
  $('estimate').textContent=artwork?'About '+duration(artwork.estimated_seconds):'';
  $('warning-list').hidden=!artwork?.warnings?.length;
  $('warning-list').textContent=artwork?.warnings?.join(' ')||'';
  draw();
}
function draw() {
  const canvas=$('preview'), box=canvas.getBoundingClientRect(), dpr=window.devicePixelRatio||1;
  if(box.width<=0 || box.height<=0)return;
  canvas.width=Math.round(box.width*dpr);canvas.height=Math.round(box.height*dpr);
  const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);
  const rect=artwork?.paper_rect||[0,0,457.2,609.6];
  const [left,top,w,h]=rect;
  const scale=Math.min((box.width-64)/w,(box.height-48)/h);
  const ox=(box.width-w*scale)/2,oy=(box.height-h*scale)/2;
  ctx.shadowColor='#30402b22';ctx.shadowBlur=18;ctx.shadowOffsetY=5;
  const corners=artwork?.paper_corners;
  const outline=points=>{
    ctx.beginPath();points.forEach(([x,y],i)=>{const px=ox+(x-left)*scale,py=oy+(top-y)*scale;i?ctx.lineTo(px,py):ctx.moveTo(px,py);});ctx.closePath();
  };
  ctx.fillStyle='#fffefa';
  if(corners){outline(corners);ctx.fill();}else ctx.fillRect(ox,oy,w*scale,h*scale);
  ctx.shadowColor='transparent';
  if (!artwork) return;
  const margin=artwork.margin;
  ctx.strokeStyle='#cbd3c2';ctx.setLineDash([3,5]);ctx.lineWidth=.7;
  if(corners){
    const [pw,ph]=artwork.paper_size;
    const inset=[[margin/pw,margin/ph],[1-margin/pw,margin/ph],[1-margin/pw,1-margin/ph],[margin/pw,1-margin/ph]];
    outline(inset.map(([u,v])=>[0,1].map(axis=>(1-u)*(1-v)*corners[0][axis]+u*(1-v)*corners[1][axis]+u*v*corners[2][axis]+(1-u)*v*corners[3][axis])));ctx.stroke();
  }else ctx.strokeRect(ox+margin*scale,oy+margin*scale,(w-2*margin)*scale,(h-2*margin)*scale);
  ctx.setLineDash([]);ctx.strokeStyle='#314a3c';ctx.lineWidth=.7;ctx.lineCap='round';ctx.lineJoin='round';
  for (const path of artwork.paths) {
    ctx.beginPath();
    path.forEach(([x,y],i)=>{const px=ox+(x-left)*scale,py=oy+(top-y)*scale;i?ctx.lineTo(px,py):ctx.moveTo(px,py);});
    ctx.stroke();
  }
}
$('home').onclick=()=>act(async()=>{toast('Homing. Keep the carriage path clear.');await api('manual',{op:'home'});});
$('pen-up').onclick=()=>act(()=>api('manual',{op:'pen_up'}));
$('pen-down').onclick=()=>act(()=>api('manual',{op:'pen_down'}));
$('calibration-form').onsubmit=e=>{
  e.preventDefault(); if(!$('calibration-form').reportValidity())return;
  calibrate({action:'begin',paper:$('cal-paper').value,width:$('cal-width').value,confirmed:$('cal-confirmed').checked});
};
for(const [id,axis,sign] of [['cal-left-in',0,-1],['cal-left-out',0,1],['cal-right-in',1,-1],['cal-right-out',1,1]])
  $(id).onclick=()=>calibrate({action:'jog',axis,mm:sign*Number($('cal-distance').value)});
$('cal-capture').onclick=()=>calibrate({action:'capture',corner:cornerNames[Object.keys(snapshot.calibration_draft?.corners||{}).length]});
$('cal-finish').onclick=()=>calibrate({action:'finish'});
$('cal-restore').onclick=()=>calibrate({action:'restore',corner:$('cal-restore-corner').value,at_corner:$('cal-at-reference').checked});
$('cal-confirmed').onchange=$('cal-at-reference').onchange=$('cal-restore-corner').onchange=render;
$('pen-cal-confirmed').onchange=render;
$('pen-cal-begin').onclick=()=>calibratePen({action:'begin',confirmed:$('pen-cal-confirmed').checked});
for(const [id,delta] of [['pen-minus-thirty',-30],['pen-minus-ten',-10],['pen-minus-five',-5],['pen-minus-one',-1],['pen-plus-one',1],['pen-plus-five',5],['pen-plus-ten',10],['pen-plus-thirty',30]])
  $(id).onclick=()=>calibratePen({action:'adjust',delta});
$('pen-angle-go').onclick=()=>{if($('pen-angle-target').reportValidity())calibratePen({action:'set',angle:Number($('pen-angle-target').value)});};
for(const [id,action,role] of [['pen-capture-in','capture','up'],['pen-capture-out','capture','down'],['pen-test-in','test','up'],['pen-test-out','test','down']])
  $(id).onclick=()=>calibratePen({action,role});
$('pen-cal-save').onclick=()=>calibratePen({action:'save'});
$('pen-cal-cancel').onclick=()=>calibratePen({action:'cancel'});
for(const id of ['stepper-speed','servo-speed'])$(id).addEventListener('input',()=>{speedDirty=true;renderSpeeds();});
$('speeds-form').onsubmit=async e=>{
  e.preventDefault();if(speedBusy || !$('speeds-form').reportValidity())return;
  speedBusy=true;renderSpeeds();
  try{snapshot=await api('speeds',{stepper_percent:Number($('stepper-speed').value),servo_speed:Number($('servo-speed').value)});speedDirty=false;}
  catch(e){toast(e.message);}
  finally{speedBusy=false;await refresh();}
};
$('svg-file').onchange=()=>act(async()=>{
  const file=$('svg-file').files[0];if (!file)return;
  source=null;invalidate();$('image-settings').hidden=true;
  const svg=/\.svg$/i.test(file.name)||file.type==='image/svg+xml';
  if(svg){
    if(file.size>2000000)throw new Error('SVG limit is 2 MB.');
    source={svg:await file.text(),name:file.name};
  }else{
    if(!/\.(png|jpe?g|webp)$/i.test(file.name))throw new Error('Choose PNG, JPG, WebP or SVG.');
    if(file.size>20000000)throw new Error('Image limit is 20 MB. Resize it first.');
    source={file};$('image-settings').hidden=false;
  }
  $('file-name').textContent=file.name+' · ready to convert';
});
$('art-form').onsubmit=e=>{e.preventDefault();act(prepare);};
$('demo').onclick=()=>act(async()=>{source={demo:true};invalidate();$('image-settings').hidden=true;$('file-name').textContent='Harmonic study · generated on your computer';await prepare();});
for(const id of ['paper','left','top','margin','feed','image-mode','threshold'])$(id).addEventListener('input',()=>{
  $('threshold-field').hidden=$('image-mode').value!=='outlines';invalidate();
});
$('quality').onchange=()=>{
  const profile=snapshot.presets?.[$('quality').value];
  if(profile){$('feed').value=profile.feed;$('quality-help').textContent=profile.description;}
  invalidate();
};
$('reviewed').onchange=render;
$('start').onclick=async()=>{
  if(startBusy || $('start').disabled)return;
  const id=selected,reviewed=$('reviewed').checked;
  startBusy=true;monitoredJobId=id;navigate('monitor');render();
  try{await api('start',{id,reviewed});}
  catch(e){toast(e.message);}
  finally{startBusy=false;await refresh();}
};
$('monitor-review').onclick=()=>act(async()=>{
  const job=snapshot.jobs.find(j=>j.id===monitoredJobId);
  if(!job || snapshot.active)return;
  artwork=await api('jobs/'+job.id);selected=job.id;$('reviewed').checked=false;showArtwork();navigate('prepare');render();
});
$('pause').onclick=()=>act(()=>api('pause',{}));
$('resume').onclick=()=>act(()=>api('resume',{}));
$('stop').onclick=$('calibration-stop').onclick=$('header-stop').onclick=()=>act(async()=>{await api('stop',{});toast('Stopped. Reset the robot and rehome before drawing again.');});
$('calibration-continue').onclick=()=>{if(calibrationComplete())navigate('workspace');};
renderRoute();
new ResizeObserver(draw).observe($('preview'));
refresh();setInterval(refresh,700);draw();
