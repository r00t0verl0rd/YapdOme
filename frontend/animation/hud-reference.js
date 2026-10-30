'use strict';
/* YapdOme reference HUD — presentation only.
   The engine, authorization, turn routing, donation queue and TTS remain
   exclusively owned by the existing client.js. */
(function(){
  const $ = id => document.getElementById(id);
  let booted=false,startAt=Date.now();
  const nodes=[];
  function getDefs(){try{return typeof defs!=='undefined'&&Array.isArray(defs)?defs:[];}catch(_){return []}}
  function getState(){try{return typeof state!=='undefined'?state:null;}catch(_){return null}}
  function getSpeech(){try{return typeof speech!=='undefined'?speech:null;}catch(_){return null}}
  function stamp(seconds){
    const h=String(Math.floor(seconds/3600)).padStart(2,'0');
    const m=String(Math.floor(seconds/60)%60).padStart(2,'0');
    const s=String(seconds%60).padStart(2,'0');
    return h+':'+m+':'+s;
  }
  function boot(){
    if(booted)return;
    const root=$('liveAvatars');if(!root)return;
    const tiles=[...root.querySelectorAll('.live-tile')];
    if(tiles.length!==3)return;
    tiles.forEach((tile,i)=>{

      const lane=tile.querySelector('.wave-lane');
      if(lane){
        const f=document.createDocumentFragment();
        for(let j=0;j<27;j++){
          const bar=document.createElement('i');
          const falloff=Math.max(.2,1-Math.abs(j-13)/16);
          const wave=Math.abs(Math.sin((j+2)*(i+3)*.71));
          bar.style.setProperty('--height',(3+Math.round((4+20*wave)*falloff))+'px');
          bar.style.setProperty('--speed',(.36+(j%7)*.09)+'s');
          f.append(bar);
        }
        lane.replaceChildren(f);
      }
      nodes[i]=tile;
    });
    booted=true;
    const cards=document.querySelector('.right-column');
    if(cards)new MutationObserver(()=>queueSync()).observe(cards,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class']});
    const connection=$('connection');
    if(connection)new MutationObserver(()=>queueSync()).observe(connection,{childList:true,characterData:true,subtree:true});
    setInterval(()=>{const t=$('hudUptime');if(t)t.textContent=stamp(Math.floor((Date.now()-startAt)/1000));sync();},1000);
    sync();
  }
  let queued=false;
  function queueSync(){
    if(queued)return;
    queued=true;
    requestAnimationFrame(()=>{queued=false;sync()});
  }
  function sync(){
    if(!booted)return;
    const cast=getDefs(),s=getState(),audio=getSpeech();
    if(!cast.length||!s)return;
    for(let i=0;i<3;i++){
      const tile=nodes[i],def=cast[i];if(!tile||!def)continue;
      const current=s.current,own=!!(current&&current.agent===i);
      const speaking=audio?.audibleAgent===i;
      const thinking=!!(own&&!s.paused&&s.running&&!speaking);
      const stage= speaking?'ГОВОРИТ':s.paused?'ПАУЗА':thinking?'ДУМАЕТ':s.running?'ЖДЁТ':'ГОТОВ';
      tile.classList.toggle('is-speaking',speaking);
      const name=tile.querySelector('.tile-name'),badge=tile.querySelector('.tile-mode');
      if(name&&name.textContent!==def.name)name.textContent=def.name;
      if(badge&&badge.textContent!==stage)badge.textContent=stage;

    }
    const turn=$('hudTurns');if(turn)turn.textContent=String(s.turns||0).padStart(4,'0');
    const air=$('hudLive');
    if(air){
      const active=!!s.running&&!s.paused&&!s.stopping;
      air.classList.toggle('on-air',active);
      air.innerHTML='<span class="live-led">●</span> '+(active?'LIVE':s.paused?'PAUSED':'OFF AIR');
    }
    window.YapdOmePixel?.sync();
  }
  window.YapdOmeHud={sync,boot};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();
