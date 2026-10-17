'use strict';
// Deterministic browser-speech regression: a model may finish immediately,
// but no text / next native turn may be committed before audible completion.
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const between=(begin,end)=>{const a=source.indexOf(begin);assert(a>=0,begin);const b=source.indexOf(end,a);assert(b>a,end);return source.slice(a,b)};
const nodes={voiceEnabled:{checked:true},rate:{value:'1'},feed:{scrollHeight:50,scrollTop:0}};
const utterances=[];
class Utterance{constructor(text){this.text=text;utterances.push(this)}}
const ctx={
  Date,Promise,AbortController,Uint8Array,Float32Array,DataView,
  state:{epoch:1,running:true,paused:false,turns:1,current:null,lastAudibleAt:0},
  defs:[{name:'Архитектор',voiceURI:''},{name:'Скептик',voiceURI:''}],
  voices:[],haveSpeech:true,SpeechSynthesisUtterance:Utterance,
  window:{speechSynthesis:{speak(){},cancel(){}}},
  $:id=>nodes[id]||(nodes[id]={textContent:''}),
  piperSelected:()=>false,sileroSelected:()=>false,kokoroSelected:()=>false,kokoroRuSelected:()=>false,qwen3Selected:()=>false,isRussian:()=>true,
  audioAvailable:()=>true,ttsText:s=>String(s||''),
  languageFor:()=> 'Russian',
  setTimeout:()=>1,clearTimeout:()=>{},
  stripDirectives:s=>String(s||'').trim(),isMarker:()=>false,
  requestID:()=> 'mockid',
  feedItem:()=>({body:{textContent:''},meta:{textContent:''},el:{classList:{remove(){},add(){}}}}),
  renderCards(){}, maybeConsultListeners(){},
  ended:0,
};
ctx.endTurn=async c=>{ctx.ended++;ctx.state.current=null};
let finishModel;
ctx.realTurn=async c=>{
  c.text='Первое предложение.';
  // Token stream can contain a finished sentence, but it must stay silent.
  await new Promise(resolve=>{finishModel=resolve});
  c.text+=' Второе предложение.';
};
vm.createContext(ctx);
vm.runInContext(between('const speech = {','function humanBytes')+'\nthis.speech=speech;',ctx);
vm.runInContext(between('function queueWholeSpeech(c){','function maybeConsultListeners(c){')+'\nthis.queueWholeSpeech=queueWholeSpeech;',ctx);
vm.runInContext(between('async function issueTurn(agent,ticket){','async function realTurn(c){')+'\nthis.issueTurn=issueTurn;',ctx);
(async()=>{
 const p=ctx.issueTurn(0,22);
 await Promise.resolve();await Promise.resolve();
 assert.equal(utterances.length,0,'a completed sentence is not enough to start speech');
 assert.equal(ctx.ended,0);
 assert.equal(ctx.state.current.item.body.textContent,'','partial model text is not shown early');
 finishModel();
 await new Promise(setImmediate);
 assert.equal(utterances.length,1,'full model answer must create exactly one utterance');
 assert.equal(utterances[0].text,'Первое предложение. Второе предложение.');
 utterances[0].onstart();
 assert.equal(ctx.state.current.item.body.textContent,'Первое предложение. Второе предложение.');
 assert.equal(ctx.ended,0);
 nodes.voiceEnabled.checked=false;
 utterances[0].onend();
 assert.equal(utterances.length,1,'the complete turn is one utterance, not sentence fragments');
 await p;
 assert.equal(ctx.ended,1,'native turn commits only after all audio');
 assert.equal(ctx.state.current,null);
 console.log('Speech-clock regression OK: hidden stream, first start, complete utterance, native commit after end');
})().catch(e=>{console.error(e);process.exitCode=1});
