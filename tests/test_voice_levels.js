'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const code=fs.readFileSync(path.join(__dirname,'../frontend/client.js'),'utf8');
const section=(a,b)=>code.slice(code.indexOf(a),code.indexOf(b,code.indexOf(a)));
function harness(){
 const context={};vm.createContext(context);
 vm.runInContext(section('const speech = {','function humanBytes')+'\nthis.speech=speech;',context);
 const speech=context.speech;
 speech.ctx={destination:{},createGain:()=>({gain:{},connect(){}})};
 function buffer(amplitude,silence=0){
  const data=new Float32Array(24000+silence);
  for(let i=0;i<24000;i++)data[i]=amplitude*Math.sin(i*Math.PI/12);
  return {sampleRate:24000,numberOfChannels:1,duration:data.length/24000,getChannelData:()=>data};
 }
 function output(buffer,entry=null,legacyConfig={}){
  const source={buffer,connect(){}};speech.connectOutput(source,legacyConfig,entry);return source._voiceGain.gain.value;
 }
 return {speech,buffer,output};
}
test('one shared analyser measures normalized output without a duplicate audible connection',()=>{
 const h=harness(),ctx=h.speech.ctx,routed=[],meterLinks=[];let creates=0;
 const meter={context:ctx,connect:target=>meterLinks.push(target)};
 ctx.createAnalyser=()=>{creates++;return meter};
 ctx.createGain=()=>({gain:{},connect:target=>routed.push(target)});
 h.output(h.buffer(.1));h.output(h.buffer(.2));
 assert.equal(creates,1);
 assert.equal(h.speech.audioMeter,meter);
 assert.deepEqual(meterLinks,[ctx.destination]);
 assert.deepEqual(routed,[meter,meter]);
 assert.equal(meter.fftSize,512);
});
test('voices with different source levels converge to the same active RMS',()=>{
 const h=harness();
 for(const amplitude of [.06,.2,.7]){
  const b=h.buffer(amplitude),level=h.speech.audioLevel(b);
  assert.ok(Math.abs(level.rms*h.output(b)-.12)<1e-6);
 }
});
test('silence does not increase gain and quiet/noisy input has bounded boost',()=>{
 const h=harness();
 assert.ok(Math.abs(h.output(h.buffer(.2))-h.output(h.buffer(.2,48000)))<1e-6);
 assert.equal(h.output(h.buffer(0)),1);
 assert.equal(h.output(h.buffer(.00001)),1);
 assert.ok(h.output(h.buffer(.01))<=4);
});
test('archived per-character zero volume never silently mutes audio',()=>{
 const h=harness(),b=h.buffer(.2);
 const audible=h.output(b);
 assert.ok(audible>0);
 assert.equal(h.output(b,null,{voiceVolume:0}),audible);
 assert.equal(h.output(b,null,{voicePitch:.7,voiceSpeed:.65}),audible);
});
test('peak headroom includes every channel and does not mutate audio',()=>{
 const h=harness(),left=new Float32Array(2400).fill(.05),right=left.slice();right[1200]=1;
 const b={sampleRate:24000,numberOfChannels:2,duration:.1,getChannelData:ch=>ch?right:left};
 assert.ok(h.output(b)<=.95);assert.equal(right[1200],1);assert.equal(left[0],Math.fround(.05));
});
test('PCM gain follows speech slowly, holds through silence and is isolated per utterance',()=>{
 const h=harness(),entry={};
 const first=h.output(h.buffer(.06),entry);
 const silent=h.output(h.buffer(0),entry);
 assert.equal(silent,first);
 const next=h.output(h.buffer(.2),entry),fresh=h.output(h.buffer(.2),{});
 assert.ok(next<first&&next>fresh);
});
test('inactive TTS stops polling while selected, installing and starting engines stay monitored',async()=>{
 const start=code.lastIndexOf('\nfor(const addon of addons){')+1;
 assert.ok(start>0,'Addon polling block exists at top level');
 const polling=code.slice(start,code.indexOf('\nsyncVoicePanel();',start));
 const addons=['kokoro','kokoro-ru','piper','silero'].map(key=>({key,id:key,state:{status:'stopped'}}));
 const nodes={ttsBackend:{value:'browser'}},calls=[],timers=[];
 const context={addons,$:id=>nodes[id]||(nodes[id]={dataset:{}}),
  refreshAddon:async addon=>calls.push(addon.key),setTimeout:fn=>timers.push(fn)};
 const tick=()=>new Promise(setImmediate);
 vm.runInNewContext(polling,context);
 await tick();assert.equal(calls.length,4);
 calls.length=0;
 for(const fn of timers.splice(0))fn();
 await tick();assert.equal(calls.length,0);
 nodes.ttsBackend.value='kokoro';
 addons[1].state.installation={running:true};addons[2].state.status='starting';
 for(const fn of timers.splice(0))fn();
 await tick();assert.deepEqual(calls,['kokoro','kokoro-ru','piper']);
 calls.length=0;
 nodes.ttsBackend.value='browser';addons[1].state.installation.running=false;addons[2].state.status='stopped';
 for(const fn of timers.splice(0))fn();
 await tick();assert.equal(calls.length,0);
});
test('every TTS exposes an independent per-character voice choice',()=>{
 const modes=['browser','kokoro','piper','silero','qwen3-tts'];
 const context={Option:function(label,value){this.value=value},voices:[{lang:'ru-RU',name:'System',voiceURI:'system'}]};
 vm.createContext(context);
 vm.runInContext(section('const defs = [','// The turn contract must never be spoken aloud:')+section('const piperSpeakers=','const isRussian=')+'\nthis.defs=defs;',context);
 vm.runInContext(section('function optionsForVoices(sel,index){','function forceRenderCards()')+'\nthis.optionsForVoices=optionsForVoices;',context);
 for(const mode of modes){
  context.$=()=>({value:mode});
  for(let i=0;i<3;i++){
   const choices=[],select={replaceChildren(){},add(option){choices.push(option)}};
   context.optionsForVoices(select,i);
   assert.ok(choices.length>=2,mode);
   assert.ok(choices.some(o=>o.value===select.value),mode+' default must exist');
  }
 }
 assert.match(code,/c\.append\(top,name\.wrap,description\.wrap,vc,foot\)/);
});
