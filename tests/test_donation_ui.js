'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'..','frontend', 'client.js'),'utf8');
function grab(name){
 const begin=code.indexOf('function '+name+'(');
 if(begin<0)throw Error('Missing '+name);
 let count=0;
 for(let i=code.indexOf('{',begin);i<code.length;i++){
  if(code[i]==='{')count++;else if(code[i]==='}'&&--count===0)return code.slice(begin,i+1);
 }
 throw Error('Missing closing brace: '+name);
}
const controls={donationAmount:{value:'50'},donor:{value:'Даша'},donationText:{value:'Здарова пацаны'}};
const state={running:true,stopping:false,paused:false,current:{agent:0},
 donationRouting:false,activeDonation:null,donationQueue:[],lastDonationAt:0};
const messages=[],items=[],scheduled=[],cancelled=[];
const ui=Function('state','$','system','feedItem','requestID','DONATION_REPLIES','scheduleNext','updateDonationBadge','cancelListeners',
 grab('donationMessage')+';return donationMessage')(
 state,k=>controls[k],msg=>messages.push(msg),
 name=>{const item={name,body:{textContent:''},meta:{textContent:''}};items.push(item);return item;},
 ()=>String(items.length),5,()=>scheduled.push(true),()=>{},c=>cancelled.push(c));
ui();
assert.equal(state.donationQueue.length,1);
assert.equal(state.donationQueue[0].donor,'Даша');
assert.equal(state.donationQueue[0].amount,50);
assert.equal(state.donationQueue[0].total,5);
assert.equal(scheduled.length,0,'new donor MUST NOT interrupt current speech');
assert.equal(cancelled.length,1,'queued donor cancels pending listener decisions only');
assert.equal(cancelled[0],state.current,'speaking generation remains the active turn');
assert.equal(state.current.intentSent,true,'no new automatic interruption may start');
assert.match(items[0].body.textContent,/^50\.00 · /);
assert.ok(!items[0].body.textContent.includes('€'));
state.activeDonation=state.donationQueue[0];
controls.donationAmount.value='100';controls.donor.value='Иван';controls.donationText.value='Сложный вопрос о будущем, развитии роботов, учёбе, цене проекта и последствиях для простых людей.';
ui();
assert.equal(state.donationQueue.length,2);
assert.equal(state.donationQueue[1].total,5);
assert.equal(scheduled.length,0,'second donation queues behind first');
assert.equal(cancelled.length,2,'each arrival clears stale background listener requests');
controls.donationAmount.value='-1';ui();
assert.equal(state.donationQueue.length,2);
assert.match(messages.at(-1),/сумма/i);
console.log('Donation UI OK: five replies, amounts without currency, FIFO and audio-safe queue');
