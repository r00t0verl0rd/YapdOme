// Native interruption regression: the next model must know what it interrupted.
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const src=fs.readFileSync(path.join(__dirname,'../frontend/client.js'),'utf8');
const a=src.indexOf('async function interruptWith(agent,reason){'),
      b=src.indexOf('function scheduleNext(){',a);
assert(a>=0&&b>a);
function harness(accepted=true){
 let launched=0,notices=[];
 const state={running:true,paused:false,stopping:false,epoch:4,history:[],
  core:{ticket:33},activeDonation:null,donationQueue:[],
  current:{agent:0,donation:null,heardText:'Это важная мысль об искусственном интеллекте.',
   audioStarted:true,audibleText:'Это важная мысль об искусственном интеллекте. Вторая часть ещё не звучала.',
   text:'Это важная мысль об искусственном интеллекте. Вторая часть ещё не звучала.'}};
 const ctx=vm.createContext({state,defs:[{name:'Норман'},{name:'Глитч'},{name:'Джесси'}],
  speech:{playing:true,queue:[]},stopTimer(){},cancelCurrent(){state.current=null;},
  applyCore(s){state.core=s;},coreEvent:async()=>({accepted,ticket:34}),
  system:s=>notices.push(s),claimNext(){launched++;},
  stripDirectives:s=>s,console});
 vm.runInContext(src.slice(a,b),ctx);
 return {state,ctx,notices,launched:()=>launched};
}
test('accepted AI interruption retains only limited attributed excerpt',async()=>{
 const x=harness();
 await x.ctx.interruptWith(1,'ai');
 assert.equal(x.state.history.length,1);
 assert.equal(x.state.history[0].agent,0);
 assert.equal(x.state.history[0].interrupted,true);
 assert.equal(x.state.history[0].name,'Норман');
 assert.match(x.state.history[0].text,/Это важная мысль/);
 assert.doesNotMatch(x.state.history[0].text,/Вторая часть/);
 assert.equal(x.state.epoch,5);
 assert.equal(x.launched(),1);
});
test('stale native interruption leaves transcript and session untouched',async()=>{
 const x=harness(false);await x.ctx.interruptWith(1,'ai');
 assert.equal(x.state.history.length,0);
 assert.equal(x.state.epoch,4);
 assert.equal(x.launched(),0);
});
test('priority donation blocks speculative AI interruption',async()=>{
 const x=harness();x.state.donationQueue.push({});
 await x.ctx.interruptWith(1,'ai');
 assert.equal(x.state.history.length,0);
 assert.equal(x.launched(),0);
});
