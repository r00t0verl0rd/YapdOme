'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const section=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const tick=()=>new Promise(setImmediate);
function harness(backend='browser'){
 const nodes={voiceEnabled:{checked:true},rate:{value:'1'},ttsBackend:{value:backend},feed:{}};
 const sources=[],utterances=[],requests=[],errors=[],timers=new Map();let timer=0;
 function buffer(channels,length,sampleRate){
  const data=Array.from({length:channels},()=>new Float32Array(length).fill(.1));
  return {length,sampleRate,numberOfChannels:channels,duration:length/sampleRate,
   copyToChannel(values,ch,offset=0){data[ch].set(values,offset)},getChannelData:ch=>data[ch]};
 }
 const audio={state:'running',currentTime:0,destination:{},resume:async()=>{},
  createBuffer:buffer,decodeAudioData:async()=>buffer(1,2400,24000),
  createGain(){return {gain:{},connect(){},disconnect(){}}},
  createBufferSource(){const s={playbackRate:{},connect(){},disconnect(){},stop(){s.stopped=true},start(at=0){s.at=at;sources.push(s)}};return s;}};
 const context={console,Date,Promise,AbortController,Uint8Array,Float32Array,DataView,
  state:{epoch:1,lastAudibleAt:0},defs:[{name:'Voice',piperVoice:'dmitri',voicePitch:1,voiceVolume:.5}],
  voices:[],haveSpeech:true,
  piperSpeakers:[['dmitri']],sileroSpeakers:[['aidar']],
  piperSelected:()=>nodes.ttsBackend.value==='piper',sileroSelected:()=>nodes.ttsBackend.value==='silero',
  kokoroSelected:()=>nodes.ttsBackend.value==='kokoro',kokoroRuSelected:()=>nodes.ttsBackend.value==='kokoro-ru',
  qwen3Selected:()=>nodes.ttsBackend.value==='qwen3-tts',
  audioAvailable:()=>true,isRussian:s=>/[а-я]/i.test(s),
  languageFor:()=> 'Russian',isMarker:()=>false,maybeConsultListeners(){},
  SpeechSynthesisUtterance:function(text){this.text=text;utterances.push(this)},
  window:{AudioContext:function(){return audio},speechSynthesis:{speak(){},cancel(){}}},
  $:id=>nodes[id]||(nodes[id]={}),
  setTimeout:fn=>{timers.set(++timer,fn);return timer},clearTimeout:id=>timers.delete(id),
  fetch:async(url,options)=>{requests.push({url,...JSON.parse(options.body)});return new Response(new Uint8Array(4))},
  system:s=>errors.push(s),forceRenderCards(){},updateTTSUI(){}};
 vm.createContext(context);
 vm.runInContext(section('function stripDirectives(raw){','const state =')+section('function ttsText(raw){','const kokoroState=')+section('const speech = {','function humanBytes')+'\nthis.speech=speech;',context);
 vm.runInContext(section('function queueWholeSpeech(c){','function maybeConsultListeners(c){')+'\nthis.queueWholeSpeech=queueWholeSpeech;',context);
 return {context,speech:context.speech,audio,nodes,sources,utterances,requests,errors,timers,buffer,
  advance(time){audio.currentTime=time;const callbacks=[...timers.values()];timers.clear();callbacks.forEach(fn=>fn())}};
}
test('audible speaker updates HUD synchronously on playback start, drain and STOP',()=>{
 const h=harness(),seen=[];
 h.context.window.YapdOmeHud={sync:()=>seen.push(h.speech.audibleAgent)};
 h.speech.push(0,'Проверка синхронизации.');
 assert.equal(h.speech.audibleAgent,null,'queued browser speech has not started');
 h.utterances[0].onstart();
 assert.equal(h.speech.audibleAgent,0);
 assert.equal(h.speech.audibleEntry.text,'Проверка синхронизации.');
 assert.equal(h.speech.audibleEntry.audioMode,'browser');
 assert.deepEqual(seen,[0]);
 h.utterances[0].onend();
 assert.equal(h.speech.audibleEntry,null);
 assert.deepEqual(seen,[0,null]);
 h.speech.push(0,'Следующая фраза.');
 const stale=h.utterances[1];stale.onstart();
 h.speech.stop();
 assert.equal(h.speech.audibleAgent,null);
 stale.onstart();stale.onend();
 assert.deepEqual(seen,[0,null,0,null],'stale callbacks cannot reactivate animation');
});
test('optional puppet module receives actual speech start and STOP when HUD is absent',()=>{
 const h=harness(),seen=[];
 h.context.window.YapdOmePixel={sync:()=>seen.push(h.speech.audibleEntry?.audioMode||null)};
 h.speech.push(0,'Тест пиксельного модуля.');
 assert.equal(seen.length,0);
 h.utterances[0].onstart();h.speech.stop();
 assert.deepEqual(seen,['browser',null]);
});

test('full reply with nested quotes and routing markers is exactly one browser utterance',async()=>{
 const h=harness('browser'),c={agent:0,epoch:1,
  text:'Он сказал: «Очень длинная цитата. «Вложенная речь?» И продолжение! Конец». [[TO:Скептик]]',
  audibleText:'',heardText:'',item:{body:{textContent:''},meta:{}},
  speechConfig:h.speech.snapshot(0)};
 h.context.state.current=c;
 const prepared=h.context.queueWholeSpeech(c);
 assert.equal(h.utterances.length,1,'all completed sentences must be in a single speak()');
 assert.match(h.utterances[0].text,/Вложенная речь/);
 assert.match(h.utterances[0].text,/Конец/);
 assert.doesNotMatch(h.utterances[0].text,/\[\[TO:/);
 assert.equal(c.item.body.textContent,'','text remains hidden before audible speech');
 h.utterances[0].onstart();
 await prepared;
 assert.equal(c.audioStarted,true);
 assert.match(c.audibleText,/И продолжение/);
 h.utterances[0].onend();
 await h.speech.idle();
 assert.equal(c.audioFinished,true);
 assert.equal(h.utterances.length,1);
});
test('one complete reply waits for the previous audible reply, without splitting',async()=>{
 const h=harness('browser');
 h.speech.push(0,'Первая реплика.');
 h.utterances[0].onstart();
 const c={agent:0,epoch:1,text:'Вторая реплика. Сложный вопрос? Полный ответ.',
  audibleText:'',heardText:'',item:{body:{textContent:''},meta:{}},
  speechConfig:h.speech.snapshot(0)};
 const wait=h.context.queueWholeSpeech(c);
 assert.equal(h.utterances.length,1);
 assert.equal(h.speech.queue.length,1,'only a complete turn is queued');
 assert.match(h.speech.queue[0].text,/Полный ответ/);
 h.utterances[0].onend();
 assert.equal(h.utterances.length,2,'one next utterance, no fragment speakers');
 assert.match(h.utterances[1].text,/Вторая реплика.*Полный ответ/);
 h.utterances[1].onstart();await wait;
 h.utterances[1].onend();await h.speech.idle();
 assert.equal(h.utterances.length,2);
});
test('streaming sentence enqueuer is not reachable from the dialogue pipeline',()=>{
 assert.doesNotMatch(source,/function queueSpeech\(|completeSpeechSegments\(|if\(!c\.pipeline\)queueSpeech/);
});
