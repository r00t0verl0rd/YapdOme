'use strict';
/* YapdOme reference HUD — presentation only.
   The C core, authorization, turn routing, donation queue and TTS remain
   exclusively owned by the existing client.js. */
(function(){
  const $ = id => document.getElementById(id);
  const portraits = [
    '<svg viewBox="0 0 200 240" role="img" aria-label="Киберпанк-портрет с шипастой причёской" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="h0" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#41ffb4" stop-opacity=".27"/><stop offset="1" stop-color="#00251d"/></linearGradient><pattern id="p0" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M0 0H8M0 0V8" stroke="#2affe2" stroke-opacity=".14" stroke-width=".5"/></pattern></defs><rect width="200" height="240" fill="#041715"/><rect width="200" height="240" fill="url(#p0)"/><g fill="none" stroke="#48ffb2" stroke-opacity=".3" stroke-width="1"><path d="M5 43h50m-38 6h28M150 72h40M160 79h30M8 191h54M150 201h36"/><path d="M25 10v45m4-45v16M182 107v24"/></g><path d="M0 240L14 189 53 168 78 164 88 144 135 151 150 174 180 190 200 240Z" fill="#071d1c" stroke="#38efb2" stroke-width="2"/><path d="M20 237L47 190 80 178 99 211 119 178 161 190 184 239M48 194l19 39m83-36-23 34" stroke="#37dca6" stroke-width="2" fill="none"/><path d="M72 99Q64 108 71 137L89 165 121 169 142 144 145 107 125 77 84 80Z" fill="url(#h0)" stroke="#59ffc9" stroke-width="2"/><path d="M65 117L50 93 66 86 45 76 68 73 53 59 81 67 69 40 92 54 91 29 108 49 126 27 132 53 153 40 146 67 168 58 156 82 161 92 148 108 137 94 121 81 91 93Z" fill="#081c19" stroke="#70ffd1" stroke-width="2.7"/><g fill="none" stroke="#55ffc0" stroke-width="1.5"><path d="M59 78l22-7 12-18m-29 42 24-14m3-27 9 17m27-12 17-11m-21 27 24 13M82 99l-7 20m66-21 6 19"/></g><path d="M70 115Q91 109 104 114L118 113Q130 109 145 113l-3 20-31 2-4-7-6 6-28-2Z" fill="#010d12" stroke="#69ffd0" stroke-width="2.5"/><path d="M75 118l25 6m17-6 22 2" stroke="#4fffc2" stroke-opacity=".45"/><path d="M113 127l-5 17 10 1m-25 9q13 7 29 1" stroke="#47e3ab" stroke-width="1.6" fill="none"/><path d="M87 164l10 15 19-1 12-14" stroke="#e9ffb0" stroke-width="2" fill="none"/><circle cx="151" cy="137" r="3.5" fill="#52ffc0"/><path d="M12 12h20m-20 0v20m156 0V12h20M12 210v20h20M168 230h20v-20" stroke="#3dc8a3" stroke-width="1.2" fill="none"/></svg>',
    '<svg viewBox="0 0 200 240" role="img" aria-label="Киберпанк-портрет в капюшоне" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="h1" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#27edff" stop-opacity=".28"/><stop offset="1" stop-color="#01161e"/></linearGradient><pattern id="p1" width="9" height="9" patternUnits="userSpaceOnUse"><path d="M9 0H0V9" stroke="#19bbd9" stroke-width=".6" stroke-opacity=".21" fill="none"/></pattern></defs><rect width="200" height="240" fill="#02121a"/><rect width="200" height="240" fill="url(#p1)"/><g fill="none" stroke="#37c8e4" stroke-opacity=".44"><path d="M3 80h29m137 17h28M16 155h23M161 162h32M14 45h30M167 46h22"/><path d="M23 41v45M175 130v41"/></g><path d="M0 240L14 187 45 150 52 76 74 45 98 33 123 40 152 65 168 132 181 185 200 240Z" fill="#031f28" stroke="#33e3fe" stroke-width="3"/><path d="M31 224Q32 173 53 148L48 89 68 58 98 40 130 60 151 92 148 152Q169 178 174 224" stroke="#32efff" stroke-opacity=".7" fill="none" stroke-width="2"/><path d="M52 141Q63 89 96 74 130 80 143 137L133 171 95 190 66 169Z" fill="url(#h1)" stroke="#19bedd" stroke-width="2"/><path d="M51 142Q47 95 71 71L98 50 131 75Q157 106 146 143L135 119 123 94 100 80 75 92 61 121Z" fill="#031721" stroke="#2deeff" stroke-width="3"/><path d="M70 129l18-7 9 4 12-4 21 6M72 132l17 3 10-4 11 4 17-3" fill="none" stroke="#6ef6ff" stroke-width="2"/><circle cx="83" cy="130" r="3" fill="#a9faff"/><circle cx="116" cy="130" r="3" fill="#a9faff"/><path d="M97 134l-4 15 10 1m-19 13 24 1 7-4" fill="none" stroke="#37dcf0" stroke-width="1.6"/><path d="M55 156L75 183 99 197 127 183 147 159l-10 44-36 26-36-24Z" fill="#06222d" stroke="#44dfff" stroke-width="2"/><path d="M79 186l-14 26m68-27 11 27M44 193l38 38M160 193l-38 38" stroke="#49e7ff" stroke-width="1.5" fill="none"/><path d="M11 10h19M11 10v20M171 10h19v20M11 210v20h19M170 230h20v-20" stroke="#3fd8eb" stroke-width="1.2" fill="none"/></svg>',
    '<svg viewBox="0 0 200 240" role="img" aria-label="Киберпанк-портрет девушки с косичками" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="h2" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#ffe66d" stop-opacity=".32"/><stop offset="1" stop-color="#025b37" stop-opacity=".35"/></linearGradient><pattern id="p2" width="7" height="7" patternUnits="userSpaceOnUse"><path d="M0 0H7V7" stroke="#bfe959" stroke-opacity=".12" stroke-width=".5" fill="none"/></pattern></defs><rect width="200" height="240" fill="#0a1810"/><rect width="200" height="240" fill="url(#p2)"/><g stroke="#e2e956" stroke-opacity=".44" fill="none"><path d="M12 37h40m107 13h26M8 163h27m136 27h23"/></g><path d="M0 240L33 197 59 181 75 176 81 150 129 148 141 178 179 197 200 240Z" fill="#073223" stroke="#d7e950" stroke-width="2"/><path d="M59 98Q51 62 77 46 101 30 128 45 151 54 156 92L149 161 134 195 113 211 68 183 52 144Z" fill="#062519" stroke="#c5eb67" stroke-width="3"/><g fill="none" stroke="#bfe973" stroke-width="4"><path d="M69 47Q45 77 56 120T39 178M78 42Q59 77 69 113T53 197M128 46Q157 67 148 125T176 194M137 51Q160 83 154 137T181 202M85 43Q73 68 75 91M117 39Q139 72 134 97"/></g><path d="M72 84Q90 66 127 80L138 101 134 147 116 170 87 168 67 146 65 103Z" fill="url(#h2)" stroke="#b1f286" stroke-width="2"/><path d="M77 115q12-7 21-1m15 0q10-7 19-1" fill="none" stroke="#e5f7ac" stroke-width="2"/><path d="M78 119q13 8 22-1m14 0q10 8 19-1" fill="none" stroke="#ffea87" stroke-width="1.8"/><circle cx="90" cy="120" r="2.5" fill="#f5ffaa"/><circle cx="122" cy="119" r="2.5" fill="#f5ffaa"/><path d="M108 119l-4 22 7 2m-20 11q14-6 29-2-10 14-28 3" fill="none" stroke="#f7db67" stroke-width="1.8"/><path d="M73 144q-9 0-10 12t11 8m60-21q11 0 10 13t-11 8" fill="none" stroke="#dff789" stroke-width="2"/><circle cx="68" cy="162" r="4" fill="none" stroke="#fff681" stroke-width="2"/><circle cx="139" cy="162" r="4" fill="none" stroke="#fff681" stroke-width="2"/><path d="M82 174l17 21 21-23m-22 23-1 28" stroke="#edff8f" stroke-width="2" fill="none"/><path d="M13 11h19M13 11v19M168 11h19v19M13 210v19h19M168 230h19v-20" stroke="#d8d858" stroke-width="1.3" fill="none"/></svg>'
  ];
  let booted=false,startAt=Date.now(),clockTimer=null;
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
      const picture=tile.querySelector('.hud-portrait');
      if(picture)picture.innerHTML=portraits[i];
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
    const cards=$('cards'),run=$('runstate'),audio=$('audioLane');
    if(cards)new MutationObserver(()=>queueSync()).observe(cards,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class']});
    for(const element of [run,audio,$('connection')])if(element)new MutationObserver(()=>queueSync()).observe(element,{childList:true,characterData:true,subtree:true});
    clockTimer=setInterval(()=>{const t=$('hudUptime');if(t)t.textContent=stamp(Math.floor((Date.now()-startAt)/1000));sync();},1000);
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
      const listening=!!(!speaking&&s.running&&!s.paused&&!own&&current&&current.listeners&&current.listeners.has(i));
      const stage= speaking?'ГОВОРИТ':s.paused?'ПАУЗА':thinking?'ДУМАЕТ':listening?'СЛУШАЕТ':s.running?'ЖДЁТ':'ГОТОВ';
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
