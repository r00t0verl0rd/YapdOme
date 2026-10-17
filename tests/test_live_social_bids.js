'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const code=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const a=code.indexOf('function rememberLiveTurn(');
const b=code.indexOf('async function claimNext(',a);
assert(a>=0&&b>a,'social policy helpers must be present');
function setup(){
 const fields={showMode:{value:'live'}};
 const defs=[{name:'Норман'},{name:'Глитч'},{name:'Джесси'}];
 const state={history:[],activeDonation:null,donationQueue:[],social:{memory:[[],[],[]]}};
 const ctx=vm.createContext({state,defs,$:key=>fields[key]});
 vm.runInContext(code.slice(a,b),ctx);
 return {state,fields,ctx};
}
test('live memory keeps bounded attributed quotes, without rewriting personas',()=>{
 const {ctx,fields}=setup();
 for(let i=0;i<5;i++)ctx.rememberLiveTurn(0,'Мой собственный довод номер '+i+' важен.');
 const notes=ctx.liveMemoryPayload();
 assert.equal(notes[0].notes.length,2);
 assert.match(notes[0].notes[0],/номер 3/);
 assert.match(notes[0].notes[1],/номер 4/);
 ctx.rememberLiveTurn(1,'Это коротко');
 assert.equal(ctx.liveMemoryPayload()[1].notes.length,0);
 fields.showMode.value='science';
 assert.equal(ctx.liveMemoryPayload().length,0);
});
test('named questions create motivated bids while empty remarks do not',()=>{
 const {ctx,state}=setup();
 state.history=[
  {agent:1,text:'Криптография и подпись защищают обмен информацией.'},
  {agent:2,text:'Живая сцена и монтаж совершенно другая тема.'},
  {agent:0,text:'Криптография — стоит ли проверять эту подпись?'}];
 assert.equal(ctx.liveFloorBid(0,'Глитч, а криптография действительно защищает подпись?'),1);
 assert.equal(ctx.liveFloorBid(0,'Хм.'),null);
});
test('donation and science never get social floor overrides',()=>{
 const {ctx,state,fields}=setup();
 const question='Глитч, почему это важно?';
 state.activeDonation={};assert.equal(ctx.liveFloorBid(0,question),null);
 state.activeDonation=null;state.donationQueue=[{}];
 assert.equal(ctx.liveFloorBid(0,question),null);
 state.donationQueue=[];fields.showMode.value='science';
 assert.equal(ctx.liveFloorBid(0,question),null);
});
