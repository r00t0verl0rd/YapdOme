'use strict';
// Offline regression for one-look-ahead synthesis; no model, server, or browser needed.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../frontend/client.js'),'utf8');
const section=source.slice(source.indexOf('const speech = {'),source.indexOf('function humanBytes'));
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(setImmediate);};
function harness({deferSecond=true}={}){
 const sources=[],calls=[],deferred=[];
 const buffer=()=>{
  const channel=new Float32Array(2400).fill(.1);
  return {duration:.1,length:2400,sampleRate:24000,numberOfChannels:1,
   getChannelData:()=>channel,copyToChannel(){}};
 };
 const audio={state:'running',currentTime:0,destination:{},resume:async()=>{},
  decodeAudioData:async()=>buffer(),
  createBuffer:()=>buffer(),
  createGain:()=>({gain:{value:1},connect(){},disconnect(){}}),
  createBufferSource(){
   const item={playbackRate:{value:1},connect(){},disconnect(){},stop(){item.stopped=true},
    start(){sources.push(item)}};
   return item;
  }};
 const dom={voiceEnabled:{checked:true},rate:{value:'1'},ttsBackend:{value:'piper'},feed:{scrollTop:0,scrollHeight:10}};
 const context={Date,Promise,AbortController,Uint8Array,Float32Array,DataView,console,
  state:{lastAudibleAt:0},defs:[{name:'Норман',piperVoice:'dmitri'}],
  voices:[],haveSpeech:false,
  piperSpeakers:[['dmitri']],sileroSpeakers:[['aidar']],
  piperSelected:()=>true,sileroSelected:()=>false,kokoroSelected:()=>false,kokoroRuSelected:()=>false,
  isRussian:()=>true,languageFor:()=> 'Russian',ttsText:s=>s,
  window:{AudioContext:function(){return audio}},
  $:id=>dom[id]||(dom[id]={}),
  setTimeout:setTimeout,clearTimeout:clearTimeout,
  fetch:(url,opts)=>{
   calls.push({url,signal:opts.signal,payload:JSON.parse(opts.body)});
   if(deferSecond&&calls.length===2)return new Promise(resolve=>deferred.push(resolve));
   return Promise.resolve(new Response(new Uint8Array([1,2,3,4])));
  },system:s=>{throw Error('Unexpected TTS error: '+s)}};
 vm.createContext(context);
 vm.runInContext(section+'\nthis.speech=speech;',context);
 return {speech:context.speech,sources,calls,deferred,buffer};
}
test('next sentence is synthesized during current audio and played once in FIFO order',async()=>{
 const h=harness(),done=[];
 h.speech.push(0,'Первая реплика.',null,t=>done.push(t));
 await tick();
 assert.equal(h.sources.length,1,'first utterance audible before next arrives');
 h.speech.push(0,'Вторая реплика.',null,t=>done.push(t));
 await tick();
 assert.equal(h.calls.length,2,'the next WAV must begin while previous audio is playing');
 assert.equal(h.sources.length,1,'prepared audio must never start over the current voice');
 h.deferred.shift()(new Response(new Uint8Array([1,2,3,4])));
 await tick();
 assert.ok(h.speech.prefetch?.buffer,'one WAV prepared in advance');
 h.sources[0].onended();
 await tick();
 assert.equal(h.sources.length,2);
 assert.equal(h.calls.length,2,'the ready WAV must not be synthesized twice');
 assert.deepEqual(done,['Первая реплика.']);
 h.sources[1].onended();
 await h.speech.idle();
 assert.deepEqual(done,['Первая реплика.','Вторая реплика.']);
 assert.equal(h.speech.prefetch,null);
});
test('STOP aborts queued prefetch and never resumes stale audio',async()=>{
 const h=harness();
 h.speech.push(0,'До перебивания.');await tick();
 h.speech.push(0,'Это нужно отменить.');await tick();
 assert.equal(h.calls.length,2);
 const signal=h.calls[1].signal;
 h.speech.stop();
 assert.equal(signal.aborted,true);
 assert.equal(h.speech.prefetch,null);
 assert.equal(h.speech.queue.length,0);
 h.deferred.shift()(new Response(new Uint8Array([1,2,3,4])));
 await tick();
 assert.equal(h.sources.length,1,'stale preparation must not start a second voice');
 assert.equal(h.sources[0].stopped,true);
});

test('long local turn is assembled from bounded backend calls into one continuous playback node',async()=>{
 const h=harness({deferSecond:false});
 const full='Цельная реплика с несколькими предложениями. '.repeat(25);
 h.speech.push(0,full);
 for(let i=0;i<12;i++)await tick();
 assert.ok(h.calls.length>1,'the inference backend still receives bounded inputs');
 assert.ok(h.calls.every(call=>call.payload.text.length<=450));
 assert.equal(h.sources.length,1,'browser playback must use only one WAV source for entire reply');
 h.sources[0].onended();
 await h.speech.idle();
 assert.equal(h.sources.length,1);
});

test('OpenAudio uses its local WAV endpoint, selected reference and FIFO prefetch',async()=>{
 const h=harness({deferSecond:false});
 const config={backend:'openaudio-s1-mini',name:'Норман',openaudioVoice:'voice-2',speed:1.2};
 h.speech.push(0,'Первая реплика.',null,null,config);await tick();
 h.speech.push(0,'Вторая реплика.',null,null,config);await tick();
 assert.equal(h.calls.length,2);
 for(const call of h.calls){
  assert.equal(call.url,'/api/voice/openaudio-s1-mini/speak');
  assert.equal(call.payload.voice,'voice-2');
  assert.equal(call.payload.speed,1.2);
 }
 assert.equal(h.sources.length,1,'prefetch must not overlap the current voice');
 h.sources[0].onended();await tick();
 assert.equal(h.sources.length,2);
 h.speech.stop();
 assert.equal(h.sources[1].stopped,true);
});

function browserHarness(){
 const spoken=[],cancelled=[];
 class FakeUtterance{
  constructor(text){this.text=text;this.lang='';this.rate=1;this.pitch=1;this.volume=1;this.voice=null;}
 }
 const dom={voiceEnabled:{checked:true},rate:{value:'1'},ttsBackend:{value:'browser'},feed:{scrollTop:0,scrollHeight:10}};
 const context={Date,Promise,AbortController,Uint8Array,Float32Array,DataView,console,
  state:{lastAudibleAt:0},defs:[{name:'Норман',voiceURI:''}],voices:[],haveSpeech:true,
  SpeechSynthesisUtterance:FakeUtterance,piperSpeakers:[['dmitri']],sileroSpeakers:[['aidar']],
  piperSelected:()=>false,sileroSelected:()=>false,kokoroSelected:()=>false,kokoroRuSelected:()=>false,
  qwen3Selected:()=>false,openaudioSelected:()=>false,
  isRussian:()=>true,languageFor:()=> 'Russian',ttsText:s=>s,
  window:{speechSynthesis:{speak:u=>spoken.push(u),cancel:()=>cancelled.push(true)}},
  $:id=>dom[id]||(dom[id]={}),setTimeout,clearTimeout,
  system:s=>{throw Error('Unexpected TTS error: '+s)}};
 vm.createContext(context);
 vm.runInContext(section+'\nthis.speech=speech;',context);
 return {speech:context.speech,spoken,cancelled};
}
test('browser voice queues the next utterance while current voice is still playing',async()=>{
 const h=browserHarness(),done=[];
 const config={backend:'browser',speed:1,name:'Норман',browserVoice:null};
 h.speech.push(0,'Первая реплика.',null,t=>done.push(t),config);
 assert.equal(h.spoken.length,1,'first browser utterance starts immediately');
 const first=h.spoken[0];
 first.onstart();
 h.speech.push(0,'Вторая реплика.',null,t=>done.push(t),config);
 await tick();
 assert.equal(h.spoken.length,2,'second utterance is sent to native TTS queue before first ends');
 const second=h.spoken[1];
 assert.equal(h.speech.queue.length,1,'second entry remains in app FIFO until first drains');
 assert.equal(h.speech.playing,true);
 assert.deepEqual(done,[]);
 first.onend();
 await tick();
 assert.equal(h.spoken.length,2,'the prepared utterance is reused, not enqueued twice');
 assert.equal(h.speech.browserPrefetch,null);
 assert.equal(h.speech.playing,true);
 second.onstart();
 second.onend();
 await h.speech.idle();
 assert.deepEqual(done,['Первая реплика.','Вторая реплика.']);
});
test('STOP cancels an already queued browser utterance and stale events stay silent',async()=>{
 const h=browserHarness();
 const config={backend:'browser',speed:1,name:'Норман'};
 h.speech.push(0,'Текущая реплика.',null,null,config);
 const first=h.spoken[0];first.onstart();
 h.speech.push(0,'Следующую реплику нужно отменить.',null,null,config);
 await tick();
 assert.equal(h.spoken.length,2);
 const stale=h.spoken[1];
 h.speech.stop();
 assert.equal(h.cancelled.length,1);
 assert.equal(h.speech.browserPrefetch,null);
 assert.equal(h.speech.queue.length,0);
 stale.onstart?.();
 stale.onend?.();
 assert.equal(h.speech.playing,false);
 assert.equal(h.speech.audibleAgent,null);
});
