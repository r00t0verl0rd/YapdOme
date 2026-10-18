'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../frontend/client.js'),'utf8');
function harness({amount=100,verdict={decision:'topic',topic:'Жизнь на Марсе'},failure=false}={}){
 const donation={id:'donation-0000001',amount,text:'Жизнь на Марсе',donor:'Зритель',remaining:5,total:5,responses:[],acknowledged:false,item:{meta:{textContent:''}}};
 const state={epoch:1,running:true,paused:false,stopping:false,current:null,donationRouting:false,activeDonation:null,
  donationQueue:[donation],core:{next_agent:1},history:[{text:'Старая тема'}],journal:[{}],social:{memory:[[1],[2],[3]]}};
 const fields={topic:{value:'Старая тема'},model:{value:'test-model'},sharedGoal:{value:'Беседа'},showMode:{value:'live'}};
 const calls=[],routes=[],timers=[],scheduled=[];
 const context={state,AbortController,Promise,console,
  speech:{playing:false,queue:[],nodes:new Set()},$:id=>fields[id],requestID:()=> 'topic-review-0001',
  fetch:async(url,options)=>{calls.push(JSON.parse(options.body));if(failure)throw Error('offline');return {ok:true,json:async()=>verdict};},
  api:async()=>({}),setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout:()=>{},
  coreEvent:async(kind)=>{routes.push(kind);return {accepted:true,status:'RUNNING',kind:'normal',next_agent:1};},
  applyCore:s=>{state.core=s;},updateDonationBadge:()=>{},cancelDirector:()=>{},scheduleNext:()=>scheduled.push(true),
  fitTopicField:()=>{},savePrefs:()=>{},resetSocialFocus:()=>{},updateScienceUI:()=>{},system:()=>{},
  stopTimer:()=>{},claimNext:()=>{},cancelListeners:()=>{},isMarker:()=>false,stripDirectives:s=>s,
  defs:[{name:'Альфа'},{name:'Бета'},{name:'Гамма'}],requestDirector:()=>{},engineError:e=>{throw e;}};
 vm.createContext(context);
 vm.runInContext(code.slice(code.indexOf('const DONATION_REPLIES='),code.indexOf('function donationMessage(')),context);
 vm.runInContext(code.slice(code.indexOf('async function endTurn('),code.indexOf('// The research notebook')),context);
 return {context,state,fields,donation,calls,routes,scheduled};
}
test('0 and 99.99 enter the five-reply scene without an AI review',async()=>{
 for(const amount of [0,99.99]){
  const h=harness({amount});await h.context.activateNextDonation();
  assert.equal(h.calls.length,0);assert.equal(h.state.activeDonation,h.donation);
  assert.equal(h.donation.remaining,5);assert.equal(h.fields.topic.value,'Старая тема');
 }
});
test('100 changes the persistent topic after approval and waits for an audible reply before the next donor',async()=>{
 const h=harness();await h.context.activateNextDonation();
 assert.equal(h.calls.length,1);assert.equal(h.calls[0].amount,100);
 assert.equal(h.fields.topic.value,'Жизнь на Марсе');assert.equal(h.state.journal.length,0);
 assert.equal(h.state.history.length,1);assert.match(h.state.history[0].text,/Жизнь на Марсе/);
 assert.equal(h.state.activeDonation,h.donation);assert.equal(h.donation.topicChanged,true);
 assert.equal(h.state.donationRouting,false);
});
test('rejected, malformed and unavailable reviews fall back to five replies without changing topic',async()=>{
 for(const options of [{verdict:{decision:'chat'}},{verdict:{decision:'topic',topic:''}},{failure:true}]){
  const h=harness(options);await h.context.activateNextDonation();
  assert.equal(h.fields.topic.value,'Старая тема');assert.equal(h.donation.remaining,5);
  assert.equal(h.state.activeDonation,h.donation);assert.match(h.donation.item.meta.textContent,/ТЕМА НЕ ПРИНЯТА/);
 }
});
test('a playing voice delays review and routing',async()=>{
 const h=harness();h.context.speech.playing=true;
 await h.context.activateNextDonation();
 assert.equal(h.calls.length,0);assert.equal(h.routes.length,0);assert.equal(h.state.donationQueue.length,1);
});
test('a stale AI review cannot overwrite the host topic or unlock another donation',async()=>{
 const h=harness();let resolve;
 h.context.fetch=()=>new Promise(r=>{resolve=r;});
 const pending=h.context.activateNextDonation();
 h.state.epoch++;h.fields.topic.value='Тема ведущего';const newer={id:'new'};h.state.donationRouting=newer;
 resolve({ok:true,json:async()=>({decision:'topic',topic:'Жизнь на Марсе'})});await pending;
 assert.equal(h.fields.topic.value,'Тема ведущего');assert.equal(h.routes.length,0);
 assert.equal(h.state.donationRouting,newer);
});
test('a host intervention releases the old review lock and resumes scheduling',async()=>{
 const h=harness();let resolve;
 h.context.fetch=()=>new Promise(r=>{resolve=r;});
 const pending=h.context.activateNextDonation();
 h.state.epoch++;h.fields.topic.value='Тема ведущего';
 resolve({ok:true,json:async()=>({decision:'topic',topic:'Жизнь на Марсе'})});await pending;
 assert.equal(h.fields.topic.value,'Тема ведущего');assert.equal(h.state.donationRouting,false);
 assert.equal(h.scheduled.length,1);
});
test('the normal scene completes after five successful replies, including short or repeated responses',async()=>{
 const h=harness({amount:0});await h.context.activateNextDonation();
 for(let i=0;i<5;i++){
  const turn={agent:i%3,ticket:i,text:'Короткий ответ.',generatedText:'Короткий ответ.',donation:h.donation,
   item:{el:{classList:{remove(){}},remove(){}},meta:{textContent:''}}};
  h.state.current=turn;await h.context.endTurn(turn,true,'Готово');
  assert.equal(h.donation.remaining,4-i);
  assert.equal(h.state.activeDonation,i===4?null:h.donation);
 }
 assert.equal(h.donation.responses.length,5);assert.match(h.donation.item.meta.textContent,/5 реплик/);
});
