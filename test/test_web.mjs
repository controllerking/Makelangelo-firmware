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
      append(){},replaceChildren(){},reportValidity:()=>true,
      getBoundingClientRect:()=>({width:600,height:600}),getContext:()=>ctx};
  }
  for(const [,id] of html.matchAll(/id="([^"]+)"/g))elements.set(id,element());
  for(const [id,value] of Object.entries({paper:'Letter',left:'100',top:'-100',margin:'20',feed:'10',quality:'balanced','image-mode':'hatching',threshold:'128'}))elements.get(id).value=value;
  const state={connected:false,device:{},jobs:[],presets:{
    fast:{resolution:256,feed:15,description:'Fast'},balanced:{resolution:512,feed:10},detailed:{resolution:768,feed:6,description:'Detailed'},
  }};
  const sandbox=vm.createContext({
    document:{getElementById:id=>{assert(elements.has(id),'Unknown DOM id: '+id);return elements.get(id);},
      createElement:()=>element(),activeElement:null},
    window:{devicePixelRatio:1},ResizeObserver:class{observe(){}},
    setTimeout:()=>0,clearTimeout(){},setInterval(){},
    btoa:value=>Buffer.from(value,'binary').toString('base64'),
    createImageBitmap:async file=>{
      if(file.bad)throw new Error('bad file');
      return {width:file.width||2,height:file.height||2,close(){closed++;}};
    },
    fetch:async (url,options)=>{
      if(url==='/api/status')return {ok:true,json:async()=>state};
      calls.push([url,JSON.parse(options.body)]);
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
  assert.equal(calls[0][1].name,'photo.png');
  assert.equal(calls[0][1].image.width,2);
  assert.equal(elements.get('prepare').disabled,false);
  assert.equal(vm.runInContext('selected',sandbox),'prepared');
  elements.get('reviewed').checked=true;
  elements.get('margin').input();
  assert.equal(vm.runInContext('selected',sandbox),null);
  assert.equal(elements.get('reviewed').checked,false);
  assert.equal(calls.length,1,'Settings changes must not send motion or imports');
  return 'PASS: image payload/grayscale, decode errors, pixel limit, presets, preview import and stale-review invalidation.';
}

// Also works when loaded by the local Node REPL for verification.
if (typeof process!=='undefined' && process.argv[1] && new URL(import.meta.url).pathname===process.argv[1]) {
  console.log(await runWebTests());
}
