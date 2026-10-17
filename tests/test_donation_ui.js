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
const tiers=Function(grab('donationTurns')+';return donationTurns')();
for(const [amount,expected] of [[0,1],[4.99,1],[5,2],[19.99,2],[20,3],[49.99,3],[50,5],[99.99,5],[100,8]]){
 assert.equal(tiers(amount),expected);
}
const budget=Function('donationTurns',grab('donationBudget')+';return donationBudget')(tiers);
const duplicates=Function(grab('donationRepeats')+';return donationRepeats')();
assert.equal(budget(50,'Здарова пацаны'),1,'greeting never becomes five thank-yous');
assert.equal(budget(500,'Что вы вообще тут делаете?'),2,'simple question should not spawn eight summaries');
assert.equal(budget(100,'Какую технологию вы выберете для реального проекта, почему и какой первый эксперимент, риски, стоимость и способы проверки? Какие у неё реальные ограничения, что будут делать люди, как измерить пользу и проверить ошибки?'),8);
assert.equal(duplicates(['Нам нужны курсы роботов и цифровой грамотности, чтобы помогать людям',
 'Роботы должны помогать людям через курсы цифровой грамотности']),true);
const controls={donationAmount:{value:'50'},donor:{value:'Даша'},donationText:{value:'Здарова пацаны'}};
const state={running:true,stopping:false,paused:false,current:{agent:0},
 donationRouting:false,activeDonation:null,donationQueue:[],lastDonationAt:0};
const messages=[],items=[],scheduled=[],cancelled=[];
const ui=Function('state','$','system','feedItem','requestID','donationBudget','scheduleNext','updateDonationBadge','cancelListeners',
 grab('donationMessage')+';return donationMessage')(
 state,k=>controls[k],msg=>messages.push(msg),
 name=>{const item={name,body:{textContent:''},meta:{textContent:''}};items.push(item);return item;},
 ()=>String(items.length),budget,()=>scheduled.push(true),()=>{},c=>cancelled.push(c));
ui();
assert.equal(state.donationQueue.length,1);
assert.equal(state.donationQueue[0].donor,'Даша');
assert.equal(state.donationQueue[0].amount,50);
assert.equal(state.donationQueue[0].total,1);
assert.equal(scheduled.length,0,'new donor MUST NOT interrupt current speech');
assert.equal(cancelled.length,1,'queued donor cancels pending listener decisions only');
assert.equal(cancelled[0],state.current,'speaking generation remains the active turn');
assert.equal(state.current.intentSent,true,'no new automatic interruption may start');
assert.match(items[0].body.textContent,/€50.00/);
state.activeDonation=state.donationQueue[0];
controls.donationAmount.value='100';controls.donor.value='Иван';controls.donationText.value='Сложный вопрос о будущем, развитии роботов, учёбе, цене проекта и последствиях для простых людей.';
ui();
assert.equal(state.donationQueue.length,2);
assert.equal(state.donationQueue[1].total,3);
assert.equal(scheduled.length,0,'second donation queues behind first');
assert.equal(cancelled.length,2,'each arrival clears stale background listener requests');
controls.donationAmount.value='-1';ui();
assert.equal(state.donationQueue.length,2);
assert.match(messages.at(-1),/сумма/i);
assert.equal(duplicates(['Роботы помогут людям','Роботы помогут людям!']),true,
 'exact short replies are also deduplicated');
assert.equal(duplicates(['Будущее города — это курсы роботов и цифровой грамотности для людей',
 'Цифровая грамотность и курсы роботов помогут людям строить город будущего']),true,
 'same claim with rearranged words terminates the donor scene');
console.log('Donation UI OK: FIFO, audio safe queue, listener cancellation and repeat guard');
