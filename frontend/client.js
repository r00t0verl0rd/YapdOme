'use strict';
// TRIAD 0.2.0: pure-Python engine; donor FIFO never preempts the audible turn.
const $ = id => document.getElementById(id);
// Secure random request ID without relying on crypto.randomUUID being present.
function requestID(){
 const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);
 bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
 const h=[...bytes].map(x=>x.toString(16).padStart(2,'0')).join('');
 return h.slice(0,8)+'-'+h.slice(8,12)+'-'+h.slice(12,16)+'-'+h.slice(16,20)+'-'+h.slice(20);
}
// Editable sample cast, not hard-coded debate positions. Existing saved characters win.
const defs = [
  {name:'Норман',color:'#48eafb',description:'Любит рассказывать истории из жизни, слегка хвастается и часто сам попадает в нелепое положение. Отшучивается, если его поддели; способен искренне признать ошибку.',voiceURI:''},
  {name:'Глитч',color:'#ffb45e',description:'Быстрый на язык, замечает нелепости и любит добродушно подкалывать друзей. Иногда спорит из азарта, но умеет неожиданно поддержать собеседника.',voiceURI:''},
  {name:'Джесси',color:'#ed68f8',description:'Остроумная, наблюдательная, прямолинейная. Не любит напускную серьёзность, задаёт неудобные вопросы и иногда выдаёт неожиданный поворот без длинных объяснений.',voiceURI:''}
];
const SCIENCE_PHASES=['knowledge','gaps','hypothesis','math','experiment'];
const PHASE_LABEL={knowledge:'01 · КАРТА ЗНАНИЙ',gaps:'02 · ПРОБЕЛЫ',hypothesis:'03 · ГИПОТЕЗА',math:'04 · МАТЕМАТИКА',experiment:'05 · ЭКСПЕРИМЕНТ'};
const currentPhase=turns=>SCIENCE_PHASES[Math.floor(Math.max(0,Number(turns)||0)/3)%SCIENCE_PHASES.length];
function updateScienceUI(){
 const node=$('scienceInfo');if(!node)return;
 const active=$('showMode').value==='science';
 node.hidden=!active;
 if(active)node.textContent='TRIAD SCIENCE · '+PHASE_LABEL[currentPhase(state.turns)]+
  ' · теоретик / критик / экспериментатор · заметок: '+state.journal.length+
  ' · рабочие гипотезы (не проверены)';
}
// The turn contract must never be spoken aloud: strip control markers from speech.
function stripDirectives(raw){
  const text=String(raw||'')
    .replace(/\[\[\s*(?:TO|RE|CLAIM)\s*:[^\]]*\]\]/gi,' ')
    .replace(/\[\s*(?:TO|RE|CLAIM)\s*:[^\]]*\]/gi,' ')
    .replace(/\[\[\s*(?:PASS|WAIT_USER|CONT)\s*\]\]/gi,' ')
    .replace(/\[\s*(?:PASS|WAIT_USER|CONT)\s*\]/gi,' ')
    .replace(/\[\[[^\]]*$/,'')
    .replace(/\s+/g,' ')
    .replace(/\s+([.,;:!?…])/g,'$1')
    .trim();
  // A turn made only of markers must never leave orphan punctuation to be spoken.
  return /^[.,;:!?…\-–—\s]*$/.test(text)?'':text;
}
const state = {archivedLines:[],connected:false,recoverable:false,provider:'chatgpt',deepseekConnected:false,running:false,paused:false,stopping:false,starting:false,epoch:0,turns:0,current:null,history:[],journal:[],timer:null,claimPending:null,core:null,donationQueue:[],activeDonation:null,donationRouting:false,lastDonationName:'',lastAudibleAt:Date.now(),lastIdleNotice:0,
  directorPlan:null,directorRequest:null,directorRouted:false,
  pipelineReady:false,audibleTurn:null,
  social:{pair:null,returnContext:null,lastEnd:0,lastPair:"",memory:[[],[],[]]}};
let voices=[];
const haveSpeech = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
const SpeechInput = window.SpeechRecognition || window.webkitSpeechRecognition;
let micRecognition=null;
// Only the audible layer is normalized. Keep original transcript and agent context untouched.
// Text streaming sometimes contains literal \" and escaped newlines; the speech engine
// can read the backslash aloud as "бэк слеш". Remove these before synthesizing.
function ttsText(raw){
 return String(raw||'').replace(/\\[nrt]/g,' ').replace(/\\/g,'')
   .replace(/[«»“”„"]/g,'').replace(/[*_`#]+/g,' ')
   .replace(/\s+/g,' ').trim();
}
const kokoroState={ready:false,installation:{}};
const kokoroRuState={ready:false,installation:{}};
const piperState={ready:false,installation:{}},sileroState={ready:false,installation:{}};
const qwen3State={ready:false,installation:{}};
const piperSpeakers=[['dmitri','Дмитрий'],['irina','Ирина'],['ruslan','Руслан'],['denis','Денис']];
const sileroSpeakers=[['aidar','Айдар'],['baya','Бая'],['kseniya','Ксения'],['xenia','Xenia'],['eugene','Евгений']];
const kokoroRuSpeakers=[['sveta','Света'],['masha','Маша'],['dima','Дима']];
const kokoroSpeakers=['af_heart','af_bella','af_sarah','af_nicole','af_sky','am_adam','am_michael','am_echo','am_puck','bf_emma','bf_isabella','bm_george','bm_lewis'];
const QWEN3_FALLBACK_SPEAKERS=['Ryan','Aiden','Serena','Vivian','Uncle_Fu','Ono_Anna','Sohee','Eric','Dylan'];
let qwen3BuiltinSpeakers={lite:[...QWEN3_FALLBACK_SPEAKERS],pro:[...QWEN3_FALLBACK_SPEAKERS]};
// Реальный список спикеров приходит из config.json установленной модели.
const qwen3SpeakerList=()=>{const list=qwen3BuiltinSpeakers[qwen3Size];return Array.isArray(list)&&list.length?list:QWEN3_FALLBACK_SPEAKERS;};
// Сохранённый голос, которого нет в модели, заменяется корректным умолчанием.
const qwen3VoiceFor=(agent,saved)=>{const list=qwen3SpeakerList();if(saved&&list.includes(saved))return saved;return list[agent%list.length]||list[0];};
let qwen3Voices=[];let qwen3Size='lite';let kokoroModel='ru';
const isRussian=text=>/[а-яё]/i.test(text);
const kokoroSelected=()=>$('ttsBackend').value==='kokoro' && kokoroModel==='en' && kokoroState.ready;
const kokoroRuSelected=()=>$('ttsBackend').value==='kokoro' && kokoroModel==='ru' && kokoroRuState.ready;
const piperSelected=()=>$('ttsBackend').value==='piper'&&piperState.ready;
const sileroSelected=()=>$('ttsBackend').value==='silero'&&sileroState.ready;
const qwen3Selected=()=>$('ttsBackend').value==='qwen3-tts'&&qwen3State.ready;
const audioAvailable=()=>kokoroSelected()||kokoroRuSelected()||piperSelected()||sileroSelected()||qwen3Selected()||haveSpeech;
function languageFor(text){
 const ru=(text.match(/[а-яё]/gi)||[]).length;
 const en=(text.match(/[a-z]/gi)||[]).length;
 return ru>=en?'Russian':'English';
}
const speech = {
 queue:[],playing:false,generation:0,waiters:[],controller:null,ctx:null,nodes:new Set(),doneAudio:null,
 serial:0,metricsEnabled:false,metrics:[],startTimers:new Set(),
 activeSynthesis:0,prefetch:null,audibleAgent:null,audibleEntry:null,audioMeter:null,
 setAudibleAgent(agent){
   if(this.audibleAgent===agent)return;
   this.audibleAgent=agent;
   if(agent===null)this.audibleEntry=null;
   if(typeof renderCards==='function')renderCards();
   if(window.YapdOmeHud?.sync)window.YapdOmeHud.sync();
   else window.YapdOmePixel?.sync();
 },
 // A single sentence of audio is prepared while the previous one is audible.
 prefetchPlan(entry){
   const backend=entry.config.backend,config=entry.config,text=entry.text;
   // Keep one bounded look-ahead for every local WAV backend. Longer replies
   // are synthesized in endpoint-sized chunks by wavFor(), then joined once.
   const budget=950;
   if(!text||text.length>budget)return null;
   if(backend==='kokoro-ru'&&isRussian(text))
     return {url:'/api/kokoro-ru/speak',limit:450,payload:{text,
       voice:config.kokoroRuVoice||['sveta','dima','masha'][entry.agent],
       speed:Math.max(.75,Math.min(1.5,config.speed||1))}};
   if(backend==='piper'||backend==='silero'||(backend==='kokoro'&&!isRussian(text))){
     const voice=backend==='piper'?(config.piperVoice||piperSpeakers[entry.agent][0]):
       backend==='silero'?(config.sileroVoice||sileroSpeakers[entry.agent][0]):
       (config.kokoroVoice||'af_heart');
     return {url:'/api/voice/'+backend+'/speak',limit:450,
       payload:{text,voice,speed:config.speed||1}};
   }
   if(backend==='qwen3-tts'){
     return {url:'/api/voice/qwen3-tts/speak',limit:600,
       payload:{text,voice:qwen3VoiceFor(entry.agent, config.qwen3Voice),
         speed:config.speed||1,size:qwen3Size}};
   }
   return null;
 },
 maybePrefetch(){
   if(!this.playing||this.prefetch||this.activeSynthesis||!this.ctx||!this.queue.length)return;
   const entry=this.queue[0],spec=this.prefetchPlan(entry);
   if(!spec)return;
   const gen=this.generation,controller=new AbortController();
   const job={entry,controller,buffer:null,error:null,promise:null};
   this.prefetch=job;this.activeSynthesis++;
   this.metric(entry,'prefetch-started');
   job.promise=(async()=>{
     try{
       const buffer=await this.wavFor(spec.url,spec.payload,spec.limit,controller,gen);
       if(this.prefetch===job&&gen===this.generation&&!controller.signal.aborted){
         job.buffer=buffer;this.metric(entry,'prefetch-ready',{duration:buffer.duration});
       }
     }catch(err){job.error=err;this.metric(entry,'prefetch-failed');}
     finally{
       this.activeSynthesis--;
       if(this.prefetch!==job)this.maybePrefetch();
     }
   })();
 },
 async obtainWav(entry,gen,url,payload,limit,controller){
   const job=this.prefetch?.entry===entry?this.prefetch:null;
   if(job){
     controller.signal.addEventListener('abort',()=>job.controller.abort(),{once:true});
     await job.promise;
     if(this.prefetch===job)this.prefetch=null;
     if(controller.signal.aborted||gen!==this.generation)throw Error('Отменено');
     if(job.buffer)return job.buffer;
     // A failed prefetch must not doom the line: fall through to a fresh
     // direct synthesis below instead of dropping it immediately.
   }
   this.activeSynthesis++;
   try{return await this.wavFor(url,payload,limit,controller,gen);}
   finally{this.activeSynthesis--;this.maybePrefetch();}
 },
 retryable(err){
   if(!err||err.name==='AbortError')return false;
   const status=err.status;
   if(Number.isInteger(status))return status===408||status===429||status>=500;
   const msg=String(err.message||err).toLowerCase();
   return /(failed to fetch|networkerror|timed?\s?out|timeout|\b50[0-9]\b|\b408\b|\b429\b|connection|reset)/.test(msg);
 },
 async obtainWavRetry(entry,gen,url,payload,limit,controller,attempts=2){
   let lastErr;
   for(let attempt=0;attempt<attempts;attempt++){
     if(controller.signal.aborted||gen!==this.generation)throw Error('Отменено');
     try{
       return await this.obtainWav(entry,gen,url,payload,limit,controller);
     }catch(err){
       if(controller.signal.aborted||gen!==this.generation)throw err;
       lastErr=err;
       if(attempt>=attempts-1||!this.retryable(err))throw err;
       await new Promise(resolve=>setTimeout(resolve,400*(attempt+1)));
     }
   }
   throw lastErr;
 },
 atPlayhead(entry,gen,when){
   if(gen!==this.generation||entry.started||entry.startTimer)return;
   if(this.ctx.state==='running'&&this.ctx.currentTime>=when){this.startEntry(entry,gen);return;}
   const timer=setTimeout(()=>{this.startTimers.delete(timer);entry.startTimer=null;this.atPlayhead(entry,gen,when);},Math.max(10,(when-this.ctx.currentTime)*1000));
   entry.startTimer=timer;this.startTimers.add(timer);
 },
 snapshot(agent){
   const backend=piperSelected()?'piper':sileroSelected()?'silero':kokoroRuSelected()?'kokoro-ru':kokoroSelected()?'kokoro':qwen3Selected()?'qwen3-tts':'browser';
   const d=defs[agent];
   // Old saved volume/pitch/speed cannot silently mute the output.
   return Object.freeze({name:d.name,backend,
     speed:Number($('rate').value)||1,browserVoice:voices.find(v=>v.voiceURI===d.voiceURI),
     kokoroVoice:d.kokoroVoice,
     kokoroRuVoice:d.kokoroRuVoice,piperVoice:d.piperVoice,sileroVoice:d.sileroVoice,
     qwen3Voice:d.qwen3Voice});
 },
 metric(entry,event,extra={}){
   if(!this.metricsEnabled)return;
   this.metrics.push({id:entry.id,backend:entry.config.backend,event,at:typeof performance!=='undefined'?performance.now():Date.now(),...extra});
   if(this.metrics.length>256)this.metrics.splice(0,this.metrics.length-256);
 },
 // WebAudio start is a playhead estimate, not a microphone measurement.
 startEntry(entry,gen){
   if(gen!==this.generation||entry.started)return;
   this.audibleEntry=entry;
   entry.started=true;state.lastAudibleAt=Date.now();this.metric(entry,'started');
      if(entry.startTimer){clearTimeout(entry.startTimer);this.startTimers.delete(entry.startTimer);entry.startTimer=null;}
   const lane=$('audioLane');if(lane)lane.textContent='♪ ОЗВУЧИВАЕТ · '+entry.config.name;
   if(entry.onStart)entry.onStart(entry.raw);
   this.setAudibleAgent(entry.agent);
 },
 unlock(){

   const C=window.AudioContext||window.webkitAudioContext;
   if(!C)return;
   try{if(!this.ctx)this.ctx=new C();if(this.ctx.state==='suspended')this.ctx.resume().catch(()=>{});}catch(_){}
 },
 async audioReady(){
   // Safari/macOS may suspend the audio context again while local TTS is generating.
   this.unlock();
   if(!this.ctx)throw Error('Web Audio недоступен');
   if(this.ctx.state==='suspended')await this.ctx.resume();
   if(this.ctx.state!=='running')throw Error('Аудиовыход браузера заблокирован. Нажми «ТЕСТ ЗВУКА».');
 },
 audioLevel(buffer){
   // Ignore silent 20 ms windows: pauses must not make a voice louder.
   let energy=0,active=0,peak=0;
   const window=Math.max(1,Math.round(buffer.sampleRate*.02));
   for(let ch=0;ch<buffer.numberOfChannels;ch++){
     const data=buffer.getChannelData(ch);
     for(let start=0;start<data.length;start+=window){
       const end=Math.min(data.length,start+window);let sum=0;
       for(let i=start;i<end;i++){const v=Number.isFinite(data[i])?data[i]:0;sum+=v*v;peak=Math.max(peak,Math.abs(v));}
       if(sum/(end-start)>1e-5){energy+=sum;active+=end-start;}
     }
   }
   return {peak,rms:active?Math.sqrt(energy/active):0};
 },
 outputNode(){
   if(this.audioMeter?.context===this.ctx)return this.audioMeter;
   if(typeof this.ctx.createAnalyser!=='function')return this.ctx.destination;
   try{
     const meter=this.ctx.createAnalyser();meter.fftSize=512;meter.smoothingTimeConstant=0;
     meter.connect(this.ctx.destination);this.audioMeter=meter;return meter;
   }catch(_){return this.ctx.destination;}
 },
 connectOutput(source,config,entry=null){
   const gain=this.ctx.createGain?.(),output=this.outputNode();
   if(gain){
     const {peak,rms}=this.audioLevel(source.buffer);
     // Bounded active-RMS matching, not peak normalization (which leaves quiet voices quiet).
     let level=rms?Math.max(.1,Math.min(4,.12/rms)):1;
     if(entry){
       // Keep streaming packets from pumping on every syllable or amplifying silence.
       const blend=1-Math.exp(-source.buffer.duration/.5);
       level=rms?(entry.audioGain==null?level:entry.audioGain+(level-entry.audioGain)*blend):(entry.audioGain??1);
       entry.audioGain=level;
     }
     level=Math.min(level,peak>0?.95/peak:Infinity);
     gain.gain.value=level;
     source.connect(gain);gain.connect(output);source._voiceGain=gain;
   }else source.connect(output);
 },
 stop(){
   this.generation++;
   if(this.prefetch){this.prefetch.controller.abort();this.prefetch=null;}
   this.queue.length=0;this.playing=false;
   for(const timer of this.startTimers)clearTimeout(timer);this.startTimers.clear();
   if(this.controller){this.controller.abort();this.controller=null;}
   for(const source of this.nodes){try{source.stop()}catch(_){}try{source.disconnect()}catch(_){}try{source._voiceGain?.disconnect()}catch(_){}}
   this.nodes.clear();
   if(this.doneAudio){const done=this.doneAudio;this.doneAudio=null;done();}
   if(haveSpeech){try{window.speechSynthesis.cancel()}catch(_){}}
   this.setAudibleAgent(null);
   this.settle();
 },
 settle(){if(!this.playing&&!this.queue.length){
   const lane=$('audioLane');if(lane)lane.textContent='◌ АУДИО СВОБОДНО';
   const w=this.waiters.splice(0);w.forEach(resolve=>resolve());
 }},
 push(agent,words,onStart=null,onFinish=null,config=this.snapshot(agent)){
   const rest=String(words||'').trim();
   if(!ttsText(rest)||!$('voiceEnabled').checked)return;
   const entry={id:++this.serial,agent,text:ttsText(rest),raw:rest,config,onStart,onFinish,started:false};
   this.metric(entry,'queued',{characters:entry.text.length});
   this.queue.push(entry);
   this.pump();
   this.maybePrefetch();
 },
 pump(){
   if(this.playing)return;
   this.setAudibleAgent(null);
   if(!this.queue.length){this.settle();return;}

   const entry=this.queue.shift(),gen=this.generation;
   this.playing=true;state.lastAudibleAt=Date.now();
   const backend=entry.config.backend;
   if(backend==='piper'||backend==='silero'){this.playKokoro(entry,gen);return;}
   if(backend==='kokoro-ru'&&isRussian(entry.text)){this.playKokoroRu(entry,gen);return;}
   if(backend==='kokoro'&&!isRussian(entry.text)){this.playKokoro(entry,gen);return;}
   if(backend==='qwen3-tts'){this.playKokoro(entry,gen);return;}

   this.playBrowser(entry,gen);
 },
 playBrowser(entry,gen){
   entry.audioMode='browser';
   if(!haveSpeech){this.playing=false;this.pump();return;}
   const u=new SpeechSynthesisUtterance(entry.text);
   u.lang=languageFor(entry.text)==='Russian'?'ru-RU':'en-US';
   u.rate=entry.config.speed||1;u.pitch=1;u.volume=1;
   const voice=entry.config.browserVoice;
   if(voice){u.voice=voice;u.lang=voice.lang||u.lang}
   let settled=false;
   const finish=played=>{if(settled)return;settled=true;clearTimeout(fallback);this.startTimers.delete(fallback);if(gen!==this.generation)return;
     if(played){this.metric(entry,'drained');if(entry.started&&entry.onFinish)entry.onFinish(entry.raw);}
     this.playing=false;state.lastAudibleAt=Date.now();this.pump()};
   u.onstart=()=>this.startEntry(entry,gen);
   u.onend=()=>finish(true);
   u.onerror=error=>{
     if(gen===this.generation){
       this.metric(entry,'failed',{reason:'browser'});
       system('Системный голос: ошибка '+String(error?.error||'озвучивания')+'. Реплика пропущена.');
     }
     finish(false);
   };
   const fallback=setTimeout(()=>{
     if(gen!==this.generation)return;
     system('Системный голос не завершил реплику. Проверь выбранный голос macOS.');
     this.metric(entry,'failed',{reason:'browser-timeout'});
     try{window.speechSynthesis.cancel()}catch(_){}
     finish(false);
   },Math.max(30000,Math.min(900000,entry.text.length*260)));
   this.startTimers.add(fallback);
   try{window.speechSynthesis.speak(u)}catch(_){finish(false)}
 },
 async readWav(response,controller,gen){
   // Enforce the transport budget before arrayBuffer/decode allocations. The
   // decoded-sample budget in wavFor alone cannot bound a chunked HTTP body.
   const maxBytes=32*1024*1024;
   if(Number(response.headers?.get('Content-Length'))>maxBytes){
     try{await response.body?.cancel()}catch(_){}
     throw Error('WAV превышает лимит 32 МиБ');
   }
   if(!response.body)throw Error('Пустой WAV');
   const reader=response.body.getReader(),chunks=[];let size=0;
   const cancel=()=>{Promise.resolve(reader.cancel()).catch(()=>{});};
   controller.signal.addEventListener('abort',cancel,{once:true});
   try{
     while(true){
       if(controller.signal.aborted||gen!==this.generation)throw Error('Отменено');
       const {done,value}=await reader.read();
       if(controller.signal.aborted||gen!==this.generation)throw Error('Отменено');
       if(done)break;
       if(value.byteLength>maxBytes-size)throw Error('WAV превышает лимит 32 МиБ');
       if(value.byteLength){chunks.push(value);size+=value.byteLength;}
     }
     const bytes=new Uint8Array(size);let offset=0;
     for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
     return bytes.buffer;
   }finally{
     controller.signal.removeEventListener('abort',cancel);
     try{await reader.cancel()}catch(_){}
     try{reader.releaseLock()}catch(_){}
   }
 },

 *textChunks(rest,limit){
   while(rest){
     let cut=Math.min(rest.length,limit);
     if(cut<rest.length){
       const boundary=rest.slice(0,cut).match(/^.*[.!?…;:,]\s/s);
       const space=rest.lastIndexOf(' ',cut);
       if(boundary)cut=boundary[0].length;else if(space>0)cut=space;
       if(/[\uD800-\uDBFF]/.test(rest[cut-1]))cut--;
     }
     const text=rest.slice(0,cut);rest=rest.slice(cut).trimStart();
     yield {text,last:!rest};
   }
 },
 async wavFor(endpoint,payload,limit,controller,gen){
   // Backend length limits are transport details, never separate audible turns.
   // Preassemble oversized WAV turns to avoid network/decode gaps between chunks.
   const buffers=[];let frames=0;
   for(const {text} of this.textChunks(payload.text,limit)){
     if(controller.signal.aborted||gen!==this.generation)throw Error('Отменено');
     const response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},
       signal:controller.signal,body:JSON.stringify({...payload,text})});
     if(!response.ok){
       const info=await response.json().catch(()=>({}));
       const err=new Error(info.error||('HTTP '+response.status));
       err.status=response.status;
       throw err;
     }
     const binary=await this.readWav(response,controller,gen);
     if(controller.signal.aborted||gen!==this.generation)throw Error('Отменено');
     const buffer=await this.ctx.decodeAudioData(binary);
     if(controller.signal.aborted||gen!==this.generation)throw Error('Отменено');
     if(!buffer.length)throw Error('Пустой WAV');
     if(buffers.length&&(buffer.sampleRate!==buffers[0].sampleRate||buffer.numberOfChannels!==buffers[0].numberOfChannels))throw Error('Формат WAV изменился внутри реплики');
     buffers.push(buffer);frames+=buffer.length;
     if(frames*buffer.numberOfChannels>24000*600)throw Error('Реплика превышает бюджет аудиопамяти');
   }
   if(buffers.length===1)return buffers[0];
   const joined=this.ctx.createBuffer(buffers[0].numberOfChannels,frames,buffers[0].sampleRate);
   let offset=0;
   for(const buffer of buffers){
     for(let ch=0;ch<buffer.numberOfChannels;ch++)joined.copyToChannel(buffer.getChannelData(ch),ch,offset);
     offset+=buffer.length;
   }
   return joined;
 },
 async playKokoroRu(entry,gen){
   const controller=new AbortController();this.controller=controller;let fallback=false;
   try{
     this.unlock();
     if(!this.ctx)throw Error('WebAudio недоступен');
     if(this.ctx.state==='suspended')await this.ctx.resume();
     const buffer=await this.obtainWavRetry(entry,gen,'/api/kokoro-ru/speak',{
       text:entry.text,voice:entry.config.kokoroRuVoice||['sveta','dima','masha'][entry.agent],
       speed:Math.max(.75,Math.min(1.5,entry.config.speed||1))},450,controller);
     if(controller.signal.aborted||gen!==this.generation)return;
     await this.audioReady();
     const source=this.ctx.createBufferSource();source.buffer=buffer;
     source.playbackRate.value=1;
     this.connectOutput(source,entry.config);this.nodes.add(source);
     await new Promise(resolve=>{
       source.onended=()=>{this.nodes.delete(source);source.disconnect();source._voiceGain?.disconnect();resolve()};
       controller.signal.addEventListener('abort',resolve,{once:true});
       source.start();this.atPlayhead(entry,gen,this.ctx.currentTime);this.maybePrefetch();
     });
     if(!controller.signal.aborted&&gen===this.generation){this.metric(entry,"drained");if(entry.onFinish)entry.onFinish(entry.raw);}
   }catch(err){
     if(!controller.signal.aborted&&gen===this.generation){system('Kokoro RU: '+err.message);fallback=haveSpeech&&!entry.started;}
   }finally{
     if(gen===this.generation){this.controller=null;if(fallback)this.playBrowser(entry,gen);
       else{this.playing=false;this.pump();}}
   }
 },
 async playKokoro(entry,gen){
   const controller=new AbortController();this.controller=controller;
   let fallback=false;
   const backend=entry.config.backend;
   try{
     this.unlock();
     if(!this.ctx)throw Error('WebAudio недоступен');
     if(this.ctx.state==='suspended')await this.ctx.resume();

      const addon=backend==='piper'||backend==='silero'||backend==='qwen3-tts';
      const backendLabel=backend==='piper'?'Piper':backend==='silero'?'Silero':backend==='qwen3-tts'?'Qwen3':'Kokoro';
      const voice=backend==='piper'?(entry.config.piperVoice||piperSpeakers[entry.agent][0]):
          backend==='silero'?(entry.config.sileroVoice||sileroSpeakers[entry.agent][0]):
          backend==='qwen3-tts'?qwen3VoiceFor(entry.agent, entry.config.qwen3Voice):
          (entry.config.kokoroVoice||'af_heart');
      const endpoint=addon?('/api/voice/'+backend+'/speak'):'/api/voice/kokoro/speak';
      const payload={text:entry.text,voice,speed:entry.config.speed||1};
      if(backend==='qwen3-tts')payload.size=qwen3Size;
     const buffer=await this.obtainWavRetry(entry,gen,endpoint,payload,backend==='qwen3-tts'?600:450,controller);
     if(controller.signal.aborted||gen!==this.generation)return;
     // Don't announce speech for a decoder buffer without audible samples.
     const data=buffer.getChannelData(0);let peak=0;
     for(let i=0;i<data.length;i+=17)peak=Math.max(peak,Math.abs(data[i]));
     if(!(buffer.duration>0&&peak>.0006))
       throw Error('Модель '+backendLabel+' вернула WAV без слышимого звука');
     await this.audioReady();
     const source=this.ctx.createBufferSource();
     source.buffer=buffer;source.playbackRate.value=1;
     this.connectOutput(source,entry.config);this.nodes.add(source);
     await new Promise(resolve=>{
       source.onended=()=>{this.nodes.delete(source);source.disconnect();source._voiceGain?.disconnect();resolve()};
       controller.signal.addEventListener('abort',resolve,{once:true});
       source.start();this.atPlayhead(entry,gen,this.ctx.currentTime);this.maybePrefetch();
     });
     if(!controller.signal.aborted&&gen===this.generation){this.metric(entry,"drained");if(entry.onFinish)entry.onFinish(entry.raw);}
   }catch(err){
     if(!controller.signal.aborted&&gen===this.generation){
       system(backendLabel+': '+err.message+' · резервный голос');
       fallback=haveSpeech&&!entry.started;
     }
   }finally{
     if(gen===this.generation){
       this.controller=null;
       if(fallback)this.playBrowser(entry,gen);
       else{this.playing=false;this.pump();}
     }
   }
 },
 idle(){if(!this.playing&&!this.queue.length)return Promise.resolve();return new Promise(resolve=>this.waiters.push(resolve))}
};
function humanBytes(bytes){
 const n=Number(bytes)||0;
 return n>=1024*1024*1024?(n/(1024*1024*1024)).toFixed(2)+' ГБ':
        n>=1024*1024?(n/(1024*1024)).toFixed(1)+' МБ':(n/1024).toFixed(0)+' КБ';
}
function status(head,desc='',cls=''){$('connection').textContent=head;$('detail').textContent=desc;$('indicator').className='led '+cls;}
function runStatus(text){$('runstate').textContent=text;}
function updateDonationBadge(){
 const element=$('queueStatus');if(!element)return;
 const waiting=state.donationQueue.length,active=state.activeDonation;
 element.classList.toggle('busy',!!active||waiting>0);
 element.textContent=active?'⚡ '+active.donor+' · '+active.responses.length+'/'+active.total+(waiting?' · +'+waiting:''):
   waiting?'⚡ В ОЧЕРЕДИ '+waiting+' · ПОСЛЕ РЕПЛИКИ':'◌ ОЧЕРЕДЬ ПУСТА';
}
// Bound both transcript DOM and TXT archive for arbitrarily long shows.
const VISIBLE_FEED_LIMIT = 180;
const ARCHIVED_FEED_LIMIT = 450;
function transcriptLine(el){
 return el.querySelector('.who').textContent+': '+el.querySelector('.body').textContent+' ['+el.querySelector('.meta').textContent+']';
}
function feedItem(name,agent=null,kind=''){
 const el=document.createElement('div');el.className='message '+kind;el.style.setProperty('--accent',agent===null?'#7f90a7':defs[agent].color);
 const who=document.createElement('div');who.className='who';who.textContent=name;
 const body=document.createElement('div');body.className='body';const meta=document.createElement('div');meta.className='meta';
 el.append(who,body,meta);
 const feed=$('feed');
 if(feed.querySelectorAll('.message').length>=VISIBLE_FEED_LIMIT){
  const first=feed.querySelector('.message');
  state.archivedLines.push(transcriptLine(first));
  if(state.archivedLines.length>ARCHIVED_FEED_LIMIT)state.archivedLines.shift();
  first.remove();
 }
 feed.append(el);feed.scrollTop=feed.scrollHeight;return {el,body,meta};
}
function system(msg){const item=feedItem('СИСТЕМА',null,'system');item.body.textContent=msg;item.meta.textContent=new Date().toLocaleTimeString('ru-RU');}
function optionsForVoices(sel,index){
 sel.replaceChildren();
 const mode=$('ttsBackend').value;
 if(mode==='piper'){
   for(const [id,name] of piperSpeakers)sel.add(new Option(name,id));
   sel.value=defs[index].piperVoice||piperSpeakers[index][0];return;
 }
 if(mode==='silero'){
   for(const [id,name] of sileroSpeakers)sel.add(new Option(name,id));
   sel.value=defs[index].sileroVoice||sileroSpeakers[index][0];return;
 }
 if(mode==='kokoro'){
   if(kokoroModel==='ru'){
     for(const [id,name] of kokoroRuSpeakers)sel.add(new Option(name,id));
     sel.value=defs[index].kokoroRuVoice||['sveta','dima','masha'][index];return;
   }
   for(const id of kokoroSpeakers)sel.add(new Option(id,id));
   sel.value=defs[index].kokoroVoice||'af_heart';return;
 }
 if(mode==='qwen3-tts'){
   for(const id of qwen3SpeakerList())sel.add(new Option('Встроенный · '+id,id));
   for(const v of qwen3Voices)sel.add(new Option('Кастомный · '+v.name,v.id));
   sel.value=qwen3VoiceFor(index, defs[index].qwen3Voice);return;
 }
 const current=defs[index].voiceURI;
 sel.add(new Option('Автовыбор голоса',''));
 for(const v of voices)sel.add(new Option((v.lang||'?')+' · '+v.name,v.voiceURI));
 sel.value=voices.some(v=>v.voiceURI===current)?current:'';
}
function forceRenderCards(){$('cards').replaceChildren();renderCards()}

function renderCards(){
 if($('cards').children.length===defs.length){
  defs.forEach((def,i)=>{
    const c=$('cards').children[i],active=state.current?.agent===i,speaking=speech.audibleAgent===i;
    c.classList.toggle('active',speaking);
    const badge=c.querySelector('.badge');
    badge.textContent=speaking?'● ГОВОРИТ':active?(state.current.phase==='speaking'?'◌ ГОТОВИТ ГОЛОС':'◌ ДУМАЕТ'):
       (state.current?.listeners?.has(i)?'◌ СЛУШАЕТ':'○ НА ЛИНИИ');
    c.querySelector('.interrupt-btn').disabled=!state.running||state.paused||active;
  });return;
 }
 $('cards').replaceChildren();defs.forEach((def,i)=>{
  const current=state.current,speaking=speech.audibleAgent===i;
  const c=document.createElement('article');c.className='card'+(speaking?' active':'');c.style.setProperty('--accent',def.color);
  const top=document.createElement('div');top.className='cardhead';
  const number=document.createElement('span');number.className='number';number.textContent='ENTITY / 0'+(i+1);
  const badge=document.createElement('span');badge.className='badge';badge.textContent=speaking?'● ГОВОРИТ':current?.agent===i?(current.phase==='speaking'?'◌ ГОТОВИТ ГОЛОС':'◌ ДУМАЕТ'):(current?.listeners?.has(i)?'◌ СЛУШАЕТ':'○ НА ЛИНИИ');top.append(number,badge);
  function textField(label,value,max,area=false){
   const wrap=document.createElement('label');wrap.className='card-field';
   const title=document.createElement('span');title.textContent=label;
   const input=document.createElement(area?'textarea':'input');
   if(!area)input.type='text';input.maxLength=max;input.value=value;
   wrap.append(title,input);return {wrap,input};
  }
  const name=textField('ИМЯ',def.name,30);
  name.input.onchange=async()=>{
   const candidate=name.input.value.trim().replace(/\s+/g,' ');
   if(!candidate||defs.some((other,j)=>j!==i&&other.name.toLocaleLowerCase('ru')===candidate.toLocaleLowerCase('ru'))){
     name.input.value=def.name;system('Имена агентов должны быть уникальными и непустыми.');return;
   }
   const previous=def.name;def.name=candidate;savePrefs();
   try{await syncAgentNames();}
   catch(e){def.name=previous;name.input.value=previous;savePrefs();system('Не удалось изменить имя в ядре: '+e.message);}
  };
  const description=textField('ХАРАКТЕР / ПОВЕДЕНИЕ',def.description,900,true);
  description.input.oninput=()=>{def.description=description.input.value;savePrefs()};
  const vc=document.createElement('div');vc.className='voice-controls';const select=document.createElement('select');select.setAttribute('aria-label','Голос: '+def.name);optionsForVoices(select,i);select.onchange=()=>setAgentVoice(i,select.value);
  const test=document.createElement('button');test.textContent='♫';
  test.title='Прослушать выбранный голос';test.disabled=!audioAvailable();
  test.onclick=()=>{speech.unlock();speech.stop();speech.push(i,'Привет! Я '+def.name+'. Готов к разговору.')};
  vc.prepend(select);vc.append(test);
  const foot=document.createElement('div');foot.className='foot';
  const emotionSlot=document.createElement('div');emotionSlot.className='emotion-slot';
  const btn=document.createElement('button');btn.className='interrupt-btn';btn.textContent='⚡ ПЕРЕБИТЬ';
  btn.disabled=!state.running||state.paused||current?.agent===i;btn.onclick=()=>interruptWith(i,'manual');
  foot.append(emotionSlot,btn);
  c.append(top,name.wrap,description.wrap,vc,foot);$('cards').append(c);
 });
 window.YapdOmePixel?.mountControls();
}
async function syncAgentNames(){
 const s=await coreEvent('names',{names:defs.map(d=>d.name)});
 applyCore(s);
}
function populateVoices(){
 if(!haveSpeech)return;
 voices=window.speechSynthesis.getVoices().slice().sort((a,b)=>{
  const ar=/^ru/i.test(a.lang)?0:1,br=/^ru/i.test(b.lang)?0:1;return ar-br||a.name.localeCompare(b.name);
 });
 // Auto-assign different Russian voices when available; fallback to system voice otherwise.
 const russian=voices.filter(v=>/^ru/i.test(v.lang));
 defs.forEach((d,i)=>{if(!d.voiceURI&&russian[i])d.voiceURI=russian[i].voiceURI;});
 renderCards();
 defs.forEach((d,i)=>{const sel=$('cards').children[i]?.querySelector('.voice-controls select');if(sel)optionsForVoices(sel,i)});
}
const PREF_KEY='triad09';
function savePrefs(){try{localStorage.setItem(PREF_KEY,JSON.stringify({agents:defs.map(d=>({name:d.name,description:d.description,voiceURI:d.voiceURI,kokoroVoice:d.kokoroVoice,kokoroRuVoice:d.kokoroRuVoice,piperVoice:d.piperVoice,sileroVoice:d.sileroVoice,qwen3Voice:d.qwen3Voice })),topic:$('topic').value,sharedGoal:$('sharedGoal').value,showMode:$('showMode').value,voiceEnabled:$('voiceEnabled').checked,ttsBackend:$('ttsBackend').value,rate:$('rate').value,auto:$('auto').checked,directorEnabled:$('directorEnabled').checked,model:$('model').value,qwen3Size:qwen3Size,kokoroModel:kokoroModel}))}catch(_){}}
function restorePrefs(){
 try{
  const modern=localStorage.getItem(PREF_KEY),p=JSON.parse(modern||localStorage.getItem('triad08')||localStorage.getItem('triad07')||'{}');
  defs.forEach((d,i)=>{
   const a=p.agents?.[i];
   if(a){if(typeof a.name==='string'&&a.name.trim())d.name=a.name.trim().slice(0,30);
     if(typeof a.description==='string'){
        // Migrate only exact retired stock prompts; never overwrite a custom persona.
        const obsolete=['Системный мыслитель: ясность, надёжность, простота. Соединяет идеи собеседников и находит устойчивые решения.',
          'Критичный, но доброжелательный собеседник. Проверяет аргументы, задаёт прямые вопросы, ищет слабые места и предлагает улучшения.',
          'Любознательный изобретатель и импровизатор. Любит неожиданные идеи, юмор и короткие эксперименты, которые проверяют смелые гипотезы.'];
        if(a.description!==obsolete[i])d.description=a.description.slice(0,900);
        else if(a.name===['Архитектор','Скептик','Экспериментатор'][i])
          d.name=['Норман','Глитч','Джесси'][i];
      }
     else if(typeof a.role==='string')d.description=
       (a.role+(typeof a.goal==='string'&&a.goal.trim()?' '+a.goal:'')).slice(0,900);
     if(typeof a.voiceURI==='string')d.voiceURI=a.voiceURI;
     if(kokoroSpeakers.includes(a.kokoroVoice))d.kokoroVoice=a.kokoroVoice;
     if(kokoroRuSpeakers.some(([id])=>id===a.kokoroRuVoice))d.kokoroRuVoice=a.kokoroRuVoice;
     if(piperSpeakers.some(([id])=>id===a.piperVoice))d.piperVoice=a.piperVoice;
     if(sileroSpeakers.some(([id])=>id===a.sileroVoice))d.sileroVoice=a.sileroVoice;
     if(typeof a.qwen3Voice==='string'&&a.qwen3Voice)d.qwen3Voice=a.qwen3Voice;
     // Legacy pitch/speed/volume prefs are deliberately not restored.
    }
   else{if(typeof p.voices?.[i]==='string')d.voiceURI=p.voices[i];if(typeof p.roles?.[i]==='string')d.description=p.roles[i].slice(0,900);}
  });
  // An edited agent roster must remain addressable in the C controller.
  const seen=new Set();defs.forEach((d,i)=>{const key=d.name.toLocaleLowerCase('ru');if(seen.has(key)){d.name=['Норман','Глитч','Джесси'][i]}seen.add(d.name.toLocaleLowerCase('ru'))});
  if(typeof p.topic==='string')$('topic').value=p.topic.slice(0,700);
  if(typeof p.sharedGoal==='string')$('sharedGoal').value=p.sharedGoal.slice(0,900);
   if(['live','science'].includes(p.showMode))$('showMode').value=p.showMode;
   else if(p.showMode==='debate')$('showMode').value='science';
   else if(p.showMode==='scene')$('showMode').value='live';
  if(typeof p.voiceEnabled==='boolean')$('voiceEnabled').checked=p.voiceEnabled;
  if(['kokoro','piper','silero','qwen3-tts','browser'].includes(p.ttsBackend))$('ttsBackend').value=p.ttsBackend;
  else if(p.ttsBackend==='kokoro-ru'){$('ttsBackend').value='kokoro';kokoroModel='ru';}
  if(typeof p.auto==='boolean')$('auto').checked=p.auto;
  if(typeof p.directorEnabled==='boolean')$('directorEnabled').checked=p.directorEnabled;
  if(p.rate&&Number(p.rate)>=.75&&Number(p.rate)<=1.5)$('rate').value=p.rate;
  if(['pro','lite'].includes(p.qwen3Size)){qwen3Size=p.qwen3Size;if($('qwen3Size'))$('qwen3Size').value=qwen3Size;}
  if(['ru','en'].includes(p.kokoroModel)){kokoroModel=p.kokoroModel;if($('kokoroModel'))$('kokoroModel').value=kokoroModel;}
 }catch(_){}
 $('rateValue').textContent=Number($('rate').value).toFixed(2)+'×';
}
async function api(path,body){
 const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
 const data=await r.json().catch(()=>({error:'Сервер вернул некорректный ответ'}));if(!r.ok)throw Error(data.error||'HTTP '+r.status);return data;
}
async function refreshStatus(){
 try{
  const response=await fetch('/api/status',{cache:'no-store'});
  if(!response.ok)throw Error('HTTP '+response.status);
  const data=await response.json();
  state.connected=Boolean(data.connected);
  state.deepseekConnected=Boolean(data.deepseek_connected);
  state.provider=data.provider||'chatgpt';
  state.recoverable=Boolean(data.recoverable);
  $('provider').value=state.provider;
  $('chatgptAuth').hidden=state.provider!=='chatgpt';
  $('deepseekAuth').hidden=state.provider!=='deepseek';
  $('logout').hidden=!state.connected;
  $('switchaccount').hidden=state.connected&&!state.recoverable||!state.connected&&!data.has_saved_account&&!state.recoverable;
  $('signin').textContent=state.recoverable?'Повторить вход':state.connected?'Сменить ChatGPT':'Войти через ChatGPT';
  $('deepseekDisconnect').hidden=!state.deepseekConnected;
  if(state.provider==='deepseek'){
   if(state.deepseekConnected){
    status('DEEPSEEK CONNECTED','API-ключ активен', 'ok');
    $('deepseekNote').textContent=data.auth_error||'Подключено. Ключ хранится локально в accounts.json.';
    $('deepseekKey').value='';
    await fetchModels();
   }else{
    status('DEEPSEEK OFFLINE',data.auth_error||'Введи API-ключ DeepSeek');
    $('model').disabled=true;
    $('model').replaceChildren(new Option('Сначала подключись',''));
    $('deepseekNote').textContent=data.auth_error||'Получи ключ на platform.deepseek.com и вставь его сюда.';
   }
  }else if(state.connected){
   status('CONNECTED',data.account||'', 'ok');
   $('authnote').textContent=data.auth_error||'Подключено. Используется разрешённая подписка ChatGPT.';
   await fetchModels();
  }else{
   status('CHATGPT OFFLINE',data.auth_error||'Вход через браузер');
   $('model').disabled=true;
   $('model').replaceChildren(new Option('Сначала войди',''));
   $('authnote').textContent=data.auth_error||(data.has_saved_account?'Нажми «Войти». Для смены используй «Другой аккаунт».':'Откроется официальный вход ChatGPT. Выбери нужный аккаунт в браузере.');
  }
  if(data.auth_pending)$('authnote').textContent='Ожидаем подтверждение в окне ChatGPT…';
 }catch(err){
  status('LOCAL BRIDGE OFFLINE',err.message);
  $('authnote').textContent='Запусти START.command и открой локальный адрес.';
 }
}
async function fetchModels(){
 if(!(state.provider==='deepseek'?state.deepseekConnected:state.connected))return;
 let saved='';try{saved=JSON.parse(localStorage.getItem(PREF_KEY)||'{}').model||''}catch(_){}const prev=$('model').value||saved,select=$('model');select.disabled=true;select.replaceChildren(new Option('Загрузка моделей…',''));
 try{const r=await fetch('/api/models',{cache:'no-store'});const data=await r.json();if(!r.ok)throw Error(data.error||'HTTP '+r.status);if(!data.models?.length)throw Error('Доступных моделей нет');select.replaceChildren();data.models.forEach(m=>select.add(new Option(m.name,m.slug)));select.value=data.models.some(m=>m.slug===prev)?prev:data.models[0].slug;select.disabled=false;savePrefs();}
 catch(err){select.replaceChildren(new Option('Модели недоступны',''));$('authnote').textContent='Ошибка каталога моделей: '+err.message;}
}
// Native C is the authority for turn assignment, pauses, interrupts and limits.
let controlQueue=Promise.resolve();
function coreEvent(action,fields={}){
 const task=()=>api('/api/engine',{action,...fields});
 const p=controlQueue.then(task);controlQueue=p.catch(()=>{});return p;
}
function applyCore(s){
 // Use C revision as an ordering guard against delayed GET/poll responses.
 if(state.core && s.revision<state.core.revision)return false;
 state.core=s;state.turns=s.turns;
 state.running=['RUNNING','PAUSED','WAIT_USER','REVIEW'].includes(s.status);
 $('start').disabled=state.running||state.stopping||state.starting;
 state.paused=s.status==='PAUSED'||s.status==='WAIT_USER'; // donation REVIEW never pauses dialogue
 $('pause').textContent=s.status==='PAUSED'?'▶ ПРОДОЛЖИТЬ':'Ⅱ ПАУЗА';
 const labels={IDLE:'ГОТОВ К ЭФИРУ',RUNNING:`В ЭФИРЕ · ХОД ${s.turns}`, 
  PAUSED:'ПАУЗА ВЕДУЩЕГО',WAIT_USER:'НЕБОЛЬШАЯ ПАУЗА',REVIEW:'ОЦЕНКА ДОНАТА',STOPPED:'ОСТАНОВЛЕНО',
  LIMIT:'ЛИМИТ ХОДОВ',ERROR:'ОШИБКА'};
 // Debate phase is meaningful only if the host explicitly selected debates.
 const phase=$('showMode').value==='science'?(PHASE_LABEL[currentPhase(s.turns)]||''):'';
 runStatus((labels[s.status]||s.status)+(s.status==='RUNNING'&&phase?' · '+phase:''));updateScienceUI();renderCards();
 return true;
}
function stopTimer(){clearTimeout(state.timer);state.timer=null;}
function cancelListeners(c){
 for(const obj of c.listenerRequests||[]){obj.controller.abort();api('/api/cancel',{request_id:obj.id}).catch(()=>{});}
 if(c.listeners)c.listeners.clear();c.listenerRequests=[];
}
function cancelCurrent(reason='прервано'){
 state.pipelineReady=false;
 const c=state.current,audible=state.audibleTurn;
 if(audible&&audible!==c){
   audible.item.el.classList.remove('live');
   audible.item.el.classList.add('interrupted');
   audible.item.meta.textContent=reason;
 }
 state.audibleTurn=null;
 // Speech can outlive its already-completed model turn in v0.12.
 // Human STOP/PAUSE/intervention must still cancel that audible tail.
 if(!c){speech.stop();return;}
 c.controller.abort();api('/api/cancel',{request_id:c.requestId}).catch(()=>{});
 cancelListeners(c);speech.stop();c.item.el.classList.remove('live');c.item.el.classList.add('interrupted');c.item.meta.textContent=reason;
 const heard=($('voiceEnabled').checked&&audioAvailable())?(c.heardText||''):stripDirectives(c.text);
 if(heard.trim()&&!isMarker(heard))state.history.push({agent:c.agent,name:defs[c.agent].name,text:heard+' [прервано]'});
 state.history=state.history.slice(-16);state.current=null;
}
function isMarker(s){
  const t=String(s||'').toUpperCase().replace(/[[\]\s.!?,;:]/g,'');
  return t==='PASS'||t==='WAITUSER'||t==='WAIT_USER';
}
function resetLocal(reason='остановлено'){
 state.epoch++;stopTimer();cancelDirector();cancelCurrent(reason);speech.stop();state.running=false;
 state.activeDonation=null;state.donationQueue=[];state.donationRouting=false;state.lastDonationName='';
 state.social.memory=[[],[],[]];state.social.lastPair='';resetSocialFocus();
 updateDonationBadge();
 state.lastAudibleAt=Date.now();state.lastIdleNotice=0;
 state.paused=false;$('start').disabled=false;$('pause').textContent='Ⅱ ПАУЗА';renderCards();
}
// Operator STOP is absolute: cancel audio and pending UI work synchronously,
// then commit STOP to C. Unlike spoken "stop" or a viewer donation, this has authority.
// Use the serialized native event lane so a queued START cannot arrive after STOP.
async function stopDialogue(){
 if(state.stopping)return;
 state.stopping=true;
 resetLocal('ОСТАНОВЛЕНО ВЕДУЩИМ');
 if(micRecognition){
  const mic=micRecognition;micRecognition=null;
  mic.onend=null;
  try{mic.abort()}catch(_){}
  $('mic').textContent='🎙 ГОВОРИТЬ';
 }
 $('start').disabled=true;
 $('stop').disabled=true;
 runStatus('ОСТАНОВКА…');
 try{
  const s=await coreEvent('stop');
  // Idempotent stop can be rejected by C only if it was already STOPPED or IDLE.
  if(!['IDLE','STOPPED'].includes(s.status))throw Error('Ядро не подтвердило остановку: '+s.status);
  applyCore(s);
  runStatus('ОСТАНОВЛЕНО');
  return true;
 }catch(err){
  runStatus('СБОЙ ОСТАНОВКИ');
  system('Не удалось подтвердить остановку C-ядра: '+err.message);
  return false;
 }finally{
  state.stopping=false;
  $('stop').disabled=false;
  $('start').disabled=state.running||state.starting;
 }
}
function engineError(err){system('Ошибка ядра C: '+String(err?.message||err).replace(/ChatGPT/gi,'LLM'));$('start').disabled=false;state.running=false;state.paused=true;stopTimer();cancelCurrent('ОШИБКА');runStatus('ОШИБКА');renderCards();}
async function begin(){
 if(state.running||state.stopping||state.starting)return;
 if(!(state.provider==='deepseek'?state.deepseekConnected:state.connected)){runStatus('НУЖЕН ВХОД');system('Подключись к выбранному провайдеру в панели подключения.');return;}
 if(!$('model').value){runStatus('НЕТ МОДЕЛИ');system('Выбери модель.');return;}
 speech.unlock();resetLocal();state.history=[];state.journal=[];state.archivedLines=[];$('feed').replaceChildren();updateScienceUI();
 const epoch=state.epoch;
 state.starting=true;$('start').disabled=true;
 try{
  await syncAgentNames();
  if(epoch!==state.epoch||state.stopping)return; // a STOP during startup wins
  const s=await coreEvent('start',{max_turns:0});
  if(epoch!==state.epoch||state.stopping)return;
  applyCore(s);
  system('Тема (приоритет): '+$('topic').value+' · Общая цель (в рамках темы): '+($('sharedGoal').value.trim()||'содержательный разговор')+' · LLM · бесконечный эфир'+(audioAvailable()&&$('voiceEnabled').checked?' · голос включён':' · без озвучивания'));savePrefs();
  await claimNext();
 }catch(err){if(epoch===state.epoch&&!state.stopping)engineError(err)}
 finally{
  state.starting=false;
  $('start').disabled=state.running||state.stopping;
 }
}
// A single short-lived planning slot: no growing arrays, no turn-by-turn model judge.
// Native C still owns all speaker claims; a director can propose only a normal rotation.
function cancelDirector(){
 const job=state.directorRequest;
 if(job){job.controller.abort();api('/api/cancel',{request_id:job.requestId}).catch(()=>{});}
 state.directorRequest=null;state.directorPlan=null;state.directorRouted=false;
}
// Scheduling-only lexical signal, not a second semantic judge or routing policy.
// Inspect at most 8 rows x 420 characters. Ignore donors, host rows, directives,
// and microreactions (<4 words). Stuck = newest word-trigram set has >=65%
// containment in each of at least 2 older lines (minimum 2 shared trigrams).
// This deliberately conservative signal does not treat a shared topic as a loop.
function directorStuck(recent){
 const lines=recent.slice(-8).filter(row=>row&&!row.untrusted&&
   Number.isInteger(row.agent)&&row.agent>=0&&row.agent<3&&typeof row.text==='string')
  .map(row=>{
   const words=stripDirectives(row.text.slice(0,420)).toLowerCase().match(/[\p{L}\p{N}]+/gu)||[];
   const grams=new Set();
   if(words.length>=4)for(let i=0;i+2<words.length;i++)grams.add(words.slice(i,i+3).join(' '));
   return grams;
  });
 const newest=lines.pop();
 if(!newest||newest.size<2)return false;
 return lines.filter(older=>{
  let shared=0;for(const gram of newest)if(older.has(gram))shared++;
  return shared>=2&&shared/newest.size>=.65;
 }).length>=2;
}
function requestDirector(currentTurn=null){
 if(!$('directorEnabled').checked||!state.running||state.stopping||state.paused||
    state.activeDonation||state.donationQueue.length||state.directorRequest)return;
 const latest=currentTurn&&!isMarker(currentTurn.text)?
   {agent:currentTurn.agent,name:defs[currentTurn.agent].name,
    text:stripDirectives(currentTurn.text).slice(0,800)}:null;
 const recent=latest?state.history.slice(-7).concat(latest):state.history.slice(-8);
 if(recent.length<4||state.turns<4)return;
 // First eligible request at turn 4; healthy interval 8 turns, stuck interval 2.
 // Hard budget: >=2 turns AND >=15 monotonic seconds between attempts, including
 // failures/cancellation. cancelDirector does not replenish it; a new epoch does.
 // One fixed-size record; no polling, extra LLM calls, or transcript accumulation.
 const now=performance.now(),budget=state.directorBudget;
 if(budget&&budget.epoch===state.epoch){
  const elapsedTurns=state.turns-budget.at;
  if(elapsedTurns<2||now-budget.time<15000)return;
  if(elapsedTurns<(directorStuck(recent)?2:($('showMode').value==='live'?4:8)))return;
 }
 const epoch=state.epoch,requestId=requestID(),controller=new AbortController(),at=state.turns;
 const topic=$('topic').value,job={epoch,requestId,controller,at,topic};
 state.directorRequest=job;
 state.directorBudget={epoch,at,time:now};
 $('directorStatus').textContent='ИИ-режиссёр: анализ контекста…';
 fetch('/api/director',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({request_id:requestId,model:$('model').value,
     agents:defs.map(d=>d.name),cast_profiles:defs.map(d=>({name:d.name,description:String(d.description||'').slice(0,300)})),topic,show_mode:$('showMode').value,history:recent}),
   signal:controller.signal})
  .then(async r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json()})
  .then(({plan})=>{
    if(state.directorRequest!==job||state.epoch!==epoch||topic!==$('topic').value||
       !$('directorEnabled').checked||!state.running||state.stopping||state.paused||
       state.activeDonation||state.donationQueue.length||state.turns>at+4)return;
    if(plan&&Number.isInteger(plan.speaker)&&plan.speaker>=0&&plan.speaker<3&&
       typeof plan.beat==='string'&&plan.beat.length<=190){
       state.directorPlan={...plan,at,topic};
       state.directorRouted=false;
       $('directorStatus').textContent='ИИ-режиссёр: '+(plan.move==='pivot'?'новая подтема':plan.move==='resolve'?'закрытие эпизода':'продолжение')+
         ' · '+plan.beat.slice(0,100);
    }else $('directorStatus').textContent='ИИ-режиссёр: обычная очередь (план не получен)';
  })
  .catch(err=>{if(err.name!=='AbortError'&&state.directorRequest===job&&
    state.epoch===epoch&&topic===$('topic').value&&$('directorEnabled').checked&&
    state.running&&!state.stopping&&!state.paused&&!state.activeDonation&&!state.donationQueue.length)
    $('directorStatus').textContent='ИИ-режиссёр недоступен — работает C-ядро';})
  .finally(()=>{if(state.directorRequest===job)state.directorRequest=null;});
}
async function applyDirectorRoute(epoch){
 const plan=state.directorPlan;
 if(!$('directorEnabled').checked||state.activeDonation||state.donationQueue.length||!plan||state.directorRouted||!state.core||
    state.core.status!=='RUNNING'||state.current||state.core.route_reason!=='rotation'||
    plan.topic!==$('topic').value||state.turns>plan.at+3)return;
 state.directorRouted=true; // one attempt per plan, never retry in a tight loop
 try{
   const result=await coreEvent('director',{agent:plan.speaker,ticket:state.core.ticket});
   if(epoch===state.epoch&&result.accepted)applyCore(result);
 }catch(err){if(!String(err.message).includes('HTTP 409'))console.warn('Режиссёр:',err.message);}
}

// Lightweight conversational floor selection. C still authorizes each handoff.
// A named model handoff, a donation or the human host always overrides this hint.
function resetSocialFocus(){
 state.social.pair=null;state.social.returnContext=null;
 state.social.lastEnd=state.turns;
 renderCards();
}
function socialTurnContext(agent){
 if($('showMode').value!=='live'||state.activeDonation)return null;
 const duo=state.social.pair;
 if(duo&&duo.pair.includes(agent))
  return {kind:'duo',pair:duo.pair.slice(),listener:duo.listener};
 const rejoin=state.social.returnContext;
 if(rejoin&&rejoin.listener===agent)
  return {kind:'rejoin',pair:rejoin.pair.slice(),listener:rejoin.listener};
 if(rejoin&&rejoin.pair.includes(agent))
  return {kind:'invite',pair:rejoin.pair.slice(),listener:rejoin.listener};
 return null;
}
function socialRouteHint(){
 if($('showMode').value!=='live'||state.activeDonation||state.donationQueue.length){
  state.social.pair=null;state.social.returnContext=null;return null;
 }
 const social=state.social,route=state.core;
 if(!route)return null;
 if(social.pair){
  const duo=social.pair;
  if(route.route_reason!=='rotation'&&route.next_agent===duo.listener){
   // Explicit invitation to the third agent wins over a two-person exchange.
   social.returnContext={pair:duo.pair,listener:duo.listener};
   social.pair=null;social.lastEnd=state.turns;
   renderCards();
   return null;
  }
  if(state.turns>=duo.until){
   social.returnContext={pair:duo.pair,listener:duo.listener};
   social.pair=null;social.lastEnd=state.turns;renderCards();
  }
 }
 if(social.returnContext){
  // The silent listener is given a natural opportunity to respond once.
  return social.returnContext.listener;
 }
 if(social.pair){
  const duo=social.pair;
  const last=state.history.slice().reverse().find(x=>Number.isInteger(x.agent)&&x.agent>=0)?.agent;
  return last===duo.pair[0]?duo.pair[1]:duo.pair[0];
 }
 if(state.turns<4||state.turns-social.lastEnd<4)return null;
 const speakers=[];
 for(const line of state.history.slice().reverse()){
  if(Number.isInteger(line.agent)&&line.agent>=0&&line.agent<3&&!speakers.includes(line.agent))
    speakers.push(line.agent);
  if(speakers.length===2)break;
 }
 if(speakers.length!==2)return null;
 const pair=speakers.sort((a,b)=>a-b);
 const listener=[0,1,2].find(i=>!pair.includes(i));
 const key=pair.join('-');
 if(route.route_reason!=='rotation'&&!pair.includes(route.next_agent))return null;
 // Avoid repeatedly sidelining the same third voice in consecutive pair episodes.
 if(social.lastPair===key)return null;
 const exchange=state.history.slice(-4).filter(h=>h&&pair.includes(h.agent));
 if(!exchange.some(h=>/[?？]/.test(h.text||'')))return null; // no artificial duo
 const duration=4; // bounded two-person exchange, then rejoin
 social.pair={pair,listener,until:state.turns+duration};
 social.lastPair=key;renderCards();
 const latest=state.history.slice().reverse().find(x=>Number.isInteger(x.agent)&&x.agent>=0)?.agent;
 return pair.find(i=>i!==latest);
}
// Bounded, attributed conversation excerpts: quotes, not permanent beliefs.
function rememberLiveTurn(agent,text){
 if($('showMode').value!=='live'||!Number.isInteger(agent)||agent<0||agent>2)return;
 const line=String(text||'').trim();if(line.length<22)return;
 const memory=state.social.memory||(state.social.memory=[[],[],[]]);
 memory[agent]=(memory[agent]||[]).slice(-1).concat(line.slice(0,230));
}
function liveMemoryPayload(){
 if($('showMode').value!=='live')return [];
 return (state.social.memory||[[],[],[]]).map((notes,agent)=>({
   agent,notes:(notes||[]).slice(-2).map(x=>String(x).slice(0,230))
 }));
}
// Deterministic social interest bid: relevance of an agent's past remarks to
// the ongoing topic and explicit questions; C retains all final authority.
function liveFloorBid(speaker,text){
 if($('showMode').value!=='live'||state.activeDonation||state.donationQueue.length)return null;
 if(!Number.isInteger(speaker)||speaker<0||speaker>2)return null;
 const terms=new Set((String(text||'').toLowerCase().match(/[\p{L}\p{N}]{4,}/gu)||[]).map(w=>w.slice(0,5)));
 const question=/[?？]/.test(text||'');
 const past=state.history.filter(h=>Number.isInteger(h.agent)&&h.agent>=0&&h.agent<3).slice(-12);
 const bids=[0,1,2].filter(i=>i!==speaker).map(i=>{
   const lines=past.filter(h=>h.agent===i),last=lines.at(-1);
   const idle=last?past.length-1-past.lastIndexOf(last):12;
   let score=Math.min(3,idle)*.3-past.slice(-5).filter(h=>h.agent===i).length*.6;
   if(last){
     const own=new Set((String(last.text||'').toLowerCase().match(/[\p{L}\p{N}]{4,}/gu)||[]).map(w=>w.slice(0,5)));
     let overlap=0;for(const word of terms)if(own.has(word))overlap++;
     score+=Math.min(3,overlap)*1.1;
   }
   const name=String(defs[i]?.name||'').toLowerCase();
   if(name&&String(text||'').toLowerCase().includes(name))score+=question?4:1.8;
   return {agent:i,score};
 }).sort((a,b)=>b.score-a.score||a.agent-b.agent);
 if(!bids.length||bids[0].score<1.3||bids[0].score-bids[1].score<.5)return null;
 return bids[0].agent;
}
async function claimNext(){
 if(!state.running||state.paused||state.current||state.claimPending?.epoch===state.epoch)return;
 // One-ahead handoff: a committed WAV reply has STARTED playing, so the
 // native core may claim one new model turn while it finishes audibly.
 if(!state.pipelineReady&&(speech.playing||speech.queue.length||speech.nodes.size)){
  // A transient system notice or a recovering turn must not lose the next claim.
  stopTimer();state.timer=setTimeout(claimNext,250);return;
 }
 const epoch=state.epoch,claim={epoch};state.claimPending=claim;
 try{
  if(state.donationRouting)return;
  if(state.donationQueue.length&&!state.activeDonation){
    state.claimPending=null;void activateNextDonation();return;
  }
  if(state.activeDonation){
    const wanted=state.activeDonation.nextSpeaker;
    if(state.core?.route_reason!=='donation'||state.core?.next_agent!==wanted){
      const route=await coreEvent('priority_donation',{agent:wanted});
      if(epoch!==state.epoch||!route.accepted)return;
      applyCore(route);
    }
  }else{
   const duo=typeof socialRouteHint==='function'?socialRouteHint():null;
   if(duo!==null&&state.core?.route_reason==='rotation'){
    const route=await coreEvent('social',{agent:duo,ticket:state.core.ticket});
    if(epoch===state.epoch&&route.accepted)applyCore(route);
   }else if(duo===null)await applyDirectorRoute(epoch);
   if(epoch===state.epoch&&state.core?.route_reason==='rotation'&&typeof $==='function'&&$('showMode').value==='live'&&typeof liveFloorBid==='function'){
    const latest=state.history.slice().reverse().find(h=>Number.isInteger(h.agent)&&h.agent>=0);
    const bidder=latest?liveFloorBid(latest.agent,latest.text):null;
    if(bidder!==null){
     const route=await coreEvent('social',{agent:bidder,ticket:state.core.ticket});
     if(epoch===state.epoch&&route.accepted)applyCore(route);
    }
   }
  }
  if(epoch!==state.epoch||!state.running||state.paused||state.current)return;
  const s=await coreEvent('claim');
  if(epoch!==state.epoch)return;
  state.pipelineReady=false;
  applyCore(s);
  if(s.status==='RUNNING'&&s.agent>=0)issueTurn(s.agent,s.ticket);

 }catch(e){if(epoch===state.epoch&&!String(e.message).includes('HTTP 409'))engineError(e)}
 finally{if(state.claimPending===claim)state.claimPending=null}
}
async function interruptWith(agent,reason){
 // A listener decision made before a donation arrived must NOT cut off its speaker.
 if(reason==='ai'&&(state.activeDonation||state.donationQueue.length))return;
 if(!state.running||state.paused||state.current?.agent===agent)return;
 // Manual acoustic barge-in is meaningful after generated text is committed
 // but while its speech is still audible. Do not "interrupt" silence.
 if(!state.current && reason!=='ai' && !speech.playing && !speech.queue.length)return;
 if(!state.current && reason==='ai')return;
 const ticket=state.core?.ticket,epoch=state.epoch;
 try{
  const s=await coreEvent('interrupt',{agent,ticket,auto:reason==='ai'});
  if(epoch!==state.epoch||state.stopping||!s.accepted)return;
  // Preserve a bounded excerpt of the interrupted speech. The original
  // turn never reached COMPLETE; without this the next LLM has no reason
  // for its objection. The preview is NOT a verified audible transcript.
  const interrupted=state.current;
  if(interrupted&&!interrupted.donation){
   const preview=stripDirectives(interrupted.heardText||
     (interrupted.audioStarted?interrupted.audibleText.slice(0,180):interrupted.text.slice(0,180))).trim();
   if(preview){
    state.history.push({agent:interrupted.agent,name:defs[interrupted.agent].name,
      text:preview.slice(0,220),interrupted:true});
    state.history=state.history.slice(-16);
   }
  }
  state.epoch++;stopTimer();cancelCurrent('ПРЕРВАНО • '+(reason==='ai'?'по решению слушателя':'вручную'));
  applyCore(s);
  system('⚡ '+(reason==='ai'?'Агент решил вмешаться: ':'Ручное перебивание: ')+defs[agent].name);
  claimNext();
 }catch(e){if(!String(e.message).includes('HTTP 409'))console.warn('Перебивание:',e.message)}
}
function scheduleNext(){
 if(!state.running||state.paused||state.stopping)return;
 stopTimer();
 // In full-WAV pipeline, start next LLM as soon as the previous WAV begins
 // playing. Outside that mode preserve the original audio-clock behavior.
 const delay=state.pipelineReady?0:(state.core?.passes>=3?1500:(!$('voiceEnabled').checked?320:85));
 state.timer=setTimeout(claimNext,delay);
}
async function endTurn(c,success,msg){
 if(state.current!==c)return;
 cancelListeners(c);c.item.el.classList.remove('live');
 const value=c.text.trim(),epoch=state.epoch;
 if(!success){
  // On a donation failure, try the next distinct persona rather than burning
  // all three retries on the same model. Keep the donor in the active slot.
  if(c.donation&&state.activeDonation===c.donation){
    c.donation.nextSpeaker=(c.agent+1)%3;
    c.donation.item.meta.textContent='⚠ СБОЙ РЕПЛИКИ · пробуем другого персонажа';
  }
  // Audio is drained on the legacy path; pipeline errors release no extra slot.
  state.pipelineReady=false;
  c.item.meta.textContent=msg;
  try{
    const s=await coreEvent('recover',{ticket:c.ticket});
    if(epoch===state.epoch&&state.current===c){
      state.current=null;
      applyCore(s);system('Сбой потока: '+msg+' · попытка восстановления '+s.errors+'/3');
      if(s.status==='RUNNING'){
        // Recovery also preserves FIFO priority, but only AFTER C and audio finish.
        if(state.donationQueue.length&&!state.activeDonation){if(typeof resetSocialFocus==='function')resetSocialFocus();void activateNextDonation();}
        else scheduleNext();
      }
      else if(s.status==='ERROR'){
        if(state.activeDonation)state.activeDonation.item.meta.textContent=
          '⚠ ОЖИДАЕТ ВОССТАНОВЛЕНИЯ LLM · ответ не получен';
        system('Три ошибки подряд. Нужна проверка подключения LLM.');
      }
    }
  }catch(e){if(epoch===state.epoch)engineError(e)}
  return;
 }
 try{
  const s=await coreEvent('complete',{ticket:c.ticket,agent:c.agent,text:value.slice(0,4000)});
  if(epoch!==state.epoch||state.current!==c)return;
  // Keep the JS ticket locked until C confirms COMPLETE.
  state.current=null;
  applyCore(s);
  if(s.kind==='pass'||s.kind==='wait'){
   c.item.el.remove();
   // Silent PASS is an immediate turn handoff, never a 20-second timeout.
  }else if(value){
   const spoken=stripDirectives(value);
   c.finalMeta=msg+(s.next_agent>=0&&s.next_agent<3?' · слово отдано: '+defs[s.next_agent].name:'');
   c.item.meta.textContent=c.pipeline&&c.audioStarted&&!c.audioFinished?
     'ГОВОРИТ · '+defs[c.agent].name:c.finalMeta;
   if(spoken&&!c.donation){
     state.history.push({agent:c.agent,name:defs[c.agent].name,text:spoken});
     state.history=state.history.slice(-16);
     if($('showMode').value==='science')rememberFinding(c.agent,defs[c.agent].name,spoken);
      else if(typeof rememberLiveTurn==='function')rememberLiveTurn(c.agent,spoken);
     state.lastDonationName=''; // Bridge only first regular turn after donation.
   }
  }
  if(c.donation&&state.activeDonation===c.donation){
    const generated=stripDirectives(c.generatedText);
    if(generated&&!isMarker(c.generatedText)){
      c.donation.responses.push(generated.slice(0,300));
      c.donation.remaining--;
      c.donation.acknowledged=true;
      const repeated=donationRepeats(c.donation.responses);
      if(repeated||c.donation.remaining<=0){
        const used=c.donation.responses.length;
        c.donation.item.meta.textContent=
          '✓ ОТВЕТ ПОЛУЧЕН · '+used+' '+(used===1?'реплика':used<5?'реплики':'реплик')+
          (repeated?' · повторение остановлено':'');
        state.lastDonationName=c.donation.donor;
        state.activeDonation=null;updateDonationBadge();
      }else{
        c.donation.item.meta.textContent='ОБСУЖДАЮТ · осталось до '+c.donation.remaining+' реплик';
        c.donation.nextSpeaker=(c.agent+1)%3;
      }
    }else{
      // Repeated marker-only replies must not lock the whole show forever.
      c.donation.emptyReplies=(c.donation.emptyReplies||0)+1;
      if(c.donation.emptyReplies>=2){
        c.donation.item.meta.textContent='⚠ МОДЕЛЬ НЕ ДАЛА СОДЕРЖАТЕЛЬНОГО ОТВЕТА';
        state.activeDonation=null;updateDonationBadge();
      }else{
        c.donation.nextSpeaker=(c.agent+1)%3;
        c.donation.item.meta.textContent='ПУСТОЙ ОТВЕТ · пробуем другого персонажа';
      }
    }
  }
  if(s.status==='RUNNING'){
    if(state.donationQueue.length&&!state.activeDonation)void activateNextDonation();
    else{if(!state.activeDonation)requestDirector();scheduleNext();}
  }

 }catch(e){if(epoch===state.epoch)engineError(e)}
}
// The research notebook stores draft claims, not validated scientific results.
function rememberFinding(agent,speaker,text){
 const content=String(text||'').trim();
 if(content.length<12)return;
 const first=content.match(/^(.{12,240}?[.!?…])(?:\s|$)/);
 const claim=(first?first[1]:content.slice(0,240)).trim();
 const key=claim.toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').slice(0,110);
 if(!key||state.journal.some(e=>e.key===key))return;
 state.journal.push({agent,speaker,claim,phase:currentPhase(Math.max(0,state.turns-1)),key});
 state.journal=state.journal.slice(-12);
 updateScienceUI();
}
// One complete model turn becomes one immutable browser utterance or
// one preassembled local WAV. No spoken fragments during LLM streaming.
// The 450-character native inference limit remains internal to wavFor().
function queueWholeSpeech(c){
 const text=ttsText(stripDirectives(c.text));
 if(!text||!$('voiceEnabled').checked)return Promise.resolve();

 let notifyStart;
 const started=new Promise(resolve=>{notifyStart=resolve});
 speech.push(c.agent,text,part=>{
   if(c.epoch!==state.epoch)return;
   c.audioStarted=true;
   state.audibleTurn=c;
   c.audibleText=part;
   c.item.body.textContent=part;
   c.item.meta.textContent='ГОВОРИТ · '+defs[c.agent].name;
   $('feed').scrollTop=$('feed').scrollHeight;
   notifyStart();
 },part=>{
   if(c.epoch!==state.epoch)return;
   c.heardText=part;
   c.audioFinished=true;
   if(state.audibleTurn===c)state.audibleTurn=null;
   c.item.meta.textContent=c.finalMeta||'Завершено · '+new Date().toLocaleTimeString('ru-RU');
 },c.speechConfig);
 // A failed TTS transport still releases the native ticket after the
 // playback lane drains, instead of hanging the whole live show forever.
 return Promise.race([started,speech.idle()]);
}
function maybeConsultListeners(c){
 // For native WAV/PCM, the first audible phrase is known when playback starts.
 // Preview at most 220 characters while the C ticket remains claimable.
 const sample=c.heardText||(c.pipeline&&c.audioStarted?c.audibleText.slice(0,220):'');
 if(state.activeDonation||state.donationQueue.length||!$('auto').checked||
    $('showMode').value!=='live'||c.intentSent||
    sample.length<(/[?？!]/.test(sample)?45:90)||
    c.turn<state.core?.cooldown_until||!state.running||state.paused)return;
 c.intentSent=true;
 // One interested candidate per turn; avoids two extra LLM requests.
 const preferred=liveFloorBid(c.agent,sample);
 const last=state.history.at(-1)?.agent;
 const listener=preferred!==null?preferred:([0,1,2].find(i=>i!==c.agent&&i!==last)??((c.agent+1)%3));
 for(const agent of [listener]){
  const controller=new AbortController(),id=requestID(),entry={id,controller};
  c.listenerRequests.push(entry);c.listeners.add(agent);
  const payload={request_id:id,agent,agent_name:defs[agent].name,description:defs[agent].description,topic:$('topic').value,show_mode:$('showMode').value,shared_goal:$('sharedGoal').value,model:$('model').value,
                 turns:state.turns,journal:$('showMode').value==='science'?state.journal.map(({speaker,claim,phase})=>({speaker,claim,phase})):[],
                 history:state.history.slice(-12),speaker:defs[c.agent].name,partial:sample.slice(-700)};
  fetch('/api/intent',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:controller.signal})
   .then(async r=>{const j=await r.json();if(!r.ok)throw Error(j.error||'Ошибка анализа');return j;})
   .then(j=>{if(state.current===c&&!state.activeDonation&&!state.donationQueue.length&&state.running&&!state.paused&&j.decision==='interrupt')interruptWith(agent,'ai');})
   .catch(e=>{if(e.name!=='AbortError'&&state.current===c)console.warn('Решение слушателя:',e.message)})
   .finally(()=>{c.listeners.delete(agent);c.listenerRequests=c.listenerRequests.filter(x=>x!==entry);if(state.current===c)renderCards()});
 }
 renderCards();
}
async function issueTurn(agent,ticket){
 if(!state.running||state.paused||state.current)return;
 const epoch=state.epoch,requestId=requestID(),item=feedItem(defs[agent].name,agent,'live');item.meta.textContent='Ожидание потока…';
 const donation=state.activeDonation;
 const socialFocus=donation||typeof socialTurnContext!=='function'?null:socialTurnContext(agent);
 if(socialFocus?.kind==='rejoin')state.social.returnContext=null;
 // One deterministic named greeting; the model must not repeat it.
 const greeting=donation&&!donation.acknowledged?'Спасибо, '+donation.donor+'! ':'';
 const baseSpeechConfig=speech.snapshot(agent);
 const pipeline=baseSpeechConfig.backend!=='browser'&&$('voiceEnabled').checked;
 const c={agent,ticket,turn:state.turns,epoch,requestId,item,text:greeting,generatedText:'',
          donation,socialFocus,pipeline,speechConfig:pipeline?Object.freeze({...baseSpeechConfig,wholeWav:true}):baseSpeechConfig,
          audibleText:'',heardText:'',controller:new AbortController(),
          intentSent:false,listeners:new Set(),listenerRequests:[],phase:'generating',lastTokenAt:Date.now()};
 state.current=c;renderCards();
 try{
  await realTurn(c);
  if(state.current!==c)return;
  if(c.pipeline){
   const spoken=stripDirectives(c.text);
   if(spoken&&!isMarker(c.text)){
    c.phase='speaking';
    c.item.meta.textContent='ПОДГОТОВКА WAV…';
    await queueWholeSpeech(c);
    if(state.current!==c||epoch!==state.epoch)return;
    // Audio and native controller are separate clocks. We release the native
    // ticket *after playback begins*, not after it ends; the one-ahead bound
    // is enforced by state.current holding the next model generation.
    // v0.18 LIVE needs an active ticket throughout TTS for genuine interrupts.
    // Без авто-перебиваний сохраняется one-ahead WAV-конвейер.
    const liveListening=$('showMode').value==='live'&&$('auto').checked;
    if(liveListening&&c.audioStarted){
     c.phase='speaking';maybeConsultListeners(c);
     await speech.idle();
     if(state.current!==c||epoch!==state.epoch)return;
    }
    state.pipelineReady=!liveListening&&Boolean(c.audioStarted&&speech.playing);
    if(!c.audioStarted)c.item.body.textContent=spoken;
    await endTurn(c,true,'Завершено · '+new Date().toLocaleTimeString('ru-RU'));
    return;
   }
   await endTurn(c,true,'Завершено · '+new Date().toLocaleTimeString('ru-RU'));
   return;
  }
  if(!isMarker(c.text))await queueWholeSpeech(c);
  // While the previous phrase is audible, plan the next scene asynchronously.
  // This hides most director latency under TTS without blocking the C clock.
  if(!c.donation&&!isMarker(c.text))requestDirector(c);
  // Keep the C ticket and the speaker's turn until ALL their audio has ended.
  c.phase='speaking';
  if(speech.playing||speech.queue.length||speech.nodes.size){
   item.meta.textContent='ОЗВУЧИВАНИЕ · ожидаем завершения речи';renderCards();
   await speech.idle();
   if(state.current!==c||epoch!==state.epoch)return;
  }
  // If sound is disabled (or failed), display the final transcript normally.
  item.body.textContent=stripDirectives(c.text);
  await endTurn(c,true,'Завершено · '+new Date().toLocaleTimeString('ru-RU'));
 }catch(err){
  if(state.current!==c)return;
  // Never speak an incomplete/error response as separate sentence fragments.
  // If synthesis already started, drain its audible tail before native recovery.
  if(speech.playing||speech.queue.length||speech.nodes.size)await speech.idle();
  if(state.current===c)await endTurn(c,false,'Ошибка: '+err.message);
 }
}
async function realTurn(c){
 // `agent` on every history entry lets the server rebuild a REAL dialogue:
 // this agent's own turns become assistant messages, peers become user turns.
 const response=await fetch('/api/stream',{method:'POST',headers:{'Content-Type':'application/json'},signal:c.controller.signal,
  body:JSON.stringify({request_id:c.requestId,agent:c.agent,agent_name:defs[c.agent].name,description:defs[c.agent].description,agents:defs.map(d=>d.name),cast_profiles:defs.map(d=>({name:d.name,description:d.description})),model:$('model').value,topic:$('topic').value,show_mode:$('showMode').value,shared_goal:$('sharedGoal').value,social_focus:c.socialFocus,social_memory:liveMemoryPayload(),turns:state.turns,history:state.history.filter(h=>!h.untrusted || h.expiresAfter>=state.turns).slice(-12),journal:$('showMode').value==='science'?state.journal.map(({speaker,claim,phase})=>({speaker,claim,phase})):[],
  director_plan:!state.activeDonation&&!c.socialFocus&&state.directorPlan&&$('directorEnabled').checked&&state.directorPlan.topic===$('topic').value&&state.turns<=state.directorPlan.at+4?state.directorPlan:null,
  donation_context:c.donation?{name:c.donation.donor,amount:c.donation.amount,
      text:c.donation.text,first:!c.donation.acknowledged,remaining:c.donation.remaining,
      total:c.donation.total,covered:c.donation.responses}:null,
  post_donation_name:!c.donation?state.lastDonationName:''})});
 if(!response.ok){const d=await response.json().catch(()=>({}));throw Error(d.error||'HTTP '+response.status)}
 if(!response.body)throw Error('Браузер не поддерживает потоковый вывод');
 const reader=response.body.getReader(),dec=new TextDecoder();let buf='',completed=false;
 const parsePacket=block=>{
  const text=block.split('\n').filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trim()).join('\n');if(!text)return;
  let event;try{event=JSON.parse(text)}catch(_){return;}
  if(state.current!==c)return;
  if(event.type==='delta'){
   c.generatedText+=event.text||'';c.text+=event.text||'';c.lastTokenAt=Date.now();
   // The turn contract stays invisible to the audience and to the speakers.
   // Raw model deltas stay private until the corresponding audio starts.
   if(!$('voiceEnabled').checked||!audioAvailable())c.item.body.textContent=stripDirectives(c.text);
   c.item.meta.textContent='ФОРМИРУЕТ ОТВЕТ…';
   if(!$('voiceEnabled').checked||!audioAvailable()){c.heardText=stripDirectives(c.text);maybeConsultListeners(c);}
  }else if(event.type==='done')completed=true;
  else if(event.type==='error')throw Error(event.message||'Ошибка ответа OpenAI');
 };
 try{
  while(true){
   const chunk=await reader.read();if(chunk.done)break;
   buf+=dec.decode(chunk.value,{stream:true}).replace(/\r/g,'');
   let idx;while((idx=buf.indexOf('\n\n'))!==-1){parsePacket(buf.slice(0,idx));buf=buf.slice(idx+2);if(completed)break;}
   if(completed)break;
  }
  if(!completed){buf+=dec.decode();if(buf.trim())parsePacket(buf)}
  if(!completed)throw Error('Ответ прерван до response.completed');
 }finally{try{await reader.cancel()}catch(_){}}
}
function hostTopicChange(text){
 // Only commands from the human host, never donations, replace priority topic.
 const value=String(text||'').trim();
 if(/^(?:смени|смените|давайте сменим|поменяйте)\s+тему[.!?…]*$/iu.test(value))
  return ''; // switch to free conversation rather than falling back to the old topic
 const pattern=/^(?:(?:смените|смени|сменим|меняем|поменяйте|поменяем)(?:\s+полностью)?\s+тему\s+(?:на|:)\s*|(?:(?:теперь|давайте)\s+)?(?:поговорим|поговорите|говорите)\s+(?:о|об|про)\s+)([\s\S]{2,700})\s*$/iu;
 const found=pattern.exec(value);
 if(!found)return null;
 const next=found[1].replace(/[.!?…]+\s*$/u,'').trim();
 return next&&next.length<=700?next:null;
}
async function humanMessage(){
 const text=$('interject').value.trim();if(!text)return;
 const newTopic=hostTopicChange(text);
 if(!state.running){system('Сначала начни диалог.');return;}
 if(state.core?.status==='PAUSED'){system('Эфир на ручной паузе — сначала нажми ПРОДОЛЖИТЬ.');return;}
 state.lastAudibleAt=Date.now(); // присутствие ведущего сбрасывает сторож тишины
 $('interject').value='';resetSocialFocus();state.epoch++;stopTimer();cancelDirector();cancelCurrent('ПЕРЕБИТО ВЕДУЩИМ');
 const epoch=state.epoch;
 const item=feedItem('ТЫ',null,'human');item.body.textContent=text;item.meta.textContent=new Date().toLocaleTimeString('ru-RU');
 try{
  const s=await coreEvent('user',{text});if(epoch!==state.epoch)return;
  applyCore(s);
  if(newTopic!==null){
   $('topic').value=newTopic;fitTopicField();savePrefs();
   state.history=[{agent:-1,name:'Ведущий',text:newTopic?'Новая тема: '+newTopic:'Полностью смените тему, выберите другое направление. Не возвращайтесь к прошлому обсуждению.'}];
   state.journal=[];state.directorBudget=null;state.lastDonationName='';state.social.memory=[[],[],[]];updateScienceUI();
   system('Новая тема разговора: '+(newTopic||'свободная беседа'));
  }else{
   state.history.push({agent:-1,name:'Ведущий',text});state.history=state.history.slice(-16);
  }
  if(s.kind==='user_pause')system('Ведущий попросил притормозить. Эфир продолжается; для полной паузы есть отдельная кнопка.');
  claimNext();
 }catch(e){if(epoch===state.epoch)engineError(e)}
}


// Donations are locally simulated, not verified payments. They always enter
// a bounded FIFO and get a named on-air answer. Amount determines speech turns,
// NEVER authentication, account privileges or permission to command the model.
function donationTurns(amount){
 if(amount>=100)return 8;
 if(amount>=50)return 5;
 if(amount>=20)return 3;
 if(amount>=5)return 2;
 return 1;
}
// A tip buys an upper bound on attention, not eight forced rephrasings of
// "hi". Short messages are acknowledged quickly; substantive questions get
// the full tier budget. This avoids artificial repetition on large greetings.
function donationBudget(amount,text){
 const ceiling=donationTurns(amount);
 const clean=String(text||'').trim();
 if(/^(?:здарова|здорово|здравствуйте|привет|приветик|салют|хай|hello|hi|hey|спасибо|респект)(?:[!.,\s]*(?:пацаны|ребята|братаны|всем|народ|боты|друзья))?[!.,\s]*$/iu.test(clean))
   return 1;
 if(clean.length<25)return Math.min(ceiling,1);
 if(clean.length<70)return Math.min(ceiling,2);
 if(clean.length<125)return Math.min(ceiling,3);
 return ceiling;
}
// Detect semantic near-duplicates before scheduling *another* donation turn.
// This bounded lexical guard backs up the LLM prompt when it still loops.
function donationRepeats(responses){
 if(responses.length<2)return false;
 const normalize=text=>String(text||'').toLocaleLowerCase('ru')
   .replace(/[^\p{L}\p{N}]+/gu,' ').replace(/\s+/g,' ').trim();
 const last=normalize(responses[responses.length-1]);
 if(!last)return false;
 // Catch identical short answers, where a three-keyword threshold never fires.
 if(responses.slice(0,-1).some(old=>normalize(old)===last))return true;
 // Five-character stems recognize Russian declensions: робот/роботы/роботов.
 const words=text=>new Set(String(text).toLocaleLowerCase('ru')
   .replace(/[^\p{L}\p{N} ]/gu,' ').split(/\s+/u)
   .filter(w=>w.length>=4&&!/^(спасибо|зритель|донат|евро|братан)$/u.test(w))
   .map(w=>w.slice(0,5)));
 const latest=words(responses[responses.length-1]);
 if(latest.size<3)return false;
 for(const older of responses.slice(0,-1)){
   const previous=words(older);
   if(previous.size<3)continue;
   const overlap=[...latest].filter(w=>previous.has(w)).length;
   // Repeated paraphrases must not consume all large-donation slots.
   if(overlap>=3&&overlap/Math.min(latest.size,previous.size)>=.50&&
      overlap/Math.max(latest.size,previous.size)>=.34)return true;
 }
 return false;
}
async function activateNextDonation(){
 if(state.donationRouting||state.activeDonation||!state.running||state.paused||
    !state.donationQueue.length||state.stopping)return;
 // IMPORTANT: a high-priority donor waits until the current turn has been
 // completely synthesized and played. Only the human host may barge in.
 if(state.current||speech.playing||speech.queue.length||speech.nodes.size){
   stopTimer();state.timer=setTimeout(claimNext,200);
   return;
 }
 state.donationRouting=true;
 const epoch=state.epoch,donation=state.donationQueue[0];
 donation.item.meta.textContent='⚡ ПЕРЕДАЁМ СЛОВО · предыдущая реплика завершена';
 try{
  const target=state.core?.next_agent>=0&&state.core?.next_agent<3?
    state.core.next_agent:0;
  const routed=await coreEvent('priority_donation',{agent:target});
  if(epoch!==state.epoch||state.stopping)return;
  if(!routed.accepted)throw Error('C-ядро не подтвердило передачу слова');
  state.donationQueue.shift();
  state.activeDonation=donation;updateDonationBadge();
  donation.nextSpeaker=target;
  cancelDirector(); // background planning may be cancelled, never speech.
  applyCore(routed);
  donation.item.meta.textContent='В ЭФИРЕ · до '+donation.total+' реплик · ждём ответа';
 }catch(err){
  if(epoch===state.epoch){
    donation.item.meta.textContent='⚠ ОЖИДАЕТ ПЕРЕДАЧИ СЛОВА · '+err.message;
    // Leave the accepted tip in the FIFO for the next *valid* transition.
  }
 }finally{
  state.donationRouting=false;
  if(epoch===state.epoch&&state.running&&!state.paused&&!state.current)
    scheduleNext();
 }
}
function donationMessage(){
 if(!state.running||state.stopping){system('Донат можно добавить во время эфира.');return;}
 const input=$('donationAmount'),raw=input.value.trim().replace(',','.'),amount=Number(raw);
 if(raw===''||!Number.isFinite(amount)||amount<0||amount>1000000){
   system('Неверная сумма доната: укажи число от 0 до 1 000 000.');return;
 }
 const cents=Math.round(amount*100),value=cents/100;
 const donor=($('donor').value.trim()||'Аноним').slice(0,32)
   .replace(/[\u202a-\u202e\u2066-\u2069<>]/g,'');
 const text=$('donationText').value.trim().slice(0,600)||
   'Спасибо за поддержку! Передаю привет всем участникам.';
 if(state.donationQueue.length>=256){
   system('Очередь донатов заполнена (256). Отправка не принята — попробуй позже.');return;
 }
 const total=donationBudget(value,text);
 const item=feedItem('⚡ ДОНАТ · '+donor,null,'donation');
 item.body.textContent='€'+value.toFixed(2)+' · '+text;
 item.meta.textContent='ПРИНЯТ · ждём окончания текущей реплики · до '+total+
   (total===1?' ответа':' реплик')+' · локальный тест';
 const donation={id:requestID(),donor,text,amount:value,remaining:total,total,item,
                 responses:[],acknowledged:false,nextSpeaker:0};
 state.donationQueue.push(donation);updateDonationBadge();
 // Cancel ONLY background listener verdicts; never generation or TTS.
 // This closes the auto-interrupt race for donors queued mid-sentence.
 if(state.current){
   state.current.intentSent=true;
   cancelListeners(state.current);
 }
 $('donationText').value='';
 // Do not cancel, mute or restart the current speaker. The normal turn
 // completion unlocks this FIFO. If already idle, claimNext performs routing.
 if(!state.current&&!state.activeDonation&&!state.paused&&!state.donationRouting)
   scheduleNext();
}
// If OpenAI doesn't produce any new text for 18s, leave this speaker and
// let C schedule another one. A successful reply resets the failure counter.
setInterval(async()=>{
 const c=state.current;
 if(!c||!state.running||state.paused||c.phase!=='generating'||c.timingOut)return;
 if(Date.now()-c.lastTokenAt<18000)return;
 c.timingOut=true;const ticket=c.ticket,epoch=state.epoch;
 if(c.donation&&state.activeDonation===c.donation)
   c.donation.nextSpeaker=(c.agent+1)%3;
 cancelCurrent('ТАЙМАУТ · нет ответа 18 секунд');
 try{
  const s=await coreEvent('recover',{ticket});
  if(epoch!==state.epoch)return;
  applyCore(s);system('Нет новых слов от LLM 18 секунд. Пробуем следующего агента ('+s.errors+'/3).');
  if(s.status==='RUNNING')scheduleNext();
  else if(s.status==='ERROR')system('Три зависания подряд. Требуется проверить подключение.');
 }catch(err){if(epoch===state.epoch)engineError(err)}
},1000);

// Best-effort audible watchdog.  If ChatGPT stalls or agents unanimously
// PASS, keep the Twitch show from going totally silent. This is a clearly
// labelled SYSTEM notice, never fabricated AI speech. Timers cannot run in a
// suspended browser tab; it is not a real-time SLA.
setInterval(()=>{
 if(!state.running||state.core?.status==='PAUSED'||speech.playing||speech.queue.length)return;
 const now=Date.now();
 if(now-state.lastAudibleAt<45000||now-state.lastIdleNotice<45000)return;
 state.lastIdleNotice=now;
 system('Слишком долгая тишина: проверяем связь. Это системное уведомление, не реплика агента.');
 if(audioAvailable()&&$('voiceEnabled').checked){
  speech.push(0,'Небольшая техническая пауза. Проверяем связь с LLM.');
 }
},1000);

async function signIn(mode){
 try{
  const response=await api('/auth/start',{mode});
  window.location.assign(response.url);
 }catch(err){$('authnote').textContent='Ошибка входа: '+err.message;}
}
$('signin').onclick=()=>signIn(state.recoverable?'auto':state.connected?'switch':'auto');
$('switchaccount').onclick=()=>signIn('switch');
$('logout').onclick=async()=>{
 await stopDialogue();
 try{
  const r=await api('/auth/logout',{});
  await refreshStatus();
  if(!r.revoked)$('authnote').textContent='Локальный выход выполнен. Отзыв удалённого токена не подтверждён.';
 }catch(err){$('authnote').textContent='Ошибка выхода: '+err.message;}
};
$('provider').onchange=async()=>{
 const p=$('provider').value;
 try{await api('/provider',{provider:p});await refreshStatus();}
 catch(err){$('authnote').textContent='Ошибка: '+err.message;}
};
$('deepseekConnect').onclick=async()=>{
 const key=$('deepseekKey').value.trim();
 if(!key){$('deepseekNote').textContent='Вставь API-ключ.';return;}
 try{await api('/deepseek/connect',{api_key:key});await refreshStatus();}
 catch(err){$('deepseekNote').textContent='Ошибка: '+err.message;}
};
$('deepseekDisconnect').onclick=async()=>{
 try{await api('/deepseek/disconnect',{});await refreshStatus();}
 catch(err){$('deepseekNote').textContent='Ошибка: '+err.message;}
};
$('start').onclick=begin;
$('stop').onclick=async()=>{if(await stopDialogue())system('Диалог остановлен ведущим.');};
$('pause').onclick=async()=>{
 if(!state.running)return;
 state.epoch++;stopTimer();cancelDirector();cancelCurrent('ПАУЗА');
 const epoch=state.epoch;
 try{const s=await coreEvent(state.core?.status==='PAUSED'?'resume':'pause');if(epoch!==state.epoch||state.stopping)return;applyCore(s);if(s.status==='RUNNING')claimNext();}
 catch(e){engineError(e)}
};
// Optional browser speech-to-text (push-to-talk) for the human host.
// Browser/OS may process audio remotely; no always-on microphone is activated.
const micButton=$('mic');
if(!SpeechInput){micButton.disabled=true;micButton.title='Распознавание речи недоступно в этом браузере';}
else micButton.onclick=()=>{
 if(micRecognition){try{micRecognition.stop()}catch(_){}return;}
 if(!state.running||state.core?.status==='PAUSED'){
  system('Микрофон доступен только во время разговора, вне ручной паузы.');return;
 }
 const rec=new SpeechInput();micRecognition=rec;
 rec.lang='ru-RU';rec.continuous=false;rec.interimResults=true;
 let spoken='';
 rec.onstart=()=>{
  // Acoustic echo prevention: don't feed TRIAD speech back into the mic.
  speech.stop();micButton.textContent='■ ЗАКОНЧИТЬ ФРАЗУ';
 };
 rec.onresult=e=>{
  let interim='';
  for(let i=e.resultIndex;i<e.results.length;i++){
   const part=e.results[i][0]?.transcript||'';
   if(e.results[i].isFinal)spoken+=part+' ';
   else interim+=part;
  }
  $('interject').value=(spoken+interim).slice(0,600);
 };
 rec.onerror=e=>{if(e.error!=='no-speech'&&e.error!=='aborted')system('Микрофон: '+e.error);};
 rec.onend=()=>{
  micRecognition=null;micButton.textContent='🎙 ГОВОРИТЬ';
  if(spoken.trim()&&state.running&&state.core?.status!=='PAUSED'){
   $('interject').value=spoken.trim().slice(0,600);humanMessage();
  }
 };
 try{rec.start()}catch(err){micRecognition=null;micButton.textContent='🎙 ГОВОРИТЬ';system('Микрофон: '+err.message);}
};
$('reloadmodels').onclick=fetchModels;
$('model').onchange=savePrefs;
const fitTopicField=()=>{
 const field=$('topic'),maxHeight=parseFloat(getComputedStyle(field).maxHeight)||132;
 field.style.height='auto';
 field.style.height=Math.min(field.scrollHeight,maxHeight)+'px';
 field.style.overflowY=field.scrollHeight>maxHeight?'auto':'hidden';
};
$('topic').oninput=()=>{fitTopicField();state.social.memory=[[],[],[]];cancelDirector();resetSocialFocus();savePrefs()};
$('sharedGoal').oninput=savePrefs;
$('showMode').onchange=()=>{state.journal=[];state.social.memory=[[],[],[]];cancelDirector();resetSocialFocus();updateScienceUI();savePrefs();if(state.running)system('Режим изменён: применится к следующей реплике.');};
$('auto').onchange=savePrefs;
$('directorEnabled').onchange=()=>{
 if(!$('directorEnabled').checked){
   cancelDirector();$('directorStatus').textContent='ИИ-режиссёр выключен · C-ядро маршрутизирует диалог';
 }else{$('directorStatus').textContent='ИИ-режиссёр включён · анализ каждые 4 реплики';}
 savePrefs();
};
$('sendInterject').onclick=humanMessage;
$('sendDonation').onclick=donationMessage;$('donationText').onkeydown=e=>{if(e.key==='Enter')donationMessage()};$('interject').onkeydown=e=>{if(e.key==='Enter')humanMessage()};
$('voiceEnabled').onchange=()=>{if(!$('voiceEnabled').checked)speech.stop();savePrefs()};
$('voiceStudioButton').onclick=()=>{
 const voicePanel=$('voiceSettings'),button=$('voiceStudioButton');
 voicePanel.open=!voicePanel.open;button.setAttribute('aria-expanded',String(voicePanel.open));
};
document.addEventListener('keydown',event=>{
 if(event.key!=='Escape')return;
 const voicePanel=$('voiceSettings'),connectPanel=$('connectPanel'),button=$('voiceStudioButton');
 let closed=false;
 if(voicePanel?.open){voicePanel.open=false;button?.setAttribute('aria-expanded','false');closed=true;}
 if(connectPanel?.open){connectPanel.open=false;closed=true;}
 if(closed)event.preventDefault();
});
// Backend changes apply to the next utterance; only explicit mute/STOP interrupts.
$('ttsBackend').onchange=()=>{syncVoicePanel();forceRenderCards();savePrefs();};
$('rate').oninput=()=>{$('rateValue').textContent=Number($('rate').value).toFixed(2)+'×';savePrefs()};
$('export').onclick=()=>{
 const logs=state.archivedLines.concat([...$('feed').querySelectorAll('.message')].map(transcriptLine));
 if($('showMode').value==='science'&&state.journal.length){
  logs.push('TRIAD SCIENCE / ЖУРНАЛ НЕПРОВЕРЕННЫХ ГИПОТЕЗ');
  logs.push(...state.journal.map((f,i)=>`${i+1}. [${PHASE_LABEL[f.phase]}] ${f.speaker}: ${f.claim}`));
 }
 const blob=new Blob([logs.join('\n\n')],{type:'text/plain;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='TRIAD-v0.2.0-'+new Date().toISOString().slice(0,10)+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1500);
};
window.addEventListener('beforeunload',()=>{cancelDirector();if(micRecognition){try{micRecognition.abort()}catch(_){}}speech.stop();if(state.current){state.current.controller.abort();cancelListeners(state.current);}});
restorePrefs();fitTopicField();updateScienceUI();renderCards();$('feed').innerHTML='<div class="empty">ОЖИДАНИЕ СИГНАЛА\nПОДКЛЮЧИ CHATGPT И ЗАПУСТИ ЭФИР</div>';
if(haveSpeech){populateVoices();window.speechSynthesis.onvoiceschanged=populateVoices;}
refreshStatus();
fetch('/api/engine').then(r=>{if(!r.ok)throw Error('Ядро C недоступно');return r.json()})
 .then(s=>{if(!state.current)applyCore(s)})
 .catch(e=>{system('Критическая ошибка: '+e.message);runStatus('НЕТ ЯДРА C')});


const addons=[
 {key:'kokoro-ru',id:'kokoroRu',state:kokoroRuState},
 {key:'kokoro',id:'kokoro',state:kokoroState},
 {key:'piper',id:'piper',state:piperState},
 {key:'silero',id:'silero',state:sileroState},
 {key:'qwen3-tts',id:'qwen3',state:qwen3State}
];
const engineHints={
 kokoro:'Kokoro 82M · выбери модель: русский (Света, Маша, Дима) или английский INT8',
 piper:'Piper · четыре русских голоса · ONNX · низкая задержка',
 silero:'Silero V5 · пять русских голосов · автоматические ударения',
 'qwen3-tts':'Qwen3-TTS MLX · Apple Silicon · клонирование / дизайн / кастомные голоса',
 browser:'Голоса macOS и браузера · не требуют установки'
};
let activeVoiceBackend=null;
function activateVoiceEngine(selected){
 if(activeVoiceBackend===selected)return;
 const old=activeVoiceBackend;
 activeVoiceBackend=selected;
 if(addons.some(a=>a.key===old)){
  api('/api/voice/'+old+'/deactivate',{}).catch(()=>{});
 }
 if(addons.some(a=>a.key===selected)){
  api('/api/voice/'+selected+'/activate',{}).then(result=>{
    const addon=addons.find(a=>a.key===selected);
    if(addon)renderAddonStatus(addon,result);
  }).catch(err=>console.warn('Запуск TTS:',err.message));
 }
}
$('testAudioOutput').onclick=async()=>{
 try{
  const C=window.AudioContext||window.webkitAudioContext;
  if(!C)throw Error('Web Audio недоступен');
  const ctx=speech.ctx||(speech.ctx=new C());
  await ctx.resume();
  if(ctx.state!=='running')throw Error('Аудиоконтекст не запущен');
  const osc=ctx.createOscillator(),gain=ctx.createGain();
  osc.type='sine';osc.frequency.value=440;
  gain.gain.setValueAtTime(.0001,ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(.12,ctx.currentTime+.035);
  gain.gain.exponentialRampToValueAtTime(.0001,ctx.currentTime+.34);
  osc.connect(gain);gain.connect(ctx.destination);
  osc.onended=()=>{osc.disconnect();gain.disconnect()};
  osc.start();osc.stop(ctx.currentTime+.36);
  system('Аудиотест: короткий звуковой сигнал отправлен на выход. Если его не слышно, проверь звук Safari/macOS.');
 }catch(err){system('Ошибка аудиовыхода: '+err.message);}
};
// Voice choices live on character cards; this studio controls the TTS backend.
function setAgentVoice(agent,voice){
 const def=defs[agent],backend=$('ttsBackend').value;
 if(backend==='piper'){
  def.piperVoice=voice;
  if(piperState.ready)warmPiperVoice(voice);
 }else if(backend==='silero')def.sileroVoice=voice;
 else if(backend==='kokoro'){if(kokoroModel==='ru')def.kokoroRuVoice=voice;else def.kokoroVoice=voice;}
 else if(backend==='qwen3-tts')def.qwen3Voice=voice;
 else def.voiceURI=voice;
 savePrefs();
}
function kokoroBackendKey(){
 return $('ttsBackend').value==='kokoro' ? (kokoroModel==='ru'?'kokoro-ru':'kokoro') : $('ttsBackend').value;
}
function syncVoicePanel(){
 const selected=$('ttsBackend').value;
 const effective=kokoroBackendKey();
 // Render immediately, irrespective of asynchronous engine activation.
 for(const addon of addons){
  $(addon.id+'Installer').hidden=addon.key!==effective;
 }
 $('browserInstaller').hidden=selected!=='browser';
 const wrap=$('kokoroModelWrap');if(wrap)wrap.hidden=selected!=='kokoro';
 $('voiceHint').textContent=engineHints[selected]||'';
 activateVoiceEngine(effective);
}
function renderAddonStatus(addon,data){
 const id=addon.id,job=data.installation||{},state=addon.state;
 const previous=state.ready;
 state.ready=!!data.ready;state.installation=job;
 state.status=data.status||'stopped';
 const failure=(data.status==='ready'||data.status==='starting')?'':(data.error||job.error||'');
 $(id+'Status').textContent=job.running?'УСТАНОВКА · '+(job.message||'Подготовка'):
   data.status==='ready'?'● ГОТОВО · модель загружена в память':
   data.status==='starting'?'◌ ЗАГРУЗКА В ПАМЯТЬ · первая инициализация':
   data.status==='error'?'ОШИБКА ЗАПУСКА · '+failure:
   data.installed?'Модель установлена · нажми «ПЕРЕЗАПУСТИТЬ ДВИЖОК»':'Не установлена';
 const dir=$(id+'Directory');
 if(!dir.dataset.userEdited&&data.directory)dir.value=data.directory;
 $(id+'Install').disabled=!!job.running;
 $(id+'Install').textContent=data.status==='error'||(data.installed===false&&job.percent===100)?
  '↻ ВОССТАНОВИТЬ УСТАНОВКУ':'↓ УСТАНОВИТЬ / ПОДКЛЮЧИТЬ';
 $(id+'Browse').disabled=!!job.running;
 $(id+'Cancel').hidden=!job.running;
 $(id+'Restart').hidden=!data.installed||job.running||
   (data.status!=='error'&&data.status!=='stopped');
 const bar=$(id+'Progress'),wrap=$(id+'ProgressWrap');
 const loading=data.status==='starting'&&!job.running;
 wrap.hidden=!(job.running||loading||job.percent===100||failure||job.message?.includes('отменена'));
 if(loading)bar.removeAttribute('value');
 else if(typeof job.percent==='number')bar.value=Math.max(0,Math.min(100,job.percent));
 else bar.removeAttribute('value');
 const stepMap={python:'Python',deps:'зависимости',models:'модели',repair:'RUAccent',load:'загрузка в память',done:'готово'};
 const stepName=job.step?stepMap[job.step]||job.step:'';
 $(id+'ProgressPercent').textContent=loading?'…':typeof job.percent==='number'?job.percent+'%':'…';
 $(id+'ProgressLabel').textContent=loading?'Инициализация модели — проверяем готовность…':(stepName?stepName+': ':'')+(job.message||'Подготовка');
 let detail=job.filename||'';
 if(job.total_bytes){
  detail+=' · '+humanBytes(job.downloaded_bytes||0)+' / '+humanBytes(job.total_bytes);
  if(job.speed_bytes>0)detail+=' · '+humanBytes(job.speed_bytes)+'/с';
  if(job.eta_seconds>0)detail+=' · ~'+Math.max(1,Math.round(job.eta_seconds))+' с';
 }
 if(job.files_total>1)detail+=' · файл '+Math.min(job.files_total,(job.files_done||0)+1)+'/'+job.files_total;
 $(id+'ProgressFile').textContent=detail;
 $(id+'Error').hidden=!failure;
 $(id+'Error').textContent=failure;

 if(previous!==state.ready&&$('ttsBackend').value===addon.key){
   forceRenderCards();
   if(addon.key==='piper'&&state.ready)warmPiperVoices();
 }
}
function warmPiperVoice(voice){
 if(!piperState.ready)return;
 api('/api/voice/piper/warmup',{voice}).catch(err=>console.warn('Piper preload:',err.message));
}
function warmPiperVoices(){
 if(!piperState.ready||$('ttsBackend').value!=='piper')return;
 // Loading all ONNX voices at once can starve the first audible phrase.
 warmPiperVoice(defs[0].piperVoice||piperSpeakers[0][0]);
}
async function refreshAddon(addon){
 try{
  const r=await fetch('/api/voice/'+addon.key+'/status',{cache:'no-store'});
  if(!r.ok)throw Error('HTTP '+r.status);
  renderAddonStatus(addon,await r.json());
 }catch(err){
  addon.state.ready=false;
  $(addon.id+'Status').textContent='Ошибка проверки состояния: '+err.message;
 }
}
for(const addon of addons){
 const id=addon.id,route='/api/voice/'+addon.key;
 $(id+'Directory').oninput=()=>{$(id+'Directory').dataset.userEdited='yes'};
 $(id+'Browse').onclick=async()=>{
  try{
   const value=await api(route+'/browse',{});
   $(id+'Directory').value=value.directory;$(id+'Directory').dataset.userEdited='yes';
  }catch(err){$(id+'Error').hidden=false;$(id+'Error').textContent=err.message;}
 };
 $(id+'Install').onclick=async()=>{
  try{
   const body={directory:$(id+'Directory').value};
   if(addon.key==='qwen3-tts')body.size=qwen3Size;
   await api(route+'/install',body);
   $(id+'Directory').dataset.userEdited='';
   await refreshAddon(addon);
  }catch(err){$(id+'Error').hidden=false;$(id+'Error').textContent=err.message;}
 };
 $(id+'Cancel').onclick=async()=>{
  try{await api(route+'/cancel',{});await refreshAddon(addon)}
  catch(err){system(err.message)}
 };
 $(id+'Restart').onclick=async()=>{
  $(id+'Restart').disabled=true;
  try{
   renderAddonStatus(addon,await api(route+'/activate',{}));
  }catch(err){
   $(id+'Error').hidden=false;
   $(id+'Error').textContent=err.message;
  }finally{$(id+'Restart').disabled=false;}
 };
 let initial=true;
 async function poll(){
  if(initial||$('ttsBackend').value===addon.key||addon.state.installation?.running||addon.state.status==='starting')await refreshAddon(addon);
  initial=false;
  setTimeout(poll,addon.state.installation?.running?1200:6000);
 }
 poll();
}
syncVoicePanel();
// Qwen3 custom voices live in one shared folder for both Pro (1.7B) and Lite (0.6B).
function refreshQwen3VoiceSelects(){
 if($('ttsBackend').value!=='qwen3-tts')return;
 defs.forEach((d,i)=>{const sel=$('cards').children[i]?.querySelector('.voice-controls select');if(sel)optionsForVoices(sel,i)});
}
function renderQwen3Voices(){
 const list=$('qwen3VoiceList');if(!list)return;
 list.replaceChildren();
 if(!qwen3Voices.length){
  const empty=document.createElement('p');empty.className='tts-install-hint';empty.textContent='Кастомных голосов пока нет — нажми «+».';
  list.append(empty);
 }else{
  for(const v of qwen3Voices){
   const row=document.createElement('div');row.className='qwen3-voice-row';
   const kind=v.mode==='preset'?'пресет':v.mode==='design'?'дизайн':'клонирование';
   const label=document.createElement('span');label.textContent=v.name+' · '+kind;
   const del=document.createElement('button');del.type='button';del.textContent='✕';del.title='Удалить голос';
   del.onclick=async()=>{try{await api('/api/qwen3/voices/delete',{id:v.id});}catch(e){system(e.message);}loadQwen3Voices();};
   row.append(label,del);list.append(row);
  }
 }
 refreshQwen3VoiceSelects();
}
async function loadQwen3Voices(){
 try{
  const r=await fetch('/api/qwen3/voices',{cache:'no-store'});
  if(!r.ok)throw Error('HTTP '+r.status);
  const data=await r.json();
  qwen3Voices=Array.isArray(data.custom)?data.custom:[];
  if(data.builtin&&typeof data.builtin==='object'){
   for(const size of ['lite','pro']){
    if(Array.isArray(data.builtin[size])&&data.builtin[size].length)
     qwen3BuiltinSpeakers[size]=data.builtin[size];
   }
  }
 }catch(err){qwen3Voices=[];}
 populateQwen3PresetSpeaker();
 renderQwen3Voices();
}
function populateQwen3PresetSpeaker(){
 const sel=$('qwen3PresetSpeaker');if(!sel)return;
 const current=sel.value;
 sel.replaceChildren();
 for(const s of qwen3SpeakerList())sel.add(new Option(s,s));
 if([...sel.options].some(o=>o.value===current))sel.value=current;
}
function syncQwen3VoiceForm(){
 const designUnavailable=qwen3Size==='lite';
 const typeSel=$('qwen3VoiceType');
 const designOption=typeSel.querySelector('option[value="design"]');
 designOption.disabled=designUnavailable;
 designOption.title=designUnavailable?'Дизайн голоса доступен только в Pro (1.7B)':'';
 let type=typeSel.value;
 if(designUnavailable&&type==='design'){type='preset';typeSel.value='preset';}
 $('qwen3DesignFields').hidden=type!=='design';
 $('qwen3CloneFields').hidden=type!=='clone';
 $('qwen3PresetFields').hidden=type!=='preset';
}
function readFileAsBase64(file){
 return new Promise((resolve,reject)=>{
  const r=new FileReader();
  r.onload=()=>resolve(String(r.result).split(',')[1]||'');
  r.onerror=()=>reject(Error('Не удалось прочитать аудиофайл'));
  r.readAsDataURL(file);
 });
}
async function saveQwen3Voice(){
 const payload={name:$('qwen3VoiceName').value.trim(),mode:$('qwen3VoiceType').value};
 if(payload.mode==='design')payload.instruct=$('qwen3DesignInstruct').value.trim();
 else if(payload.mode==='preset'){
  payload.speaker=$('qwen3PresetSpeaker').value;
  payload.instruct=$('qwen3PresetInstruct').value.trim()||'Normal tone';
  payload.speed=Number($('qwen3PresetSpeed').value)||1;
 }else{
  payload.ref_text=$('qwen3CloneText').value.trim();
  const file=$('qwen3CloneAudio').files[0];
  if(file){
   if(file.size>12*1024*1024){system('Аудиофайл слишком большой (максимум 12 МиБ).');return;}
   payload.ref_audio_b64=await readFileAsBase64(file);
  }
 }
 const err=$('qwen3Error');
 try{
  await api('/api/qwen3/voices',payload);
  $('qwen3VoiceForm').hidden=true;
  err.hidden=true;
  await loadQwen3Voices();
 }catch(e){err.hidden=false;err.textContent=e.message;}
}
$('qwen3Size').onchange=()=>{qwen3Size=$('qwen3Size').value;savePrefs();syncQwen3VoiceForm();populateQwen3PresetSpeaker();refreshQwen3VoiceSelects();};
$('kokoroModel').onchange=()=>{kokoroModel=$('kokoroModel').value;syncVoicePanel();forceRenderCards();savePrefs();};
$('qwen3AddVoice').onclick=()=>{$('qwen3VoiceForm').hidden=false;$('qwen3VoiceName').value='';$('qwen3VoiceType').value=qwen3Size==='lite'?'preset':'design';syncQwen3VoiceForm();};
$('qwen3VoiceType').onchange=syncQwen3VoiceForm;
$('qwen3VoiceSave').onclick=saveQwen3Voice;
$('qwen3VoiceCancel').onclick=()=>{$('qwen3VoiceForm').hidden=true;};
populateQwen3PresetSpeaker();
loadQwen3Voices();
