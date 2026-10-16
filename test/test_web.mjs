// Browser logic tests without a browser, network, robot, or third-party package.
// Run with node test/test_web.mjs where Node is installed.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

export async function runWebTests() {
  const code=await readFile(new URL('../controller/web/app.js',import.meta.url),'utf8');
  const html=await readFile(new URL('../controller/web/index.html',import.meta.url),'utf8');
  for(const removed of ['A little machinery. A lot of possibility.','Prepare a drawing here. Let the wall do the rest.',
    'id="connection-form"','id="host"','id="token"','id="connect"','id="disconnect"'])assert(!html.includes(removed));
  assert(!code.includes("api('connect'"));assert(!code.includes("api('disconnect'"));
  const elements=new Map(), calls=[], draws=[];
  let closed=0;
  const ctx=new Proxy({
    getImageData:()=>({data:Uint8ClampedArray.from([0,0,0,255,255,0,0,255,0,255,0,255,255,255,255,255])}),
    fillRect:()=>draws.push('background'),drawImage:()=>draws.push('image'),
  },{get:(target,key)=>key in target?target[key]:()=>{}});
  function element() {
    return {value:'',checked:false,disabled:false,hidden:false,files:[],options:[{},{}],
      classList:{toggle(){}},addEventListener(name,fn){this[name]=fn;},
      children:[],attributes:{},append(...nodes){this.children.push(...nodes);for(const node of nodes)node.parentElement=this;},replaceChildren(){},reportValidity:()=>true,
      setAttribute(name,value){this.attributes[name]=value;},focus(){},
      getBoundingClientRect:()=>({width:600,height:600}),getContext:()=>ctx};
  }
  for(const [,id] of html.matchAll(/id="([^"]+)"/g))elements.set(id,element());
  for(const [id,value] of Object.entries({paper:'Letter',left:'100',top:'-100',margin:'20',feed:'10',quality:'balanced','image-mode':'hatching',threshold:'128','pen-width':'.3','minimum-mark':'0','path-tolerance':'.02','travel-feed':'10','bridge-gap':'0','color-mode':'mono'}))elements.get(id).value=value;
  const state={connected:false,device:{},jobs:[],presets:{
    fast:{resolution:256,feed:15,description:'Fast'},balanced:{resolution:512,feed:10},detailed:{resolution:768,feed:6,description:'Detailed'},
  }};
  const sandbox=vm.createContext({
    document:{getElementById:id=>{assert(elements.has(id),'Unknown DOM id: '+id);return elements.get(id);},
      createElement:()=>element(),activeElement:null},
    window:{devicePixelRatio:1,location:{hash:''},addEventListener(name,fn){this[name]=fn;},scrollTo(){}},ResizeObserver:class{observe(){}},
    setTimeout:()=>0,clearTimeout(){},setInterval(){},
    btoa:value=>Buffer.from(value,'binary').toString('base64'),
    createImageBitmap:async file=>{
      if(file.bad)throw new Error('bad file');
      return {width:file.width||2,height:file.height||2,close(){closed++;}};
    },
    fetch:async (url,options)=>{
      if(url==='/api/status')return {ok:true,json:async()=>state};
      if(url.startsWith('/api/jobs/')){
        const job=state.jobs.find(j=>j.id===url.split('/').at(-1));
        return {ok:true,json:async()=>({...job,paths:[[[200,-200],[210,-210]]],paper_rect:[200,-170,215.9,279.4],margin:20,drawn_mm:100,warnings:[]})};
      }
      calls.push([url,JSON.parse(options.body)]);
      if(url==='/api/speeds'){
        Object.assign(state.device,JSON.parse(options.body));
        return {ok:true,json:async()=>state};
      }
      if(url==='/api/calibration'){
        state.calibration_draft=null;state.device.calibrating=false;state.device.homed=true;
        state.device.calibration_id=state.calibration.id;
        return {ok:true,json:async()=>state};
      }
      if(url==='/api/pen-calibration'){
        state.pen_draft=null;state.device.pen_calibrated=true;
        return {ok:true,json:async()=>state};
      }
      if(url==='/api/start'){
        const job=state.jobs.find(j=>j.id===JSON.parse(options.body).id);
        state.active=job.id;Object.assign(job,{state:'uploading',accepted:12,completed:0,message:'Uploading complete plot'});
        return {ok:true,json:async()=>job};
      }
      return {ok:true,json:async()=>({id:'prepared',title:'photo.png',paths:[[[100,-100],[101,-101]]],
        paper:'Letter',paper_rect:[100,-100,215.9,279.4],margin:20,command_count:6,drawn_mm:1,
        estimated_seconds:1,warnings:[],quality:'detailed'})};
    },
  });
  new vm.Script(code).runInContext(sandbox);
  await vm.runInContext('refresh()',sandbox);
  const payload=await vm.runInContext('imagePayload({}, "fast")',sandbox);
  assert.deepEqual([...Buffer.from(payload.pixels,'base64')],[0,54,182,255]);
  assert.equal(payload.width,2);assert.equal(payload.height,2);assert.equal(closed,1);
  assert.equal(draws.at(-2),'background');assert.equal(draws.at(-1),'image');
  await assert.rejects(vm.runInContext('imagePayload({bad:true},"fast")',sandbox),/Could not decode/);
  await assert.rejects(vm.runInContext('imagePayload({width:10000,height:10000},"fast")',sandbox),/40 megapixels/);
  assert.equal(closed,2);
  const rgbPayload=await vm.runInContext('imagePayload({}, "fast", true)',sandbox);
  assert.equal(rgbPayload.channels,3);
  assert.deepEqual([...Buffer.from(rgbPayload.pixels,'base64')],[0,0,0,255,0,0,0,255,0,255,255,255]);
  elements.get('quality').value='detailed';elements.get('quality').onchange();
  assert.equal(elements.get('feed').value,6);
  assert.equal(elements.get('reviewed').checked,false);
  elements.get('svg-file').files=[{name:'photo.png',size:100,type:'image/png'}];
  await elements.get('svg-file').onchange();
  assert.equal(elements.get('image-settings').hidden,false);
  await vm.runInContext('prepare()',sandbox);
  assert.equal(calls.length,1);
  assert.equal(calls[0][0],'/api/import');
  assert.equal(calls[0][1].options.quality,'detailed');
  assert.equal(calls[0][1].options.pen_width,'.3');
  assert.equal(calls[0][1].options.travel_feed,'10');
  assert.equal(calls[0][1].options.bridge_gap,'0');
  assert.equal(calls[0][1].options.optimize_travel,false);
  assert.equal(calls[0][1].name,'photo.png');
  assert.equal(calls[0][1].image.width,2);
  assert.equal(elements.get('prepare').disabled,false);
  assert.equal(vm.runInContext('selected',sandbox),'prepared');
  elements.get('reviewed').checked=true;
  elements.get('margin').input();
  assert.equal(vm.runInContext('selected',sandbox),null);
  assert.equal(elements.get('reviewed').checked,false);
  assert.equal(calls.length,1,'Settings changes must not send motion or imports');
  state.connected=true;
  state.device={boot:'live-speed-test',speed_control_api:1,stepper_percent:100,servo_speed:35,homed:true};
  state.active='drawing';
  state.jobs=[{id:'drawing',state:'running',title:'Active draw',paper:'Letter',command_count:100,completed:10,estimated_seconds:60}];
  await vm.runInContext('refresh()',sandbox);
  assert.equal(elements.get('speeds-apply').disabled,false,'Speed controls remain enabled during drawing');
  elements.get('stepper-speed').value='50';elements.get('stepper-speed').input();
  elements.get('servo-speed').value='20';elements.get('servo-speed').input();
  await elements.get('speeds-form').onsubmit({preventDefault(){}});
  assert.deepEqual(calls.at(-1),['/api/speeds',{stepper_percent:50,servo_speed:20}]);
  assert.equal(state.active,'drawing');
  assert.equal(elements.get('speeds-apply').disabled,false);
  assert.equal(elements.get('calibration-card').parentElement,elements.get('calibration-content'));
  assert.equal(elements.get('monitor-page').hidden,false,'An active job opens in Print & monitor');
  assert.equal(elements.get('workspace-page').hidden,true);
  assert.equal(elements.get('robot-card').parentElement,elements.get('monitor-controls'));
  assert.equal(elements.get('speeds-card').parentElement,elements.get('monitor-controls'));
  vm.runInContext("navigate('prepare')",sandbox);
  await vm.runInContext('prepare()',sandbox);
  assert.equal(vm.runInContext('selected',sandbox),'prepared');
  assert.equal(elements.get('monitor-job-title').textContent,'Active draw','Preparing another image must not replace the monitored job');
  vm.runInContext("navigate('monitor')",sandbox);
  assert.equal(elements.get('workspace-page').hidden,true);
  assert.equal(vm.runInContext('selected',sandbox),'prepared','Monitoring must preserve the preparation draft');
  const navigationCalls=calls.length;
  vm.runInContext("navigate('calibration')",sandbox);
  assert.equal(elements.get('workspace-page').hidden,true);
  assert.equal(elements.get('calibration-page').hidden,false);
  assert.equal(elements.get('nav-calibration').attributes['aria-current'],'page');
  sandbox.window.location.hash='#workspace';sandbox.window.hashchange();
  assert.equal(elements.get('workspace-page').hidden,false,'Browser back/hash navigation restores the workspace');
  assert.equal(calls.length,navigationCalls,'Navigation must not send robot commands');
  assert.equal(elements.get('stop').onclick,elements.get('calibration-stop').onclick,'Both pages have the same explicit Stop action');
  assert.equal(elements.get('stop').onclick,elements.get('header-stop').onclick,'Stop is available on Prepare too');
  state.active=null;state.jobs=[];
  state.calibration={id:'saved-paper',paper:'Letter',left:200,top:-170,width:644.525};
  Object.assign(state.device,{homed:false,calibration_api:1,pen_calibration_api:1,pen_calibrated:false,pen_up:90,pen_down:40});
  vm.runInContext("navigate('calibration')",sandbox);
  await vm.runInContext('refresh()',sandbox);
  assert.equal(elements.get('calibration-continue').disabled,true);
  await vm.runInContext("calibrate({action:'finish'})",sandbox);
  assert.equal(elements.get('calibration-page').hidden,false,'Paper save alone must not skip unfinished pen setup');
  state.pen_draft={boot:state.device.boot,angle:90,up:90,down:40};
  await vm.runInContext('refresh()',sandbox);
  await vm.runInContext("calibratePen({action:'save'})",sandbox);
  assert.equal(elements.get('workspace-page').hidden,false,'Completing pen and paper setup opens workspace');
  assert.equal(elements.get('calibration-page').hidden,true);
  assert.equal(elements.get('workspace-calibration-notice').hidden,true);
  state.device.homed=false;
  vm.runInContext("navigate('calibration')",sandbox);
  await vm.runInContext('refresh()',sandbox);
  await vm.runInContext("calibrate({action:'restore'})",sandbox);
  assert.equal(elements.get('workspace-page').hidden,false,'Restoring saved position also returns to workspace');
  state.jobs=[{id:'next-print',state:'queued',title:'Next print',paper:'Letter',command_count:100,completed:0,estimated_seconds:60}];
  vm.runInContext("navigate('monitor')",sandbox);await vm.runInContext('refresh()',sandbox);
  await elements.get('monitor-review').onclick();
  assert.equal(elements.get('workspace-page').hidden,false,'A queued job can be opened in Prepare for review');
  assert.equal(vm.runInContext('selected',sandbox),'next-print');
  elements.get('reviewed').checked=true;vm.runInContext('render()',sandbox);
  await elements.get('start').onclick();
  assert.equal(elements.get('monitor-page').hidden,false,'Start opens monitoring during upload');
  assert.equal(elements.get('workspace-page').hidden,true);
  assert.match(elements.get('progress-label').textContent,/Uploading: 12%/);
  assert.equal(elements.get('monitor-job-title').textContent,'Next print');
  assert.equal(calls.at(-1)[0],'/api/start');
  const strokeColors=[];
  ctx.stroke=()=>strokeColors.push(ctx.strokeStyle);
  vm.runInContext('artwork='+JSON.stringify({paper_rect:[0,0,200,200],margin:20,
    paths:[[[10,-10],[20,-20]],[[30,-30],[40,-40]]],
    color_stages:[{path_start:0,path_end:1,swatch:'#dc232d'},{path_start:1,path_end:2,swatch:'#1e8c41'}]})+';draw()',sandbox);
  assert.deepEqual(strokeColors.slice(-2),['#dc232d','#1e8c41'],'Preview paths retain their own pen colors');
  state.active='color-job';
  state.device={homed:true,pen:90,pen_up:90,moving:false,fault:false,plot_storage_total:1408*1024,plot_free:1000*1024};
  state.jobs=[{id:'color-job',plot_run:'color-run',state:'awaiting_pen',pending_stage:0,
    title:'Color artwork',paper:'Letter',command_count:100,completed:0,estimated_seconds:60,
    color_stages:[{name:'Red'},{name:'Green'}]}];
  const callsBeforePrompt=calls.length;
  await vm.runInContext('refresh()',sandbox);
  assert.match(elements.get('plot-storage').textContent,/408.*1408/);
  assert.equal(elements.get('pen-change-panel').hidden,false);
  assert.equal(elements.get('pen-change').disabled,true);
  assert.match(elements.get('pen-change-title').textContent,/Red/);
  assert.equal(calls.length,callsBeforePrompt,'Showing a pen prompt never sends motion');
  elements.get('pen-change-confirmed').checked=true;
  elements.get('pen-change-confirmed').onchange();
  await elements.get('pen-change').onclick();
  assert.deepEqual(calls.at(-1),['/api/pen-change',{id:'color-job',run:'color-run',stage:0,confirmed:true}]);
  state.jobs[0].pending_stage=1;
  await vm.runInContext('refresh()',sandbox);
  assert.equal(elements.get('pen-change-confirmed').checked,false,'Each new color needs a new confirmation');
  assert.match(elements.get('pen-change-title').textContent,/Green/);
  const beforeDiagnostic=calls.length;
  await elements.get('diagnostic').onclick();
  assert.equal(calls.at(-1)[0],'/api/import');
  assert.equal(calls.at(-1)[1].diagnostic,true);
  assert.equal(calls.length,beforeDiagnostic+1,'Accuracy pattern only prepares; it must never start motion');
  return 'PASS: separate Prepare/Print & monitor/Calibration pages, independent preparation, upload handoff and safe navigation.';
}

// Also works when loaded by the local Node REPL for verification.
if (typeof process!=='undefined' && process.argv[1] && new URL(import.meta.url).pathname===process.argv[1]) {
  console.log(await runWebTests());
}
