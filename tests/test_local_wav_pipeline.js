'use strict';
// A complete Piper utterance is a single WAV. During playback, the next
// LLM turn and its WAV pre-render may proceed, without overlapping voices.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../frontend/client.js'),'utf8');
const between=(a,b)=>{
 const i=source.indexOf(a),j=source.indexOf(b,i+a.length);
 assert.ok(i>=0&&j>i,a);
 return source.slice(i,j);
};
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(setImmediate);};
function harness(){
 const wavCalls=[],sources=[],completions=[];
 function buffer(){
  const samples=new Float32Array(24000).fill(.1);
  return {duration:1,length:24000,numberOfChannels:1,sampleRate:24000,getChannelData:()=>samples};
 }
 const audio={state:'running',currentTime:0,destination:{},resume:async()=>{},
  decodeAudioData:async()=>buffer(),
  createGain:()=>({gain:{value:1},connect(){},disconnect(){}}),
  createBufferSource(){
   const node={playbackRate:{value:1},connect(){},disconnect(){},stop(){node.stopped=true},
    start(){sources.push(node)}};
   return node;
  }};
 const elements={voiceEnabled:{checked:true},rate:{value:'1'},feed:{scrollTop:0,scrollHeight:100}};
 const state={epoch:1,running:true,paused:false,current:null,turns:1,lastAudibleAt:0,
  pipelineReady:false};
 const defs=[{name:'Норман',piperVoice:'dmitri',voiceURI:''},
  {name:'Глитч',piperVoice:'irina',voiceURI:''}];
 const ctx={console,Date,Promise,AbortController,Uint8Array,Float32Array,DataView,
  state,defs,haveSpeech:false,voices:[],piperSpeakers:[['dmitri'],['irina']],isRussian:()=>true,
  piperSelected:()=>true,sileroSelected:()=>false,
  kokoroSelected:()=>false,kokoroRuSelected:()=>false,audioAvailable:()=>true,
  languageFor:()=> 'Russian',ttsText:s=>s,stripDirectives:s=>String(s||'').trim(),
  isMarker:()=>false,window:{AudioContext:function(){return audio}},
  $:id=>elements[id]||(elements[id]={}),renderCards(){},
  setTimeout,clearTimeout,
  feedItem:()=>({body:{textContent:''},meta:{textContent:''},el:{classList:{remove(){},add(){}}}}),
  requestID:()=>String(++state.turns),requestDirector(){},queueSpeech(){},
  realTurn:async c=>{c.text=c.agent===0?'Первый готовый ответ.':'Следующий готовый ответ, созданный пока играет первый WAV. '.repeat(5);},
  endTurn:async c=>{
   completions.push({agent:c.agent,played:sources.length,ready:state.pipelineReady,wholeWav:c.speechConfig.wholeWav});
   state.current=null;
  },
  fetch:async (url,opt)=>{
   wavCalls.push({url,payload:JSON.parse(opt.body)});

   return new Response(new Uint8Array([0,0,0,0]));
  },
  system:s=>{throw Error(s)}
 };
 vm.createContext(ctx);
 vm.runInContext(between('const speech = {','function humanBytes')+'\nthis.speech=speech;',ctx);
 vm.runInContext(between('function queueWholeSpeech(c){','async function issueTurn(agent,ticket){')+'\nthis.queueWholeSpeech=queueWholeSpeech;',ctx);
 vm.runInContext(between('async function issueTurn(agent,ticket){','async function realTurn(c){')+'\nthis.issueTurn=issueTurn;',ctx);
 return {ctx,state,sources,wavCalls,completions};
}
test('next agent synthesizes entire Piper WAV while previous WAV is audible',async()=>{
 const h=harness();
 await h.ctx.issueTurn(0,101);
 assert.equal(h.completions.length,1);
 assert.deepEqual(h.completions[0],{agent:0,played:1,ready:true,wholeWav:true});
 assert.equal(h.wavCalls.length,1);
 assert.equal(h.wavCalls[0].url,'/api/voice/piper/speak');
 assert.equal(h.sources.length,1);
 assert.equal(h.ctx.speech.audibleAgent,0);
 const next=h.ctx.issueTurn(1,102);
 await tick();
 assert.equal(h.wavCalls.length,2,'the next full WAV must be synthesized during playback');
 assert.equal(h.wavCalls[1].url,'/api/voice/piper/speak');
 assert.match(h.wavCalls[1].payload.text,/созданный пока играет первый WAV/);
 assert.equal(h.sources.length,1,'the next voice must not interrupt current playback');
 assert.equal(h.completions.length,1,'next engine ticket remains active until WAV starts');
 assert.equal(h.ctx.speech.audibleAgent,0,'preparing the next reply cannot switch the audible avatar');
 h.sources[0].onended();
 await next;
 assert.equal(h.sources.length,2);
 assert.equal(h.ctx.speech.audibleAgent,1);
 assert.equal(h.wavCalls.length,2,'the prepared WAV must be reused, not synthesized a second time');
 assert.equal(h.ctx.speech.prefetch,null,'the look-ahead slot must be released so the next reply can be prepared');
 assert.deepEqual(h.completions[1],{agent:1,played:2,ready:true,wholeWav:true});
 h.ctx.speech.stop();
});
test('long show keeps preparing each reply exactly once while the previous plays',async()=>{
 const h=harness();
 await h.ctx.issueTurn(0,101);
 for(let round=1;round<=3;round++){
  const next=h.ctx.issueTurn(round%2,100+round);
  await tick();
  assert.equal(h.sources.length,round,'only the current reply is audible');
  assert.ok(h.ctx.speech.prefetch,'the follow-up reply is prepared during playback');
  h.sources[round-1].onended();
  await next;
 }
 assert.equal(h.wavCalls.length,h.sources.length,'one synthesis per reply: no duplicate or stalled look-ahead');
 assert.equal(h.ctx.speech.prefetch,null);
 h.ctx.speech.stop();
});
test('STOP discards the next ready Piper WAV without playing it',async()=>{
 const h=harness();
 await h.ctx.issueTurn(0,101);
 const next=h.ctx.issueTurn(1,102);
 await tick();
 assert.equal(h.wavCalls.length,2);
 h.state.epoch++;
 h.ctx.speech.stop();
 await next;
 assert.equal(h.sources.length,1);
 assert.equal(h.sources[0].stopped,true);
 assert.equal(h.ctx.speech.audibleAgent,null);
});

test('Engine claims one next turn while full WAV is playing',async()=>{
 const state={epoch:4,running:true,paused:false,current:null,stopping:false,
  pipelineReady:true,claimPending:null,donationQueue:[],activeDonation:null,
  donationRouting:false,core:{status:'RUNNING',route_reason:'rotation'}};
 const speech={playing:true,queue:[],nodes:new Set([{}])};
 const actions=[],launched=[];
 const ctx={state,speech,stopTimer(){},setTimeout(){throw Error('Must not poll audio');},
  async applyDirectorRoute(){},async coreEvent(action){
   actions.push(action);return {status:'RUNNING',agent:1,ticket:42};
  },applyCore(s){state.core=s},issueTurn:(agent,ticket)=>launched.push([agent,ticket]),
  engineError(err){throw err},console};
 vm.createContext(ctx);
 vm.runInContext(between('async function claimNext(){','function scheduleNext(){')+
  '\nthis.claimNext=claimNext;',ctx);
 await ctx.claimNext();
 assert.deepEqual(actions,['claim'],'engine ticket should be claimed before audio ends');
 assert.deepEqual(launched,[[1,42]]);
 assert.equal(state.pipelineReady,false,'only one speculative turn may be claimed');
});
test('non-pipelined engine claim still waits for audio drain',async()=>{
 const state={epoch:4,running:true,paused:false,current:null,
  pipelineReady:false,claimPending:null};
 const speech={playing:true,queue:[],nodes:new Set()};
 let rescheduled=false;
 const ctx={state,speech,stopTimer(){},setTimeout(){rescheduled=true},
  async coreEvent(){throw Error('Cannot claim while audio is playing')},
  console};
 vm.createContext(ctx);
 vm.runInContext(between('async function claimNext(){','function scheduleNext(){')+
  '\nthis.claimNext=claimNext;',ctx);
 await ctx.claimNext();
 assert.equal(rescheduled,true);
});
