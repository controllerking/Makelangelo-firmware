'use strict';
const $ = id => document.getElementById(id);
let snapshot = {connected:false,device:{},jobs:[]}, selected = null, artwork = null, source = null;
let toastTimer, statusBusy = false, preparing = false, revision = 0;
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
  $('machine-state').textContent=!connected?'Offline':d.fault?'Reset required':d.homing?'Homing':d.paused?'Paused':d.reference==='manual'?'Manual reference':d.homed?'Homed':'Needs homing';
  $('prepare').disabled=preparing; $('demo').disabled=preparing;
  $('prepare').textContent=preparing?'Converting…':'Convert & preview';
  $('position').textContent=connected && Number.isFinite(d.x)?d.x.toFixed(1)+', '+d.y.toFixed(1)+' mm'+(d.position_kind==='planned'?' · target':''):'—';
  $('pen-state').textContent=connected?(d.pen===d.pen_up?'Up':d.pen+'°'):'—';
  if (document.activeElement!==$('host')) $('host').value=snapshot.host || 'drawy.local';
  if ($('paper').options.length===1 && snapshot.papers) {
    $('paper').replaceChildren(...Object.keys(snapshot.papers).map(name=>{
      const option=document.createElement('option');option.value=name;option.textContent=name+(name.startsWith('A')?'':' in');return option;
    })); $('paper').value='18 × 24';
  }
  for (const id of ['home','pen-up','pen-down']) $(id).disabled=!connected || !!active || !!d.fault || !!d.paused;
  $('pen-down').disabled ||= !d.homed;
  $('connect').disabled=connected; $('disconnect').disabled=!connected;
  $('start').disabled=!connected || !d.homed || !!d.fault || !!active || !selected || !$('reviewed').checked || !!d.paused;
  $('pause').disabled=!connected || !active || active.state!=='running';
  $('resume').disabled=!connected || (active ? active.state!=='paused' : !!d.busy) || !d.paused || !!d.moving || !!d.fault || !d.homed;
  $('resume').textContent=active?'Resume':'Resume robot';
  $('stop').disabled=!connected || !!d.fault;
  $('job-message').textContent=active?active.message:d.fault?'Reset the robot, then rehome.':selected?'Your drawing is ready for review.':'Ready when you are.';
  const progress=active?100*active.completed/active.command_count:0;
  $('progress').value=progress;
  $('progress-label').textContent=active?Math.floor(progress)+'% complete · '+active.completed+' / '+active.command_count+' commands':'No active drawing';
  const queue=$('queue'); queue.replaceChildren();
  if (!snapshot.jobs.length) {const p=document.createElement('p');p.className='help';p.textContent='Your prepared drawings will appear here.';queue.append(p);}
  for (const job of snapshot.jobs) {
    const button=document.createElement('button');button.className='queue-item'+(job.id===selected?' selected':'');
    const title=document.createElement('strong');title.textContent=job.title;
    const meta=document.createElement('small');meta.textContent=job.paper+' · '+job.command_count.toLocaleString()+' commands · ~'+duration(job.estimated_seconds);
    const state=document.createElement('span');state.className='state';state.textContent=job.state;
    button.append(title,meta,state);button.onclick=()=>act(async()=>{artwork=await api('jobs/'+job.id);selected=job.id;$('reviewed').checked=false;showArtwork();render();});
    queue.append(button);
  }
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
    artwork=result; selected=artwork.id; $('reviewed').checked=false;showArtwork();
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
  canvas.width=Math.round(box.width*dpr);canvas.height=Math.round(box.height*dpr);
  const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);
  const rect=artwork?.paper_rect||[0,0,457.2,609.6];
  const [left,top,w,h]=rect;
  const scale=Math.min((box.width-64)/w,(box.height-48)/h);
  const ox=(box.width-w*scale)/2,oy=(box.height-h*scale)/2;
  ctx.shadowColor='#30402b22';ctx.shadowBlur=18;ctx.shadowOffsetY=5;
  ctx.fillStyle='#fffefa';ctx.fillRect(ox,oy,w*scale,h*scale);ctx.shadowColor='transparent';
  if (!artwork) return;
  const margin=artwork.margin;
  ctx.strokeStyle='#cbd3c2';ctx.setLineDash([3,5]);ctx.lineWidth=.7;
  ctx.strokeRect(ox+margin*scale,oy+margin*scale,(w-2*margin)*scale,(h-2*margin)*scale);
  ctx.setLineDash([]);ctx.strokeStyle='#314a3c';ctx.lineWidth=.7;ctx.lineCap='round';ctx.lineJoin='round';
  for (const path of artwork.paths) {
    ctx.beginPath();
    path.forEach(([x,y],i)=>{const px=ox+(x-left)*scale,py=oy+(top-y)*scale;i?ctx.lineTo(px,py):ctx.moveTo(px,py);});
    ctx.stroke();
  }
}
$('connection-form').onsubmit=e=>{e.preventDefault();act(async()=>{
  await api('connect',{host:$('host').value,token:$('token').value});$('token').value='';toast('Robot connected.');
});};
$('disconnect').onclick=()=>act(()=>api('disconnect',{}));
$('home').onclick=()=>act(async()=>{toast('Homing. Keep the carriage path clear.');await api('manual',{op:'home'});});
$('pen-up').onclick=()=>act(()=>api('manual',{op:'pen_up'}));
$('pen-down').onclick=()=>act(()=>api('manual',{op:'pen_down'}));
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
$('start').onclick=()=>act(()=>api('start',{id:selected,reviewed:$('reviewed').checked}));
$('pause').onclick=()=>act(()=>api('pause',{}));
$('resume').onclick=()=>act(()=>api('resume',{}));
$('stop').onclick=()=>act(async()=>{await api('stop',{});toast('Stopped. Reset the robot and rehome before drawing again.');});
new ResizeObserver(draw).observe($('preview'));
refresh();setInterval(refresh,700);draw();
