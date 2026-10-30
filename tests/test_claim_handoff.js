// Claim handoff must remain single-flight when a host interruption changes epoch.
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'..','frontend','client.js'),'utf8');
const start=source.indexOf('function retryClaim(');
const end=source.indexOf('function scheduleNext()',start);
assert(start>=0&&end>start,'claim handoff functions must remain available');
const functions=source.slice(start,end);

function makeContext({coreEvent,fetchSnapshot=null}={}){
 const timers=[],issued=[];
 const state={
  running:true,paused:false,stopping:false,current:null,claimPending:null,
  epoch:1,pipelineReady:true,donationRouting:false,donationQueue:[],
  activeDonation:null,history:[],social:{returnContext:null},
  core:{status:'RUNNING',agent:-1,next_agent:0,ticket:3,revision:3,
        route_reason:'rotation'},turns:1,timer:null,lastClaimRetryNotice:0
 };
 const context=vm.createContext({
  state,
  speech:{playing:false,queue:[],nodes:{size:0}},
  $:id=>({value:id==='showMode'?'live':'',checked:false}),
  setTimeout(fn){timers.push(fn);return timers.length;},
  clearTimeout(){},
  fetch:fetchSnapshot||(()=>Promise.reject(Error('unexpected GET'))),
  coreEvent:coreEvent||(()=>Promise.reject(Error('unexpected engine event'))),
  applyCore(snapshot){
   state.core=snapshot;
   state.turns=snapshot.turns||state.turns;
   state.running=['RUNNING','PAUSED','WAIT_USER'].includes(snapshot.status);
   state.paused=snapshot.status==='PAUSED'||snapshot.status==='WAIT_USER';
   return true;
  },
  issueTurn(agent,ticket){issued.push({agent,ticket});state.current={agent,ticket};},
  applyDirectorRoute:async()=>{},
  socialRouteHint:()=>null,
  socialReturnTarget:()=>null,
  liveFloorBid:()=>null,
  stopTimer(){state.timer=null;},
  system:()=>{},
  console,Date,Promise,Number,String
 });
 vm.runInContext(functions,context);
 return {context,state,timers,issued};
}

test('a new epoch waits for the previous claim and is resumed once',async()=>{
 let resolveFirst,claimCalls=0;
 const {context,state,timers,issued}=makeContext({
  coreEvent:action=>{
   assert.equal(action,'claim');
   claimCalls++;
   if(claimCalls===1)return new Promise(resolve=>{resolveFirst=resolve;});
   return Promise.resolve({accepted:true,status:'RUNNING',agent:2,next_agent:0,
    ticket:19,revision:5,route_reason:'rotation',turns:2});
  }
 });

 const first=context.claimNext();
 await Promise.resolve();
 await Promise.resolve();
 assert.equal(claimCalls,1,'first claim should be in flight');

 // This models humanMessage() invalidating the prior turn before asking for
 // the next claim. It must not let a second claim overlap the first one.
 state.epoch=2;
 await context.claimNext();
 assert.equal(claimCalls,1,'new epoch must not issue a concurrent claim');
 assert.equal(state.claimPending.rerun,true);
 assert.equal(state.claimPending.rerunEpoch,2);

 resolveFirst({accepted:true,status:'RUNNING',agent:-1,next_agent:1,
  ticket:18,revision:4,route_reason:'rotation',turns:1});
 await first;
 assert.equal(timers.length,1,'the latest epoch should be queued exactly once');
 timers.shift()();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(claimCalls,2);
 assert.deepEqual(issued,[{agent:2,ticket:19}]);
});

test('HTTP 409 adopts the already-claimed ticket from the engine snapshot',async()=>{
 const snapshot={accepted:true,status:'RUNNING',agent:1,next_agent:2,
  ticket:27,revision:9,route_reason:'rotation',turns:4};
 let gets=0;
 const {context,issued,timers}=makeContext({
  coreEvent:async action=>{assert.equal(action,'claim');throw Error('HTTP 409');},
  fetchSnapshot:async url=>{
   gets++;
   assert.equal(url,'/api/engine');
   return {ok:true,json:async()=>snapshot};
  }
 });
 await context.claimNext();
 assert.equal(gets,1);
 assert.deepEqual(issued,[{agent:1,ticket:27}]);
 assert.equal(timers.length,0,'a recovered claim must not enter retry loop');
});

test('HTTP 409 with no active ticket schedules one bounded retry',async()=>{
 const snapshot={accepted:true,status:'RUNNING',agent:-1,next_agent:2,
  ticket:31,revision:12,route_reason:'rotation',turns:5};
 let gets=0;
 const {context,issued,timers}=makeContext({
  coreEvent:async()=>{throw Error('HTTP 409');},
  fetchSnapshot:async()=>{
   gets++;
   return {ok:true,json:async()=>snapshot};
  }
 });
 await context.claimNext();
 assert.equal(gets,1);
 assert.equal(issued.length,0);
 assert.equal(timers.length,1);
});
