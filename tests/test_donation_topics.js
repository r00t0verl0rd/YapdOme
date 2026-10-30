'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../frontend/client.js'),'utf8');
function harness({amount=100,verdict={decision:'topic',topic:'Жизнь на Марсе'},failure=false}={}){
 const donation={id:'donation-0000001',amount,text:'Жизнь на Марсе',donor:'Зритель',remaining:3,total:3,responses:[],acknowledged:false,item:{meta:{textContent:''}}};
 const state={epoch:1,running:true,paused:false,stopping:false,current:null,donationRouting:false,activeDonation:null,
  donationQueue:[donation],core:{next_agent:1},history:[{text:'Старая тема'}],journal:[{}],social:{memory:[[1],[2],[3]]}};
 const fields={topic:{value:'Старая тема'},model:{value:'test-model'},sharedGoal:{value:'Беседа'},showMode:{value:'live'}};
 const calls=[],routes=[],timers=[],scheduled=[];
 const context={state,AbortController,Promise,console,
  speech:{playing:false,queue:[],nodes:new Set()},$:id=>fields[id],requestID:()=> 'topic-review-0001',
  fetch:async(url,options)=>{calls.push(JSON.parse(options.body));if(failure)throw Error('offline');return {ok:true,json:async()=>verdict};},
  api:async()=>({}),setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout:()=>{},
  coreEvent:async(kind)=>{routes.push(kind);return {accepted:true,status:'RUNNING',kind:'normal',next_agent:1};},
  applyCore:s=>{state.core=s;},updateDonationBadge:()=>{},cancelDirector:()=>{},scheduleNext:()=>scheduled.push(true),claimNext:()=>scheduled.push('claim'),
  fitTopicField:()=>{},savePrefs:()=>{},resetSocialFocus:()=>{},updateScienceUI:()=>{},system:()=>{},
  stopTimer:()=>{},isMarker:()=>false,stripDirectives:s=>s,
  defs:[{name:'Альфа'},{name:'Бета'},{name:'Гамма'}],requestDirector:()=>{},engineError:e=>{throw e;}};
 vm.createContext(context);
 vm.runInContext(code.slice(code.indexOf('const DONATION_REPLIES='),code.indexOf('function donationMessage(')),context);
 vm.runInContext(code.slice(code.indexOf('async function endTurn('),code.indexOf('// The research notebook')),context);
 return {context,state,fields,donation,calls,routes,scheduled};
}
test('a stalled engine control request aborts instead of locking the control queue forever',async()=>{
 const timers=[],context={AbortController,controlQueue:Promise.resolve(),
  setTimeout:(fn,delay)=>{timers.push({fn,delay});return timers.length;},clearTimeout:()=>{},
  api:(url,body,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Object.assign(Error('aborted'),{name:'AbortError'}))))};
 vm.createContext(context);
 vm.runInContext(code.slice(code.indexOf('function coreEvent('),code.indexOf('function applyCore(')),context);
 const pending=context.coreEvent('claim');await Promise.resolve();
 assert.equal(timers[0].delay,12000);timers[0].fn();
 await assert.rejects(pending,{name:'AbortError'});
});
test('model output has agent-name speaker labels removed before display or speech',()=>{
 const context={defs:[{name:'Норман'},{name:'Глитч'},{name:'Джесси'}]};vm.createContext(context);
 vm.runInContext(code.slice(code.indexOf('function stripSpeakerLabels('),code.indexOf('function stripDirectives(')),context);
 assert.equal(context.stripSpeakerLabels('Норман: Вася, Глитч: Вася, это ответ.'),'Вася, Вася, это ответ.');
});
test('0 and 99.99 enter the three-reply scene without an AI review',async()=>{
 for(const amount of [0,99.99]){
  const h=harness({amount});await h.context.activateNextDonation();
  assert.equal(h.calls.length,0);assert.equal(h.state.activeDonation,h.donation);
  assert.equal(h.donation.remaining,3);assert.equal(h.fields.topic.value,'Старая тема');
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
test('rejected, malformed and unavailable reviews fall back to three replies without changing topic',async()=>{
 for(const options of [{verdict:{decision:'chat'}},{verdict:{decision:'topic',topic:''}},{failure:true}]){
  const h=harness(options);await h.context.activateNextDonation();
  assert.equal(h.fields.topic.value,'Старая тема');assert.equal(h.donation.remaining,3);
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
test('the normal scene completes after exactly three replies, all routed to the donor',async()=>{
 const h=harness({amount:0});await h.context.activateNextDonation();
 for(let i=0;i<3;i++){
  const turn={agent:i%3,ticket:i,text:'Короткий ответ.',generatedText:'Короткий ответ.',donation:h.donation,
   item:{el:{classList:{remove(){}},remove(){}},meta:{textContent:''}}};
  h.state.current=turn;await h.context.endTurn(turn,true,'Готово');
  assert.equal(h.donation.remaining,2-i);
  assert.equal(h.state.activeDonation,i===2?null:h.donation);
 }
 assert.equal(h.donation.responses.length,3);assert.match(h.donation.item.meta.textContent,/3 реплики/);
 assert.equal(h.scheduled.at(-1),'claim','the regular show should resume immediately after the third reply');
});

function loadQueueStatus(h){
 h.fields.queueStatus={textContent:'',classList:{toggle(){}}};
 vm.runInContext(code.slice(code.indexOf('function updateDonationBadge(){'),code.indexOf('// Bound both transcript DOM')),h.context);
}
const flush=async()=>{for(let i=0;i<6;i++)await Promise.resolve();};

test('GTA donation stays queued until the third reply finishes audibly',async()=>{
 const h=harness({amount:5});loadQueueStatus(h);
 const first=h.donation;first.text='здарова';first.responses=['1','2'];first.remaining=1;
 const gta={id:'gta-donation',amount:5,text:'а что насчёт гта 6?',donor:'Зритель',total:3,remaining:3,
  responses:[],acknowledged:false,item:{meta:{textContent:''}}};
 h.state.activeDonation=first;h.state.donationQueue=[gta];
 const turn={agent:0,ticket:5,donation:first,audioStarted:true,audioFinished:false,
  text:'Третья реплика.',generatedText:'Третья реплика.',item:{el:{classList:{remove(){}},remove(){}},meta:{textContent:''}}};
 h.state.current=turn;h.state.audibleTurn=turn;h.context.speech.playing=true;
 let drain;h.context.speech.idle=()=>new Promise(resolve=>{drain=resolve;});
 const pending=h.context.endTurn(turn,true,'Готово');
 await flush();
 assert.equal(h.routes.length,0,'engine completion must not precede the audible tail');
 assert.match(first.item.meta.textContent,/ОЗВУЧИВАЕТСЯ ПОСЛЕДНЯЯ/);
 assert.match(gta.item.meta.textContent,/В ОЧЕРЕДИ · № 1/);
 assert.match(gta.item.meta.textContent,/здарова.*осталось ответов: 1/);
 assert.equal(h.state.activeDonation,first);assert.equal(h.state.donationQueue[0],gta);
 h.context.speech.playing=false;turn.audioFinished=true;h.state.audibleTurn=null;drain();
 await pending;await flush();
 assert.match(first.item.meta.textContent,/✓ ОТВЕТ ПОЛУЧЕН · 3 реплики/);
 assert.equal(h.state.activeDonation,gta);assert.equal(h.state.donationQueue.length,0);
 assert.equal(gta.remaining,3);assert.deepEqual(h.routes,['complete','priority_donation']);
});

test('STOP while the last donation reply is playing prevents a late completion or routing',async()=>{
 const h=harness({amount:5});
 h.donation.remaining=1;h.state.activeDonation=h.donation;h.state.donationQueue=[];
 const turn={donation:h.donation,audioStarted:true,audioFinished:false};h.state.current=turn;
 let drain;h.context.speech.idle=()=>new Promise(resolve=>{drain=resolve;});
 const pending=h.context.endTurn(turn,true,'Готово');
 h.state.epoch++;h.state.running=false;h.state.current=null;h.state.activeDonation=null;drain();
 await pending;
 assert.equal(h.routes.length,0);assert.ok(!h.donation.item.meta.textContent.includes('✓'));
});

test('audio completion explicitly wakes a waiting donation once, without a polling timer',async()=>{
 const h=harness({amount:5});
 h.fields.voiceEnabled={checked:true};h.fields.feed={scrollHeight:100,scrollTop:0};
 h.context.ttsText=s=>s;
 let finish;
 h.context.speech.push=(agent,text,onStart,onFinish)=>{finish=onFinish;};
 h.context.speech.idle=()=>Promise.resolve();
 vm.runInContext(code.slice(code.indexOf('function queueWholeSpeech(c){'),code.indexOf('async function issueTurn(agent,ticket)')),h.context);
 const turn={epoch:1,agent:0,text:'Предыдущая реплика',item:{body:{textContent:''},meta:{textContent:''}}};
 await h.context.queueWholeSpeech(turn);
 finish(turn.text);finish(turn.text);await flush();
 assert.equal(h.state.activeDonation,h.donation);assert.equal(h.state.donationQueue.length,0);
 assert.deepEqual(h.routes,['priority_donation']);
});
