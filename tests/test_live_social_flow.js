// Lightweight deterministic test of the live two-person floor selector.
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'..','web','app.js'),'utf8');
const a=src.indexOf('function resetSocialFocus(){'),b=src.indexOf('async function claimNext(){',a);
assert(a>=0&&b>a);
const fields={showMode:{value:'live'}};
const state={running:true,paused:false,turns:7,
 social:{pair:null,returnContext:null,lastEnd:0,lastPair:''},
 history:[{agent:0,text:'Одна идея'},{agent:1,text:'Возражение'},
          {agent:2,text:'Важный вопрос?'},{agent:1,text:'Интересный ответ'}],
 core:{route_reason:'rotation',next_agent:0},
 activeDonation:null,donationQueue:[]};
const ctx=vm.createContext({state,$:key=>fields[key],renderCards:()=>{}});
vm.runInContext(src.slice(a,b),ctx);
const chosen=ctx.socialRouteHint();
assert.equal(chosen,2,'one partner should answer the other');
assert.equal(state.social.pair.listener,0,'third agent listens');
assert.equal(ctx.socialTurnContext(2).kind,'duo');
assert.equal(ctx.socialTurnContext(0),null,'listener has no forced speech');
state.turns=state.social.pair.until;
state.core.route_reason='rotation';
assert.equal(ctx.socialRouteHint(),0,'listener returns when duet finishes');
assert.equal(ctx.socialTurnContext(0).kind,'rejoin');
assert.equal(ctx.socialTurnContext(1).kind,'invite','pair member invites third if C token defers handoff');
state.social.returnContext=null;
state.turns+=1;
assert.equal(ctx.socialRouteHint(),null,'cooldown prevents endless two-person shows');
state.social.pair={pair:[1,2],listener:0,until:100};
state.core.route_reason='token';state.core.next_agent=0;
assert.equal(ctx.socialRouteHint(),null,'explicit invitation to listener overrides duet');
assert.equal(state.social.returnContext.listener,0);
state.social.pair={pair:[1,2],listener:0,until:100};
state.activeDonation={};
assert.equal(ctx.socialRouteHint(),null,'donation takes precedence');
assert.equal(state.social.pair,null);
state.activeDonation=null;fields.showMode.value='science';
assert.equal(ctx.socialRouteHint(),null,'science mode remains a three-agent discussion');
// Keep the v0.2 host controls while testing the social routing extension.
assert(src.includes("function hostTopicChange("));
assert(src.includes("social_focus:c.socialFocus"));
const parserStart=src.indexOf('function hostTopicChange('),parserEnd=src.indexOf('async function humanMessage()',parserStart);
const commands=vm.createContext({});
vm.runInContext(src.slice(parserStart,parserEnd),commands);
assert.equal(commands.hostTopicChange('поговорите о девушках'),'девушках');
assert.equal(commands.hostTopicChange('смените тему'),'');
assert.equal(commands.hostTopicChange('смените тему на автомобили'),'автомобили');
assert.equal(commands.hostTopicChange('Это просто шутка'),null);
console.log('PASS: duo, listener rejoin, priority exceptions and hot edits');
