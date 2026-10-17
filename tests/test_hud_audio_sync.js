'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/animation/hud-reference.js'),'utf8');
function harness(){
 const tiles=Array.from({length:3},()=>{
  const classes=new Set(),name={textContent:''},badge={textContent:''};
  return {classes,badge,classList:{toggle(key,on){if(on)classes.add(key);else classes.delete(key)}},
   querySelector:key=>key==='.tile-name'?name:key==='.tile-mode'?badge:null};
 });
 const state={running:true,paused:false,current:{agent:0,phase:'speaking',listeners:new Set()},turns:1};
 const speech={audibleAgent:null};
 let frames=0;
 const context={console,Date,state,speech,defs:[{name:'A'},{name:'B'},{name:'C'}],window:{},
  document:{readyState:'complete',getElementById:id=>id==='liveAvatars'?{querySelectorAll:()=>tiles}:null},
  setInterval(){},requestAnimationFrame(){frames++},MutationObserver:class{observe(){}}};
 vm.createContext(context);vm.runInContext(source,context);
 return {tiles,state,speech,window:context.window,sync:context.window.YapdOmeHud.sync,frames:()=>frames};
}
test('HUD follows audible output rather than generation phase, without waiting for a frame or timer',()=>{
 const h=harness();
 assert.ok(h.tiles.every(tile=>!tile.classes.has('is-speaking')),'synthesis preparation is not speech');
 h.speech.audibleAgent=0;h.sync();
 assert.equal(h.tiles[0].badge.textContent,'ГОВОРИТ');
 assert.equal(h.tiles[0].classes.has('is-speaking'),true);
 h.state.current={agent:1,phase:'speaking',listeners:new Set()};h.sync();
 assert.equal(h.tiles[0].classes.has('is-speaking'),true,'previous speaker remains animated during next-turn synthesis');
 assert.equal(h.tiles[1].classes.has('is-speaking'),false);
 assert.equal(h.tiles[1].badge.textContent,'ДУМАЕТ');
 h.speech.audibleAgent=null;h.sync();
 assert.ok(h.tiles.every(tile=>!tile.classes.has('is-speaking')));
 h.speech.audibleAgent=1;h.sync();
 assert.equal(h.tiles[1].classes.has('is-speaking'),true);
 assert.equal(h.frames(),0);
});
test('HUD immediately forwards playback and thinking changes to the optional pixel module',()=>{
 const h=harness(),seen=[];
 h.window.YapdOmePixel={sync:()=>seen.push(h.speech.audibleAgent)};
 h.speech.audibleAgent=0;h.sync();
 h.speech.audibleAgent=null;h.sync();
 assert.deepEqual(seen,[0,null]);
});
test('voice preview animates even when the live show is not running',()=>{
 const h=harness();h.state.running=false;h.state.current=null;
 h.speech.audibleAgent=2;h.sync();
 assert.equal(h.tiles[2].badge.textContent,'ГОВОРИТ');
 h.speech.audibleAgent=null;h.sync();
 assert.equal(h.tiles[2].badge.textContent,'ГОТОВ');
});
