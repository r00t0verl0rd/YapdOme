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
const messages=[],items=[],scheduled=[];
const ui=Function('state','$','system','feedItem','requestID','DONATION_REPLIES','scheduleNext','updateDonationBadge',
 grab('donationMessage')+';return donationMessage')(
 state,k=>controls[k],msg=>messages.push(msg),
 name=>{const item={name,body:{textContent:''},meta:{textContent:''}};items.push(item);return item;},
 ()=>String(items.length),3,()=>scheduled.push(true),()=>{});
ui();
assert.equal(state.donationQueue.length,1);
assert.equal(state.donationQueue[0].donor,'Даша');
assert.equal(state.donationQueue[0].amount,50);
assert.equal(state.donationQueue[0].total,3);
assert.equal(scheduled.length,0,'new donor MUST NOT interrupt current speech');
assert.equal(state.current.agent,0,'queued donor leaves the speaking turn untouched');
assert.match(items[0].body.textContent,/^50\.00 · /);
assert.ok(!items[0].body.textContent.includes('€'));
state.activeDonation=state.donationQueue[0];
controls.donationAmount.value='100';controls.donor.value='Иван';controls.donationText.value='Сложный вопрос о будущем, развитии роботов, учёбе, цене проекта и последствиях для простых людей.';
ui();
assert.equal(state.donationQueue.length,2);
assert.equal(state.donationQueue[1].total,3);
assert.equal(scheduled.length,0,'second donation queues behind first');

controls.donationAmount.value='-1';ui();
assert.equal(state.donationQueue.length,2);
assert.match(messages.at(-1),/сумма/i);
console.log('Donation UI OK: three replies, amounts without currency, FIFO and audio-safe queue');
