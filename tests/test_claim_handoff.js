// Claim handoff stays single-flight across host interruptions and HTTP conflicts.
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'..','frontend','client.js'),'utf8');
const slotStart=source.indexOf('function reserveClaimSlot()');
const retryStart=source.indexOf('function retryClaim(',slotStart);
const retryEnd=source.indexOf('function scheduleNext()',retryStart);
assert(slotStart>=0&&retryStart>slotStart&&retryEnd>retryStart,
 'claim handoff helpers must remain available');
const slotFunctions=source.slice(slotStart,retryStart);
const recoveryFunctions=source.slice(retryStart,retryEnd);

function makeContext(fetchSnapshot=null){
 const timers=[],issued=[];
 const state={
  running:true,paused:false,stopping:false,current:null,claimPending:null,
  epoch:1,pipelineReady:false,core:{status:'RUNNING',agent:-1,next_agent:0,
   ticket:3,revision:3,route_reason:'rotation'},turns:1,timer:null,
  lastClaimRetryNotice:0
 };
 const context=vm.createContext({
  state,
  setTimeout(fn){timers.push(fn);return timers.length;},
  clearTimeout(){},
  fetch:fetchSnapshot||(()=>Promise.reject(Error('unexpected GET'))),
  applyCore(snapshot){
   state.core=snapshot;
   state.turns=snapshot.turns||state.turns;
   state.running=['RUNNING','PAUSED','WAIT_USER'].includes(snapshot.status);
   state.paused=snapshot.status==='PAUSED'||snapshot.status==='WAIT_USER';
   return true;
  },
  issueTurn(agent,ticket){issued.push({agent,ticket});state.current={agent,ticket};},
  stopTimer(){state.timer=null;},
  system:()=>{},
  console,Date,Promise,Number,String
 });
 vm.runInContext(slotFunctions,context);
 vm.runInContext(recoveryFunctions,context);
 return {context,state,timers,issued};
}

test('a new epoch waits for the old claim and is resumed once',()=>{
 const {context,state,timers}=makeContext();
 const first=context.reserveClaimSlot();
 assert.equal(first.epoch,1);
 assert.equal(context.reserveClaimSlot(),null,'same epoch must not reserve twice');

 // humanMessage() advances the epoch while the old claim sequence unwinds.
 state.epoch=2;
 assert.equal(context.reserveClaimSlot(),null,'new epoch must wait for the old claim');
 assert.equal(first.rerun,true);
 assert.equal(first.rerunEpoch,2);

 let resumed=0;
 context.claimNext=()=>{resumed++;};
 context.releaseClaimSlot(first);
 assert.equal(state.claimPending,null);
 assert.equal(timers.length,1,'latest epoch should be queued exactly once');
 timers.shift()();
 assert.equal(resumed,1);
 const next=context.reserveClaimSlot();
 assert.equal(next.epoch,2,'the new epoch can now reserve the slot');
});

test('HTTP 409 adopts the already-claimed ticket from the engine snapshot',async()=>{
 const snapshot={accepted:true,status:'RUNNING',agent:1,next_agent:2,
  ticket:27,revision:9,route_reason:'rotation',turns:4};
 let gets=0;
 const {context,issued,timers}=makeContext(async url=>{
  gets++;
  assert.equal(url,'/api/engine');
  return {ok:true,json:async()=>snapshot};
 });
 await context.reconcileClaimConflict(1,'conflict');
 assert.equal(gets,1);
 assert.deepEqual(issued,[{agent:1,ticket:27}]);
 assert.equal(timers.length,0,'a recovered claim must not enter a retry loop');
});

test('HTTP 409 with no active ticket schedules one retry',async()=>{
 const snapshot={accepted:true,status:'RUNNING',agent:-1,next_agent:2,
  ticket:31,revision:12,route_reason:'rotation',turns:5};
 let gets=0;
 const {context,issued,timers}=makeContext(async()=>{
  gets++;
  return {ok:true,json:async()=>snapshot};
 });
 await context.reconcileClaimConflict(1,'conflict');
 assert.equal(gets,1);
 assert.equal(issued.length,0);
 assert.equal(timers.length,1);
});
