// Synthetic scheduling/transport tests, not live dialogue or speech e2e.
// Run: node tests/test_director_async.js
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const begin = source.indexOf('function cancelDirector(');
const end = source.indexOf('async function applyDirectorRoute(', begin);
assert(begin >= 0 && end > begin);
const flush = () => new Promise(r => setImmediate(r));
const loop = 'Красные носки лежат возле синего ведра у окна.';
const row = (i, text = `позиция${i} условие${i} проверка${i} результат${i}`) => ({agent:i%3,name:'A',text});
const plan = {speaker:1,beat:'Предложить новый пример.',pace:'short',move:'continue'};

function harness() {
  const fields = {directorEnabled:{checked:true},topic:{value:'Лес'},showMode:{value:'live'},
    model:{value:'test-model'},directorStatus:{textContent:''}};
  const state = {running:true,turns:4,epoch:1,directorAt:-1,
    donationQueue:[],history:Array.from({length:4},(_,i)=>row(i))};
  let now=0;
  const calls=[];
  const context=vm.createContext({state,defs:[{name:'A'},{name:'B'},{name:'C'}],
    $:id=>fields[id],AbortController,performance:{now:()=>now},
    requestID:()=>`synthetic-request-${calls.length}`,api:async()=>({}),
    isMarker:text=>/^\[\[.*\]\]$/.test(text),
    stripDirectives:text=>text.replace(/\[\[.*?\]\]/g,''),
    fetch:()=>new Promise((resolve,reject)=>calls.push({resolve,reject,at:state.turns,time:now}))});
  vm.runInContext(source.slice(begin,end),context);
  return {state,fields,calls,context,time:t=>{now=t;},
    finish:async(value=plan)=>{calls.at(-1).resolve({ok:true,json:async()=>({plan:value})});await flush();}};
}

async function main() {
  // Exact trigram policy and bounded inspection; microreactions are not loops.
  const h=harness(), stuck=h.context.directorStuck;
  assert(stuck([row(0,loop),row(1,loop),row(2,loop)]));
  assert(stuck([row(0,loop),row(1,loop),row(2,loop+' И что дальше?')]));
  assert(!stuck([row(0,loop),row(1,'Другой пример меняет проверяемые условия.'),row(2,loop)]));
  assert(!stuck(Array.from({length:8},(_,i)=>row(i,'Ну да'))));
  assert(!stuck(Array.from({length:8},(_,i)=>row(i,'[[PASS]]'))));
  assert(!stuck([row(0,loop),{...row(1,loop),untrusted:true},row(2,loop)]));
  assert(!stuck([row(0,loop),{...row(1,loop),agent:-1},row(2,loop)]));
  assert(!stuck([row(0,loop),row(1,loop),...Array.from({length:7},(_,i)=>row(i)),row(2,loop)]));
  assert(!stuck([row(0,loop),row(1,loop),row(2,' '.repeat(420)+loop)]));
  assert(!stuck([row(0,loop),row(1,loop),row(2,'Хм')]));

  assert.equal(h.context.requestDirector(),undefined,'transport never blocks caller');
  h.time(100000);h.state.turns=20;h.context.requestDirector();
  assert.equal(h.calls.length,1,'single flight even when overdue');
  await h.finish();
  assert.equal(h.state.directorPlan,undefined,'discard plan older than four turns');
  assert.equal(h.state.directorRequest,null);

  // Healthy/stuck budget counts across synthetic 30/50/100/300-turn fixtures.
  for(const count of [30,50,100,300])for(const repeats of [false,true]){
    const t=harness();
    for(let turn=1;turn<=count;turn++){
      t.state.turns=turn;t.time(turn*10000);
      t.state.history=Array.from({length:Math.min(turn,8)},(_,i)=>row(turn-i,repeats?loop:undefined));
      t.context.requestDirector();
      if(t.state.directorRequest)await t.finish();
      t.context.requestDirector(); // same-turn callback must not spend again
    }
    const expected=1+Math.floor((count-4)/(repeats?2:4));
    assert.equal(t.calls.length,expected);
    for(let i=1;i<t.calls.length;i++){
      assert(t.calls[i].at-t.calls[i-1].at>=2);
      assert(t.calls[i].time-t.calls[i-1].time>=15000);
    }
    console.log(`SYNTHETIC ${count} turns ${repeats?'stuck':'healthy'}: ${t.calls.length} calls`);
  }

  // Failed/null/cancelled requests consume budget; exact time boundary is inclusive.
  for(const outcome of ['failed','null','cancelled']){
    const t=harness();t.state.history=Array.from({length:4},(_,i)=>row(i,loop));
    t.context.requestDirector();
    if(outcome==='failed'){t.calls[0].reject(Error('offline'));await flush();}
    else if(outcome==='null')await t.finish(null);
    else {const job=t.state.directorRequest;t.context.cancelDirector();assert(job.controller.signal.aborted);}
    t.state.turns=6;t.time(14999);t.context.requestDirector();assert.equal(t.calls.length,1);
    t.time(15000);t.state.turns=5;t.context.requestDirector();assert.equal(t.calls.length,1);
    t.state.turns=6;t.context.requestDirector();assert.equal(t.calls.length,2);
    if(outcome==='cancelled'){
      t.calls[0].resolve({ok:true,json:async()=>({plan})});await flush();
      assert(t.state.directorRequest,'old finally must not clear new job');
      assert.equal(t.state.directorPlan,null);
    }
    await t.finish();assert.equal(t.state.directorPlan.speaker,1);
  }

  // Re-evaluate the current window: healthy -> stuck accelerates, recovery slows.
  const t=harness();t.context.requestDirector();await t.finish();
  t.time(20000);t.state.turns=6;t.context.requestDirector();assert.equal(t.calls.length,1);
  t.state.history=Array.from({length:4},(_,i)=>row(i,loop));
  t.context.requestDirector();assert.equal(t.calls.length,2);await t.finish();
  t.time(40000);t.state.turns=8;t.state.history=Array.from({length:8},(_,i)=>row(i));
  t.context.requestDirector();assert.equal(t.calls.length,2);
  t.state.turns=14;t.context.requestDirector();assert.equal(t.calls.length,3);

  for(const guard of ['donation','queued','paused','stopping','stopped','disabled']){
    const g=harness();
    const set=()=>{
      if(guard==='donation')g.state.activeDonation={};
      if(guard==='queued')g.state.donationQueue=[{}];
      if(guard==='paused')g.state.paused=true;
      if(guard==='stopping')g.state.stopping=true;
      if(guard==='stopped')g.state.running=false;
      if(guard==='disabled')g.fields.directorEnabled.checked=false;
    };
    g.context.requestDirector();set();await g.finish();
    assert.equal(g.state.directorPlan,undefined,guard+' rejects inflight result');
    g.time(100000);g.state.turns=20;g.context.requestDirector();
    assert.equal(g.calls.length,1,guard+' gates new requests');
  }
  for(const stale of ['epoch','topic','cancel']){
    const g=harness();g.context.requestDirector();
    if(stale==='epoch')g.state.epoch++;
    if(stale==='topic')g.fields.topic.value='Другая тема';
    if(stale==='cancel')g.context.cancelDirector();
    const status=g.fields.directorStatus.textContent;
    await g.finish();assert(!g.state.directorPlan,stale);
    assert.equal(g.fields.directorStatus.textContent,status);
  }
  // Fast turns cannot turn the stuck interval into a request storm.
  const fast=harness();
  for(let turn=1;turn<=300;turn++){
    fast.state.turns=turn;fast.time(turn*1000);
    fast.state.history=Array.from({length:Math.min(turn,8)},(_,i)=>row(i,loop));
    fast.context.requestDirector();if(fast.state.directorRequest)await fast.finish();
  }
  assert.equal(fast.calls.length,20,'300 one-second turns remain capped by time');
  for(let i=1;i<fast.calls.length;i++)assert(fast.calls[i].time-fast.calls[i-1].time>=15000);

  const latest=harness();latest.state.turns=3;latest.context.requestDirector();
  assert.equal(latest.calls.length,0,'no bootstrap before turn four');
  latest.state.turns=4;latest.context.requestDirector();await latest.finish();
  latest.state.turns=6;latest.time(15000);
  latest.state.history=[row(0,loop),row(1,loop),row(2),row(0)];
  latest.context.requestDirector();assert.equal(latest.calls.length,1);
  latest.context.requestDirector({agent:2,text:loop});
  assert.equal(latest.calls.length,2,'completed current turn participates before history append');

  const error=harness();error.context.requestDirector();error.context.cancelDirector();
  const status=error.fields.directorStatus.textContent;
  error.calls[0].reject(Error('late network failure'));await flush();
  assert.equal(error.fields.directorStatus.textContent,status,'stale error cannot replace status');

  // New session resets budget without requiring edits to session/speech methods.
  const fresh=harness();fresh.context.requestDirector();fresh.context.cancelDirector();
  fresh.state.epoch++;fresh.context.requestDirector();assert.equal(fresh.calls.length,2);
  console.log('PASS: adaptive cadence, hard budgets, bounded lexical signal, nonblocking singleflight, guards');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
