'use strict';
// Reproduces the narrow interval after TTS finishes but before native COMPLETE.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'..','frontend', 'client.js'),'utf8');
function grab(name,async=false){
 const signature=(async?'async ':'')+'function '+name+'(';
 const begin=code.indexOf(signature);
 assert.ok(begin>=0,'Missing '+signature);
 let depth=0;
 for(let i=code.indexOf('{',begin);i<code.length;i++){
   if(code[i]==='{')depth++;
   else if(code[i]==='}'&&--depth===0)return code.slice(begin,i+1);
 }
 throw Error('Unbalanced '+name);
}
async function verify(action){
 const state={epoch:4,current:null,history:[],journal:[],running:true,
   paused:false,stopping:false,donationQueue:[],activeDonation:null,
   donationRouting:false,lastDonationName:''};
 const calls=[],notifications=[],scheduled=[];
 let resolveNative;
 const nativePromise=new Promise(resolve=>{resolveNative=resolve;});
 const native=async(kind)=>{calls.push(kind);return nativePromise;};
 const helpers={
   state,
   cancelListeners:()=>calls.push('cancel-listeners'),
   coreEvent:native,
   applyCore:s=>{state.core=s;},
   isMarker:()=>false,
   stripDirectives:x=>x,
   defs:[{name:'Альфа'},{name:'Бета'},{name:'Гамма'}],
   rememberClaim:()=>{},
   $:id=>id==='showMode'?{value:'live'}:null,
   donationRepeats:()=>false,
   updateDonationBadge:()=>{},
   activateNextDonation:()=>{notifications.push('donor activated');},
   requestDirector:()=>{},
   scheduleNext:()=>{scheduled.push('next');},
   system:()=>{},
   engineError:e=>{throw e;}
 };
 const keys=Object.keys(helpers);
 const endTurn=Function(...keys,grab('endTurn',true)+';return endTurn')(...Object.values(helpers));
 const c={agent:0,ticket:21,text:'Готовая реплика по теме.',
   generatedText:'Готовая реплика по теме.',item:{
     el:{classList:{remove(){},add(){}},remove(){}},meta:{textContent:''}
   }};
 state.current=c;
 const done=endTurn(c,action==='complete','Завершено');
 await Promise.resolve();
 assert.equal(state.current,c,'native acknowledgement must retain the turn lock');
 assert.equal(calls.includes(action),true,'native '+action+' must be requested');
 // An incoming donation cannot run the NEXT claim while native C is still busy.
 const fields={donationAmount:{value:'50'},donor:{value:'Тест'},donationText:{value:'Привет'}};
 const donorFactory=Function('state','$','system','feedItem','requestID',
   'donationBudget','scheduleNext','updateDonationBadge','cancelListeners',
   grab('donationMessage')+';return donationMessage');
 const donate=donorFactory(state,id=>fields[id],()=>{},
   ()=>({body:{textContent:''},meta:{textContent:''}}),
   ()=>'donation-test',()=>1,()=>scheduled.push('early'),()=>{},helpers.cancelListeners);
 donate();
 assert.equal(state.donationQueue.length,1);
 assert.equal(scheduled.length,0,'donor may not schedule claim before native ACK');
 assert.equal(state.current,c,'donor may not interrupt current audible turn');
 resolveNative({status:'RUNNING',kind:'normal',next_agent:1,errors:1});
 await done;
 assert.equal(state.current,null,'native response releases turn lock');
 assert.deepEqual(notifications,['donor activated']);
 assert.equal(scheduled.length,0,'direct donor routing wins over ordinary schedule');
}
(async()=>{
 await verify('complete');
 await verify('recover');
 console.log('Donation handoff OK: native complete/recover gate + FIFO');
})().catch(err=>{console.error(err);process.exitCode=1;});
