'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../frontend/animation/hud-reference.js'),'utf8');
function harness(){
 const names=Array.from({length:3},()=>({textContent:''}));
 const tiles=Array.from({length:3},()=>{
  const classes=new Set();
  return {classes,classList:{toggle(key,on){if(on)classes.add(key);else classes.delete(key)}},
   querySelector:()=>null};
 });
 const root={
  querySelectorAll:()=>tiles,
  querySelector:selector=>{
   const match=selector.match(/data-agent-index="(\\d+)"/);
   return match?names[Number(match[1])]||null:null;
  }
 };
 const state={running:true,paused:false,current:{agent:0,phase:'speaking'},turns:1};
 const speech={audibleAgent:null};
 let frames=0;
 const context={console,Date,state,speech,defs:[{name:'A'},{name:'B'},{name:'C'}],window:{},names,
  document:{readyState:'complete',getElementById:id=>id==='liveAvatars'?root:null,querySelector:selector=>selector==='.right-column'?{}:null},
  setInterval(){},requestAnimationFrame(){frames++},MutationObserver:class{observe(){}}};
 vm.createContext(context);vm.runInContext(source,context);
 return {tiles,names,state,speech,window:context.window,sync:context.window.YapdOmeHud.sync,frames:()=>frames};
}
test('HUD keeps names on table plaques and only toggles speaking visuals',()=>{
 const h=harness();
 assert.ok(h.tiles.every(tile=>!tile.classes.has('is-speaking')),'synthesis preparation is not speech');
 h.sync();
 assert.deepEqual(h.names.map(node=>node.textContent),['A','B','C']);
 h.speech.audibleAgent=0;h.sync();
 assert.equal(h.tiles[0].classes.has('is-speaking'),true);
 h.state.current={agent:1,phase:'speaking'};h.sync();
 assert.equal(h.tiles[0].classes.has('is-speaking'),true,'previous speaker remains animated during next-turn synthesis');
 assert.equal(h.tiles[1].classes.has('is-speaking'),false);
 h.speech.audibleAgent=null;h.sync();
 assert.ok(h.tiles.every(tile=>!tile.classes.has('is-speaking')));
 h.speech.audibleAgent=1;h.sync();
 assert.equal(h.tiles[1].classes.has('is-speaking'),true);
 h.contextNames?.();
 assert.equal(h.frames(),0);
});
test('HUD immediately forwards playback and thinking changes to the optional pixel module',()=>{
 const h=harness(),seen=[];
 h.window.YapdOmePixel={sync:()=>seen.push(h.speech.audibleAgent)};
 h.speech.audibleAgent=0;h.sync();
 h.speech.audibleAgent=null;h.sync();
 assert.deepEqual(seen,[0,null]);
});
test('voice preview animates without displaying any status label',()=>{
 const h=harness();h.state.running=false;h.state.current=null;
 h.speech.audibleAgent=2;h.sync();
 assert.equal(h.tiles[2].classes.has('is-speaking'),true);
 h.speech.audibleAgent=null;h.sync();
 assert.equal(h.tiles[2].classes.has('is-speaking'),false);
 assert.deepEqual(h.names.map(node=>node.textContent),['A','B','C']);
});
