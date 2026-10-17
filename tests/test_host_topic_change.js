// Host commands should change the priority topic, not append a competing request.
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const code=fs.readFileSync(path.join(__dirname,'..','frontend', 'client.js'),'utf8');
const a=code.indexOf('function hostTopicChange('),b=code.indexOf('async function humanMessage(){',a);
assert(a>=0&&b>a);
const ctx=vm.createContext({});
vm.runInContext(code.slice(a,b),ctx);
assert.equal(ctx.hostTopicChange('смените тему на автомобили'),'автомобили');
assert.equal(ctx.hostTopicChange('смените полностью тему на девушек'),'девушек');
assert.equal(ctx.hostTopicChange('Давайте поговорим про космос.'),'космос');
assert.equal(ctx.hostTopicChange('Это просто обычная реплика'),null);
assert.equal(ctx.hostTopicChange('смените тему на'),null);
const handler=code.slice(b,code.indexOf('// Donations are locally simulated',b));
assert(handler.includes("$('topic').value=newTopic"));
assert(handler.includes('state.history=[{agent:-1'));
assert(handler.includes('state.journal=[]'));
console.log('Host topic changes update priority and clear stale context');
